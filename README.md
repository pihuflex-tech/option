# Nifty 50 Real-Time Option Chain & Paper Trading Terminal

An ultra-low latency (100ms) Nifty 50 option chain visualizer and virtual paper trading platform. Built on FastAPI, native browser WebSockets, and Angel One's SmartAPI (`SmartWebSocketV2`).

## Run on Windows

1. Install dependencies into the project environment:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set `SMARTAPI_KEY`, `CLIENT_CODE`,
   `MPIN`, and `TOTP_SECRET` to your Angel One credentials.
3. Start the server:

   ```powershell
   .\.venv\Scripts\python.exe run.py
   ```

The application obtains the SmartAPI JWT and feed tokens by logging in; do not
put JWT or feed tokens in `.env`. If credentials are missing or login fails,
the server stays available for paper trading, but live prices will not be
available.

## Features

- **Live in-memory pricing:** SmartAPI websocket ticks update the local quote
  cache; the browser receives option-chain and portfolio snapshots every
  500ms.
- **Indexed option master:** The daily contract master is indexed for fast
  NIFTY strike and expiry lookup.
- **Paper execution:** Orders use the latest cached quote when available and
  track virtual cash, positions, and mark-to-market P&L.