
#!/usr/bin/env python3
"""
Binance Testnet RSI Paper-Trading Bot (CCXT)
-------------------------------------------
• Exchange: Binance (Testnet / Sandbox mode via ccxt.set_sandbox_mode)
• Strategy: RSI mean-reversion on a chosen symbol/timeframe
• Mode: DRY-RUN by default. Use BOT_LIVE=true to place real orders (against Testnet API keys).
• Requirements: pip install ccxt pandas numpy python-dotenv
• Usage: export/test env vars (see below) and run `python main.py`
IMPORTANT: Use Testnet API keys from https://testnet.binance.vision/ for safety.
"""

import os
import time
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import ccxt
from dotenv import load_dotenv

load_dotenv()

# -------------------- User Settings (via env vars) --------------------
SYMBOL = os.getenv("BOT_SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("BOT_TIMEFRAME", "15m")
RSI_PERIOD = int(os.getenv("BOT_RSI_PERIOD", "14"))
RSI_OVERSOLD = float(os.getenv("BOT_RSI_OS", "30"))
RSI_OVERBOUGHT = float(os.getenv("BOT_RSI_OB", "70"))

# Risk settings
ACCOUNT_ALLOCATION_USD = float(os.getenv("BOT_ALLOCATION_USD", "200"))
RISK_PER_TRADE_USD = float(os.getenv("BOT_RISK_USD", "5"))
TAKE_PROFIT_R_MULTIPLE = float(os.getenv("BOT_TP_R", "1.5"))

# Order controls
MIN_NOTIONAL_USD = float(os.getenv("BOT_MIN_NOTIONAL_USD", "10"))
SLIPPAGE_BPS = float(os.getenv("BOT_SLIPPAGE_BPS", "10"))
POLL_SECONDS = int(os.getenv("BOT_POLL_SECONDS", "30"))
LIVE_TRADING = os.getenv("BOT_LIVE", "false").lower() == "true"
PRINT_BALANCES_EVERY = int(os.getenv("BOT_PRINT_BAL_EVERY", "20"))

# API keys (use Testnet keys)
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ---------------------------------------------------------------------

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(gain).rolling(window=period, min_periods=period).mean()
    roll_down = pd.Series(loss).rolling(window=period, min_periods=period).mean()
    rs = roll_up / roll_down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi.index = series.index
    return rsi

def pct_to_price(price: float, bps: float) -> float:
    return price * (1.0 + bps / 10000.0)

def round_amount(exchange, symbol, amount):
    market = exchange.market(symbol)
    precision = market.get('precision', {})
    amount_prec = precision.get('amount', None)
    if amount_prec is None:
        return amount
    step = 10 ** (-amount_prec)
    return math.floor(amount / step) * step

def round_price(exchange, symbol, price):
    market = exchange.market(symbol)
    precision = market.get('precision', {})
    price_prec = precision.get('price', None)
    if price_prec is None:
        return price
    step = 10 ** (-price_prec)
    return math.floor(price / step) * step

def fetch_ohlcv_df(exchange, symbol, timeframe, limit=200):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.set_index("ts", inplace=True)
    return df

def make_exchange():
    exchange = ccxt.binance({
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"}
    })
    # Use sandbox/testnet mode
    try:
        exchange.set_sandbox_mode(True)
    except Exception as e:
        print(f"[{utc_now_iso()}] Warning: set_sandbox_mode not available in this ccxt version: {e}")
    return exchange

def compute_signals(df: pd.DataFrame):
    df = df.copy()
    df["rsi"] = rsi(df["close"], RSI_PERIOD)
    df["buy_sig"] = (df["rsi"] < RSI_OVERSOLD)
    df["sell_sig"] = (df["rsi"] > RSI_OVERBOUGHT)
    return df

def size_position_usdt(entry_price: float) -> (float, float):
    stop_pct = 0.01
    qty = RISK_PER_TRADE_USD / (entry_price * stop_pct)
    max_qty = ACCOUNT_ALLOCATION_USD / entry_price
    qty = min(qty, max_qty)
    notional = qty * entry_price
    return qty, notional

def place_orders(exchange, symbol, side, entry_price, stop_price, take_profit_price, amount):
    results = {"entry": None, "stop": None, "tp": None}
    if LIVE_TRADING:
        entry_price = round_price(exchange, symbol, entry_price)
        amount = round_amount(exchange, symbol, amount)
        if amount * entry_price < MIN_NOTIONAL_USD:
            print(f"[{utc_now_iso()}] Skipping: below min notional ({amount*entry_price:.2f} < {MIN_NOTIONAL_USD})")
            return results
        try:
            # Place a limit order as entry
            results["entry"] = exchange.create_order(symbol, "limit", side, amount, entry_price)
            # Place TP and stop as separate limit orders (testnet supports these via normal orders)
            opp_side = "sell" if side == "buy" else "buy"
            results["tp"] = exchange.create_order(symbol, "limit", opp_side, amount, round_price(exchange, symbol, take_profit_price))
            # Note: Binance Testnet may not support stopLimit via unified ccxt; leaving stop as info only.
            results["stop"] = {"stop_price": stop_price}
        except Exception as e:
            print(f"[{utc_now_iso()}] Order placement failed: {e}")
    else:
        print(f"[DRY-RUN] Would place {side.upper()} LIMIT {amount:.6f} {symbol} @ {entry_price:.4f}")
        print(f"[DRY-RUN] Would set STOP @ {stop_price:.4f} and TP @ {take_profit_price:.4f}")
    return results

def main():
    print(f"=== Binance Testnet RSI Bot | LIVE_TRADING={LIVE_TRADING} | {utc_now_iso()} ===")
    exchange = make_exchange()
    markets = exchange.load_markets()
    if SYMBOL not in markets:
        raise SystemExit(f"Symbol {SYMBOL} not found on Binance Testnet markets. Available pairs example: {list(markets)[:10]}")
    iter_count = 0
    in_position = False
    position_side = None

    while True:
        try:
            df = fetch_ohlcv_df(exchange, SYMBOL, TIMEFRAME, limit=max(200, RSI_PERIOD + 10))
            df = compute_signals(df).dropna()
            last = df.iloc[-1]
            price = float(last["close"])
            rsi_v = float(last["rsi"])
            print(f"[{utc_now_iso()}] {SYMBOL} {TIMEFRAME} close={price:.4f} RSI={rsi_v:.2f}")

            if iter_count % PRINT_BALANCES_EVERY == 0:
                try:
                    bal = exchange.fetch_balance()
                    usdt_free = bal.get('USDT', {}).get('free', 0.0)
                    print(f"[{utc_now_iso()}] Free USDT (testnet): {usdt_free}")
                except Exception as e:
                    print(f"[{utc_now_iso()}] fetch_balance() failed: {e}")

            if not in_position:
                if last["buy_sig"]:
                    qty, notional = size_position_usdt(price)
                    entry_price = pct_to_price(price, -SLIPPAGE_BPS)
                    stop_price = price * 0.99
                    tp_price = price + TAKE_PROFIT_R_MULTIPLE * (price - stop_price)
                    place_orders(exchange, SYMBOL, "buy", entry_price, stop_price, tp_price, qty)
                    in_position = True
                    position_side = "long"
                elif last["sell_sig"]:
                    print(f"[{utc_now_iso()}] SELL signal (ignored on spot short).")
            else:
                # simple exit suggestion based on RSI crossing above 50
                if position_side == "long" and rsi_v > 50:
                    print(f"[{utc_now_iso()}] Exit condition met (RSI>{50}). Consider closing position.")
            iter_count += 1
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("Interrupted by user.")
            break
        except Exception as e:
            print(f"[{utc_now_iso()}] ERROR: {e}")
            time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
