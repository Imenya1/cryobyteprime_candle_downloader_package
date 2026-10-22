#!/usr/bin/env python3
"""
CryoBytePrime / Deriv candle downloader (CLI)
- Official budget: ticks_history in "All other calls" = 220/min, 14400/hour
- Extra server throttle: ticks_history_expensive on heavy history
- Checkpoint + resume: saves partial CSV and continues from earliest epoch
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from websocket import create_connection
except ImportError:
    raise SystemExit("pip install websocket-client")

PAGE = 2000
MAX_RETRIES = 10
# Stay under 220/min with margin → ~2.5 req/s max; fine TF slower
MIN_INTERVAL_DEFAULT = 0.45   # ~133/min
MIN_INTERVAL_FINE = 1.5       # granularity <= 900 (15m and below)
MIN_INTERVAL_M1 = 2.0         # granularity == 60

WS_ENDPOINTS = [
    "wss://api.derivws.com/trading/v1/options/ws/public",
    "wss://ws.derivws.com/websockets/v3?app_id={app_id}",
    "wss://ws.binaryws.com/websockets/v3?app_id={app_id}",
    "wss://frontend.binaryws.com/websockets/v3?app_id={app_id}",
]

TF_MAP = {
    "M1": 60, "1m": 60, "M2": 120, "2m": 120, "M3": 180, "3m": 180,
    "M5": 300, "5m": 300, "M10": 600, "10m": 600, "M15": 900, "15m": 900,
    "M30": 1800, "30m": 1800, "H1": 3600, "1h": 3600, "H2": 7200, "2h": 7200,
    "H4": 14400, "4h": 14400, "H8": 28800, "8h": 28800, "D1": 86400, "1d": 86400,
}


def resolve_tfs(items: list[str]) -> list[int]:
    out = []
    for x in items:
        k = x.strip()
        if k.isdigit():
            out.append(int(k))
        elif k.upper() in TF_MAP or k.lower() in TF_MAP:
            out.append(TF_MAP.get(k.upper()) or TF_MAP[k.lower()])
        else:
            raise SystemExit(f"Unknown timeframe: {x}")
    return out


def tf_label(g: int) -> str:
    for k, v in TF_MAP.items():
        if v == g and k[0].isupper():
            return k
    return str(g)


def min_interval(g: int) -> float:
    if g <= 60:
        return MIN_INTERVAL_M1
    if g <= 900:
        return MIN_INTERVAL_FINE
    return MIN_INTERVAL_DEFAULT


class RateLimiter:
    """Pace requests under official 220/min budget with TF-aware floors."""

    def __init__(self):
        self._last = 0.0

    def wait(self, granularity: int) -> None:
        need = min_interval(granularity)
        now = time.monotonic()
        gap = need - (now - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


class DerivAPI:
    def __init__(self, app_id: str = "1089", timeout: float = 30.0):
        self.app_id = app_id
        self.timeout = timeout
        self.ws = None
        self._id = 0
        self.limiter = RateLimiter()

    def connect(self) -> dict:
        last_err: Exception | None = None
        for tmpl in WS_ENDPOINTS:
            url = tmpl.format(app_id=self.app_id)
            try:
                self.ws = create_connection(
                    url,
                    timeout=self.timeout,
                    header=[
                        "Origin: https://app.deriv.com",
                        "User-Agent: CryoBytePrimeCandleDownloader/3.0",
                    ],
                )
                pong = self.request({"ping": 1}, granularity=86400)
                print(f"Endpoint: {url}", flush=True)
                return pong
            except Exception as e:
                last_err = e
                print(f"  skip {url.split('?')[0]} — {e}", flush=True)
                self.close()
        raise RuntimeError(f"All endpoints failed. Last error: {last_err}")

    def close(self) -> None:
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def request(self, payload: dict, granularity: int = 3600) -> dict:
        if not self.ws:
            raise RuntimeError("not connected")
        self.limiter.wait(granularity)
        last_err = None
        for attempt in range(MAX_RETRIES):
            self._id += 1
            rid = self._id
            msg = dict(payload)
            msg["req_id"] = rid
            self.ws.send(json.dumps(msg))
            while True:
                raw = self.ws.recv()
                data = json.loads(raw)
                if data.get("req_id") != rid:
                    continue
                if data.get("error"):
                    err = data["error"]
                    err_text = err.get("message") or str(err)
                    code = str(err.get("code") or "")
                    rate_limited = (
                        "rate limit" in err_text.lower()
                        or "ticks_history_expensive" in err_text.lower()
                        or code.lower() in ("ratelimit", "rate_limit")
                    )
                    if rate_limited and attempt < MAX_RETRIES - 1:
                        # respect hourly budget: long cool-down
                        wait = min(120.0, 8.0 * (2 ** attempt))
                        print(
                            f"  rate limit — waiting {wait:.0f}s "
                            f"(retry {attempt + 1}/{MAX_RETRIES})",
                            flush=True,
                        )
                        time.sleep(wait)
                        last_err = err_text
                        break
                    raise RuntimeError(err_text)
                return data
        raise RuntimeError(last_err or "request failed")

    def list_symbols(self) -> list[dict]:
        msg = self.request({"active_symbols": "brief"}, granularity=86400)
        out = []
        for s in msg.get("active_symbols") or []:
            sym = s.get("underlying_symbol") or s.get("symbol")
            if not sym:
                continue
            out.append({
                "symbol": sym,
                "display": s.get("underlying_symbol_name") or s.get("display_name") or "",
                "market": s.get("market") or "",
            })
        out.sort(key=lambda x: x["symbol"])
        return out


def checkpoint_path(outdir: Path, symbol: str, label: str) -> Path:
    d = outdir / ".checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{symbol}_{label}.json"


def partial_path(outdir: Path, symbol: str, label: str) -> Path:
    d = outdir / ".partial"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{symbol}_{label}.csv"


def load_checkpoint(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_checkpoint(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


def write_csv(path: Path, rows: list[dict], append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append and path.exists() else "w"
    with path.open(mode, encoding="utf-8") as f:
        if mode == "w":
            f.write("epoch,datetime_utc,open,high,low,close\n")
        for c in rows:
            e = int(c["epoch"])
            dt = datetime.fromtimestamp(e, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{e},{dt},{c['open']},{c['high']},{c['low']},{c['close']}\n")


def merge_and_finalize(partial: Path, final: Path, start_epoch: int, end_epoch: int, g: int) -> int:
    """Load partial CSV, de-dupe, filter closed bars, write final."""
    if not partial.exists():
        return 0
    seen: dict[int, dict] = {}
    with partial.open(encoding="utf-8") as f:
        next(f, None)  # header
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 6:
                continue
            e = int(parts[0])
            seen[e] = {
                "epoch": e,
                "open": parts[2],
                "high": parts[3],
                "low": parts[4],
                "close": parts[5],
            }
    rows = [
        c for e, c in sorted(seen.items())
        if e >= start_epoch and e + g <= end_epoch
    ]
    write_csv(final, rows, append=False)
    return len(rows)


def gap_report(rows: list[dict], g: int) -> str:
    gaps = missing = 0
    for i in range(1, len(rows)):
        d = int(rows[i]["epoch"]) - int(rows[i - 1]["epoch"])
        if d > g:
            gaps += 1
            missing += d // g - 1
    note = f"{len(rows)} closed candles"
    if gaps:
        note += f", {gaps} gap(s), ~{missing} missing"
    else:
        note += ", continuous"
    return note


def fetch_candles(
    api: DerivAPI,
    symbol: str,
    g: int,
    start_epoch: int,
    end_epoch: int,
    outdir: Path,
    label: str,
) -> list[dict]:
    """
    Backward page with checkpoint.
    Cursor starts at end_epoch, or earliest_epoch-1 if resuming.
    Every page is appended to partial CSV; checkpoint stores cursor.
    """
    cp = checkpoint_path(outdir, symbol, label)
    partial = partial_path(outdir, symbol, label)
    ck = load_checkpoint(cp)

    cursor = end_epoch
    resumed = False
    if ck and ck.get("start_epoch") == start_epoch and ck.get("end_epoch") == end_epoch and ck.get("granularity") == g:
        if ck.get("status") == "done":
            print(f"  checkpoint: already complete — reusing", flush=True)
            final = outdir / f"{symbol}_{label}.csv"
            if final.exists():
                # reload for gap report
                rows = []
                with final.open(encoding="utf-8") as f:
                    next(f, None)
                    for line in f:
                        p = line.strip().split(",")
                        if len(p) >= 6:
                            rows.append({"epoch": int(p[0]), "open": p[2], "high": p[3], "low": p[4], "close": p[5]})
                return rows
        if ck.get("earliest_epoch"):
            cursor = int(ck["earliest_epoch"]) - 1
            resumed = True
            print(
                f"  RESUME from epoch {ck['earliest_epoch']} "
                f"({ck.get('pages', 0)} pages, {ck.get('unique', 0)} bars so far)",
                flush=True,
            )

    if not resumed and partial.exists():
        partial.unlink()

    seen_session: set[int] = set()
    guard = 0
    stagnant = 0
    pages = int(ck.get("pages", 0)) if resumed and ck else 0
    earliest = int(ck["earliest_epoch"]) if resumed and ck and ck.get("earliest_epoch") else None

    while cursor > start_epoch and guard < 50000:
        guard += 1
        try:
            msg = api.request(
                {
                    "ticks_history": symbol,
                    "style": "candles",
                    "granularity": g,
                    "end": cursor,
                    "count": PAGE,
                    "adjust_start_time": 1,
                },
                granularity=g,
            )
        except RuntimeError as e:
            # persist progress then re-raise
            save_checkpoint(cp, {
                "symbol": symbol,
                "granularity": g,
                "label": label,
                "start_epoch": start_epoch,
                "end_epoch": end_epoch,
                "earliest_epoch": earliest,
                "pages": pages,
                "unique": pages and None,  # filled below
                "status": "paused",
                "error": str(e),
                "updated": datetime.now(timezone.utc).isoformat(),
            })
            # count unique in partial
            n = 0
            if partial.exists():
                with partial.open() as f:
                    n = max(0, sum(1 for _ in f) - 1)
            ck2 = load_checkpoint(cp) or {}
            ck2["unique"] = n
            save_checkpoint(cp, ck2)
            print(f"  PAUSED — progress saved ({n} bars). Re-run the same command to resume.", flush=True)
            raise

        rows = msg.get("candles") or []
        if not rows:
            break

        first = min(int(c["epoch"]) for c in rows)
        batch = []
        for c in rows:
            e = int(c["epoch"])
            if e not in seen_session:
                seen_session.add(e)
                batch.append(c)

        if batch:
            write_csv(partial, batch, append=partial.exists())
            pages += 1
            earliest = first if earliest is None else min(earliest, first)
            save_checkpoint(cp, {
                "symbol": symbol,
                "granularity": g,
                "label": label,
                "start_epoch": start_epoch,
                "end_epoch": end_epoch,
                "earliest_epoch": earliest,
                "pages": pages,
                "unique": (load_checkpoint(cp) or {}).get("unique", 0) + len(batch),
                "status": "in_progress",
                "updated": datetime.now(timezone.utc).isoformat(),
            })
            # fix unique count properly
            n = 0
            with partial.open() as f:
                n = max(0, sum(1 for _ in f) - 1)
            ck_now = load_checkpoint(cp) or {}
            ck_now["unique"] = n
            save_checkpoint(cp, ck_now)

        ts = datetime.fromtimestamp(first, tz=timezone.utc).isoformat()[:16]
        print(f"  page +{len(rows)}  → {ts}  (session new {len(batch)}, pages {pages})", flush=True)

        if len(batch) == 0 or first >= cursor:
            stagnant += 1
            if stagnant >= 2 or first >= cursor:
                break
        else:
            stagnant = 0
        if first <= start_epoch:
            break
        cursor = first - 1

    final = outdir / f"{symbol}_{label}.csv"
    n = merge_and_finalize(partial, final, start_epoch, end_epoch, g)
    save_checkpoint(cp, {
        "symbol": symbol,
        "granularity": g,
        "label": label,
        "start_epoch": start_epoch,
        "end_epoch": end_epoch,
        "earliest_epoch": earliest,
        "pages": pages,
        "unique": n,
        "status": "done",
        "updated": datetime.now(timezone.utc).isoformat(),
    })
    # optional: keep partial for audit; remove to save disk
    # partial.unlink(missing_ok=True)
    return [
        {"epoch": int(p[0]), "open": p[2], "high": p[3], "low": p[4], "close": p[5]}
        for p in (
            line.strip().split(",")
            for i, line in enumerate(final.read_text().splitlines())
            if i > 0 and line.strip()
        )
        if len(p) >= 6
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="CryoBytePrime Deriv candle downloader")
    ap.add_argument("-s", "--symbols", required=False, help="Comma-separated symbols")
    ap.add_argument("--list-symbols", action="store_true")
    ap.add_argument("-d", "--days", type=int, default=None)
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default=None)
    ap.add_argument("--tf", nargs="+", default=["M15", "H1"])
    ap.add_argument("-o", "--outdir", type=Path, default=Path("."))
    ap.add_argument("--app-id", default="1089")
    args = ap.parse_args()

    api = DerivAPI(app_id=args.app_id)
    try:
        api.connect()
        print("Connected: pong", flush=True)

        if args.list_symbols:
            for s in api.list_symbols():
                print(f"{s['symbol']:16} {s['display']}")
            return

        if not args.symbols:
            raise SystemExit("Provide -s SYMBOLS or --list-symbols")

        symbols = [x.strip() for x in args.symbols.split(",") if x.strip()]
        tfs = sorted(resolve_tfs(args.tf), reverse=True)

        now = datetime.now(timezone.utc)
        if args.days:
            end = now
            start = now - timedelta(days=args.days)
        else:
            if not args.date_from or not args.date_to:
                raise SystemExit("Use -d DAYS or --from/--to YYYY-MM-DD")
            start = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = datetime.strptime(args.date_to, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            if end > now:
                end = now

        start_epoch = int(start.timestamp())
        end_epoch = int(end.timestamp())
        args.outdir.mkdir(parents=True, exist_ok=True)

        print(
            f"Rate plan: ≤220/min official · paced "
            f"M1={MIN_INTERVAL_M1}s  ≤15m={MIN_INTERVAL_FINE}s  else={MIN_INTERVAL_DEFAULT}s",
            flush=True,
        )
        print(f"Checkpoint dir: {args.outdir / '.checkpoints'}", flush=True)

        for symbol in symbols:
            for g in tfs:
                label = tf_label(g)
                print(f"\n{symbol} {label}  {start.date()} → {end.date()}", flush=True)
                try:
                    rows = fetch_candles(api, symbol, g, start_epoch, end_epoch, args.outdir, label)
                    print(f"{label}: {gap_report(rows, g)}", flush=True)
                    if rows:
                        print(f"  wrote {args.outdir / f'{symbol}_{label}.csv'}", flush=True)
                except RuntimeError as e:
                    print(f"FAILED {symbol} {label}: {e}", flush=True)
                    print("  Re-run the same command to resume from checkpoint.", flush=True)
                time.sleep(1.0)

        print("\nDone.", flush=True)
    finally:
        api.close()


if __name__ == "__main__":
    main()
