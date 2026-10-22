# CryoBytePrime Candle Downloader

## Official rate limits (developers.deriv.com/docs/limits)
- ticks_history is under **All other calls**: **220/min**, **14,400/hour**
- Heavy history may also return `ticks_history_expensive` — longer cool-downs apply

## Pacing
| Timeframe | Pause between pages |
|-----------|---------------------|
| 1m        | ~2.0s               |
| ≤15m      | ~1.5s               |
| H1+       | ~0.45s              |

## Checkpoint / resume (CLI)
Progress is saved under `.checkpoints/` and `.partial/`.
If a job fails mid-way, **re-run the same command** — it continues from the last epoch.

```bash
pip install websocket-client
python deriv_candle_downloader.py -s BOOM150N -d 365 --tf M15 H1 H4 D1 -o ./data
# if rate-limited on M15, run the same line again to resume
```

## Browser UI
```bash
npx serve .
```
Checkpoints stored in localStorage; same job re-run resumes.
