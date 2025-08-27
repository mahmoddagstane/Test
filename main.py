
#!/usr/bin/env python3
"""
Multi-Pair RSI + EMA Bot (Binance Testnet)
-------------------------------------------
- الأزواج: BTC/USDT, ETH/USDT, BNB/USDT, SOL/USDT
- كل زوج: رصيد افتراضي 200 دولار، مخاطرة 2%-3%
- مؤشرات: RSI + EMA20 & EMA50
- Take Profit / Stop Loss محسوبة
- الوضع الافتراضي: BOT_LIVE=false (Testnet)
"""

import os
import time
import math
import threading
import pandas as pd
import numpy as np
import ccxt
from datetime import datetime, timezone
from dotenv import load_dotenv

# تحميل متغيرات البيئة من .env (للتطوير المحلي فقط)
# load_dotenv() سيتم استدعاؤها في دالة get_secret() حسب الحاجة

def get_secret(key, default=None):
    """
    جلب المتغيرات من متغيرات البيئة (Secrets) أولاً، ثم من ملف .env
    """
    # محاولة جلب من متغيرات البيئة (Secrets/Environment Variables)
    value = os.environ.get(key)
    if value and value != "your_testnet_api_key_here" and value != "your_testnet_api_secret_here":
        return value
    
    # إذا لم توجد أو كانت قيمة افتراضية، جرب من ملف .env
    load_dotenv(override=False)  # لا تعيد كتابة متغيرات البيئة الموجودة
    env_value = os.getenv(key, default)
    
    # تأكد من أن القيمة ليست افتراضية
    if env_value and env_value != "your_testnet_api_key_here" and env_value != "your_testnet_api_secret_here":
        return env_value
    
    return default

# -------------------- الإعدادات --------------------
SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
TIMEFRAME = get_secret("BOT_TIMEFRAME", "15m")
RSI_PERIOD = int(get_secret("BOT_RSI_PERIOD", "14"))
RSI_OS = float(get_secret("RSI_OS", "30"))
RSI_OB = float(get_secret("RSI_OB", "70"))
ACCOUNT_PER_PAIR = float(get_secret("ACCOUNT_PER_PAIR", "200"))
RISK_PER_TRADE_USD = float(get_secret("RISK_PER_TRADE_USD", "4"))
TAKE_PROFIT_R = float(get_secret("TAKE_PROFIT_R", "1.5"))
BOT_LIVE = get_secret("BOT_LIVE", "false").lower() == "true"

# مفاتيح API من Secrets
API_KEY = get_secret("BINANCE_API_KEY", "")
API_SECRET = get_secret("BINANCE_API_SECRET", "")

POLL_SECONDS = int(get_secret("BOT_POLL_SECONDS", "30"))
MIN_NOTIONAL_USD = float(get_secret("BOT_MIN_NOTIONAL_USD", "10"))
SLIPPAGE_BPS = float(get_secret("BOT_SLIPPAGE_BPS", "10"))

# -------------------- الدوال --------------------
def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(gain).rolling(window=period, min_periods=period).mean()
    roll_down = pd.Series(loss).rolling(window=period, min_periods=period).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    rsi.index = series.index
    return rsi

def pct_to_price(price: float, bps: float) -> float:
    return price * (1.0 + bps / 10000.0)

def round_amount(exchange, symbol, amount):
    try:
        market = exchange.market(symbol)
        precision = market.get('precision', {})
        amount_prec = precision.get('amount', None)
        if amount_prec is None:
            return amount
        step = 10 ** (-amount_prec)
        return math.floor(amount / step) * step
    except:
        return amount

def round_price(exchange, symbol, price):
    try:
        market = exchange.market(symbol)
        precision = market.get('precision', {})
        price_prec = precision.get('price', None)
        if price_prec is None:
            return price
        step = 10 ** (-price_prec)
        return math.floor(price / step) * step
    except:
        return price

def make_exchange():
    exchange = ccxt.binance({
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"}
    })
    try:
        exchange.set_sandbox_mode(True)
    except Exception as e:
        print(f"[{utc_now_iso()}] Warning: set_sandbox_mode not available: {e}")
    return exchange

def fetch_ohlcv_df(exchange, symbol, timeframe, limit=200):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.set_index("ts", inplace=True)
    return df

def compute_signals(df):
    df = df.copy()
    df["rsi"] = rsi(df["close"], RSI_PERIOD)
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["buy_sig"] = (df["rsi"] < RSI_OS) & (df["ema20"] > df["ema50"])
    df["sell_sig"] = (df["rsi"] > RSI_OB) & (df["ema20"] < df["ema50"])
    return df

def size_position_usdt(entry_price: float, account_size: float = ACCOUNT_PER_PAIR) -> (float, float):
    stop_pct = 0.02  # 2% stop loss
    qty = RISK_PER_TRADE_USD / (entry_price * stop_pct)
    max_qty = account_size / entry_price
    qty = min(qty, max_qty)
    notional = qty * entry_price
    return qty, notional

def place_orders(exchange, symbol, side, entry_price, stop_price, take_profit_price, amount):
    results = {"entry": None, "stop": None, "tp": None}
    if BOT_LIVE:
        entry_price = round_price(exchange, symbol, entry_price)
        amount = round_amount(exchange, symbol, amount)
        if amount * entry_price < MIN_NOTIONAL_USD:
            print(f"[{utc_now_iso()}] Skipping {symbol}: below min notional ({amount*entry_price:.2f} < {MIN_NOTIONAL_USD})")
            return results
        try:
            results["entry"] = exchange.create_order(symbol, "limit", side, amount, entry_price)
            opp_side = "sell" if side == "buy" else "buy"
            results["tp"] = exchange.create_order(symbol, "limit", opp_side, amount, round_price(exchange, symbol, take_profit_price))
            results["stop"] = {"stop_price": stop_price}
            print(f"[{utc_now_iso()}] LIVE ORDER: {side.upper()} {amount:.6f} {symbol} @ {entry_price:.4f}")
        except Exception as e:
            print(f"[{utc_now_iso()}] Order placement failed for {symbol}: {e}")
    else:
        print(f"[DRY-RUN] Would place {side.upper()} LIMIT {amount:.6f} {symbol} @ {entry_price:.4f}")
        print(f"[DRY-RUN] Would set STOP @ {stop_price:.4f} and TP @ {take_profit_price:.4f}")
    return results

def process_symbol(exchange, symbol, positions):
    """معالجة زوج واحد"""
    try:
        df = fetch_ohlcv_df(exchange, symbol, TIMEFRAME, limit=max(200, RSI_PERIOD + 50))
        df = compute_signals(df).dropna()
        
        if df.empty:
            print(f"[{utc_now_iso()}] No data for {symbol}")
            return
            
        last = df.iloc[-1]
        price = float(last["close"])
        rsi_v = float(last["rsi"])
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])
        
        print(f"[{utc_now_iso()}] {symbol}: Price={price:.4f}, RSI={rsi_v:.2f}, EMA20={ema20:.4f}, EMA50={ema50:.4f}")
        
        if not positions[symbol]:
            if last["buy_sig"]:
                qty, notional = size_position_usdt(price)
                entry_price = pct_to_price(price, -SLIPPAGE_BPS)
                stop_price = price * 0.98  # 2% stop loss
                tp_price = price + TAKE_PROFIT_R * (price - stop_price)
                
                print(f"[{utc_now_iso()}] BUY SIGNAL: {symbol} @ {price:.4f} (RSI: {rsi_v:.2f}, EMA Bull)")
                place_orders(exchange, symbol, "buy", entry_price, stop_price, tp_price, qty)
                positions[symbol] = True
                
            elif last["sell_sig"]:
                print(f"[{utc_now_iso()}] SELL SIGNAL: {symbol} @ {price:.4f} (RSI: {rsi_v:.2f}, EMA Bear) - Spot mode, no short")
        else:
            # شروط الإغلاق
            if rsi_v > 50 or last["sell_sig"]:
                print(f"[{utc_now_iso()}] EXIT CONDITION: {symbol} @ {price:.4f} (RSI: {rsi_v:.2f})")
                positions[symbol] = False
                
    except Exception as e:
        print(f"[{utc_now_iso()}] ERROR processing {symbol}: {e}")

def main():
    print(f"=== Multi-Pair RSI+EMA Bot | LIVE_TRADING={BOT_LIVE} | {utc_now_iso()} ===")
    print(f"Symbols: {SYMBOLS}")
    print(f"Account per pair: ${ACCOUNT_PER_PAIR}, Risk per trade: ${RISK_PER_TRADE_USD}")
    
    exchange = make_exchange()
    try:
        markets = exchange.load_markets()
        for symbol in SYMBOLS:
            if symbol not in markets:
                print(f"Warning: {symbol} not found in markets")
    except Exception as e:
        print(f"Warning: Could not load markets: {e}")
    
    positions = {symbol: False for symbol in SYMBOLS}
    
    iter_count = 0
    
    while True:
        try:
            print(f"\n--- Iteration {iter_count + 1} | {utc_now_iso()} ---")
            
            # معالجة كل زوج
            for symbol in SYMBOLS:
                process_symbol(exchange, symbol, positions)
                time.sleep(1)  # تأخير قصير بين الأزواج
            
            # طباعة الأرصدة كل 20 iteration
            if iter_count % 20 == 0:
                try:
                    bal = exchange.fetch_balance()
                    usdt_free = bal.get('USDT', {}).get('free', 0.0)
                    print(f"[{utc_now_iso()}] Free USDT (testnet): {usdt_free}")
                except Exception as e:
                    print(f"[{utc_now_iso()}] fetch_balance() failed: {e}")
            
            iter_count += 1
            print(f"Active positions: {[s for s, active in positions.items() if active]}")
            time.sleep(POLL_SECONDS)
            
        except KeyboardInterrupt:
            print("Interrupted by user.")
            break
        except Exception as e:
            print(f"[{utc_now_iso()}] MAIN LOOP ERROR: {e}")
            time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
