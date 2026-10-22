# CryoBytePrime Candle Downloader

**Professional OHLCV historical data downloader for Deriv (Binary.com) markets**

A dual-interface tool (Browser UI + Python CLI) that fetches high-quality candle data from Deriv’s public WebSocket API with built-in rate-limit respect, automatic checkpointing, and resume capability.

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![Status](https://img.shields.io/badge/status-production--ready-brightgreen)
![Platform](https://img.shields.io/badge/platform-Web%20%7C%20CLI-lightgrey)

---

## Overview

CryoBytePrime Candle Downloader was built for traders, quant researchers, and developers who need reliable historical candle data from Deriv’s synthetic and forex markets.

It solves the common pain points of:
- Hitting official rate limits (`220 requests/min`)
- Losing progress on long multi-timeframe downloads
- Having to restart from scratch after network interruptions

Both the modern browser interface and the lightweight CLI share the same robust download engine and checkpoint system.

---

## Features

### Browser UI
- Clean, dark-themed single-page application
- Multi-timeframe selection (M1 → D1)
- Real-time progress tracking
- Automatic resume via `localStorage`
- One-click CSV download
- Fully client-side (no backend required)

### Python CLI
- High-performance WebSocket downloader
- Adaptive pacing based on timeframe granularity
- Disk-based checkpoints (`.checkpoints/` + `.partial/`)
- Resume any interrupted job by re-running the exact same command
- Supports multiple symbols and timeframes in one run
- Clean CSV output ready for backtesting or analysis

### Shared Strengths
- Respects official Deriv rate limits
- Handles `ticks_history_expensive` cool-downs gracefully
- Works with both real and synthetic indices (Boom, Crash, Step, Volatility, etc.)
- Zero external dependencies beyond `websocket-client` (CLI)

---

## Tech Stack

| Layer          | Technology                          |
|----------------|-------------------------------------|
| Frontend       | Vanilla HTML / CSS / JavaScript     |
| Backend (CLI)  | Python 3.9+                         |
| Protocol       | Deriv WebSocket API (public)        |
| Persistence    | localStorage (UI) / filesystem (CLI)|
| Deployment     | Static hosting (Vercel, Netlify…)   |

---

## Quick Start

### 1. Browser UI (Recommended for most users)

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/cryobyteprime-candle-downloader.git
cd cryobyteprime-candle-downloader

# Serve locally
npx serve .
# or
python -m http.server 8080
```

Open `http://localhost:3000` (or the port shown) and start downloading.

**Live Demo**  
Deploy the folder to Vercel in one click → [vercel.com/drop](https://vercel.com/drop)

### 2. Python CLI

```bash
pip install websocket-client

python deriv_candle_downloader.py \
  -s BOOM150N \
  -d 365 \
  --tf M15 H1 H4 D1 \
  -o ./data
```

If the download is interrupted, simply run the **exact same command** again — it will resume from the last saved checkpoint.

---

## CLI Usage Reference

```bash
python deriv_candle_downloader.py [OPTIONS]

Required:
  -s, --symbol      Symbol (e.g. BOOM150N, CRASH300N, R_100, frxEURUSD)
  -d, --days        Number of days of history to fetch

Optional:
  --tf              One or more timeframes (default: H1)
                    Supported: M1 M2 M3 M5 M10 M15 M30 H1 H2 H4 H8 D1
  -o, --output      Output directory (default: ./data)
  --app-id          Deriv App ID (default: 1089 – public)
```

**Example – multi-timeframe, 2 years**
```bash
python deriv_candle_downloader.py -s VOLATILITY_100 -d 730 --tf M5 M15 H1 H4 D1 -o ./vol100
```

---

## Rate Limits & Responsible Usage

According to [Deriv’s official documentation](https://developers.deriv.com/docs/limits):

| Limit Type              | Value          |
|-------------------------|----------------|
| ticks_history           | 220 / minute   |
| ticks_history           | 14,400 / hour  |
| Heavy history           | May trigger longer cool-down (`ticks_history_expensive`) |

The downloader automatically applies adaptive delays:

| Timeframe | Pause between pages |
|-----------|---------------------|
| 1-minute  | ~2.0 s              |
| ≤ 15-min  | ~1.5 s              |
| H1 and higher | ~0.45 s         |

This keeps the tool safely under the official limits while maximizing throughput.

---

## Project Structure

```
cryobyteprime-candle-downloader/
├── index.html                  # Full browser application
├── logo.jpeg                   # Brand asset
├── deriv_candle_downloader.py  # CLI engine
└── README.md
```

---

## Deployment (Vercel)

This project is a pure static site — perfect for Vercel:

1. Push to GitHub
2. Import repository on [vercel.com/new](https://vercel.com/new)
3. Framework Preset → **Other**
4. Build Command → leave empty
5. Output Directory → `.`
6. Deploy

Or simply drag the folder onto [vercel.com/drop](https://vercel.com/drop).

---

## Use Cases

- Building personal historical databases for backtesting
- Research on synthetic indices behaviour
- Feeding data into quant models or TradingView scripts
- Educational projects on market microstructure
- Portfolio demonstration of clean frontend + robust Python tooling

---

## Author

**CryoBytePrime**  
Built with attention to rate-limit ethics, user experience, and resume reliability.

---

## License

MIT License — free for personal and commercial use.

Feel free to fork, improve, and share.
