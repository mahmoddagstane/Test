
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
    
    # شروط أكثر مرونة للإشارات
    df["buy_sig"] = (
        (df["rsi"] < 35) &  # RSI أقل من 35 بدلاً من 30
        (df["ema20"] > df["ema50"]) |  # EMA صاعد أو
        ((df["rsi"] < 25) & (df["rsi"].shift(1) > df["rsi"]))  # RSI منخفض جداً ومتراجع
    )
    
    df["sell_sig"] = (
        (df["rsi"] > 65) &  # RSI أكبر من 65 بدلاً من 70
        (df["ema20"] < df["ema50"]) |  # EMA هابط أو
        ((df["rsi"] > 75) & (df["rsi"].shift(1) < df["rsi"]))  # RSI عالي جداً ومرتفع
    )
    
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
            # تنفيذ أمر السوق بدلاً من أمر محدد للدخول السريع
            results["entry"] = exchange.create_market_order(symbol, side, amount)
            actual_price = float(results["entry"]["average"]) if results["entry"]["average"] else entry_price
            
            # وضع أمر جني الأرباح
            opp_side = "sell" if side == "buy" else "buy"
            results["tp"] = exchange.create_order(symbol, "limit", opp_side, amount, round_price(exchange, symbol, take_profit_price))
            
            # حفظ معلومات وقف الخسارة للمراقبة
            results["stop"] = {"stop_price": stop_price, "amount": amount, "side": opp_side}
            
            print(f"[{utc_now_iso()}] ✅ EXECUTED: {side.upper()} {amount:.6f} {symbol} @ {actual_price:.4f}")
            print(f"[{utc_now_iso()}] 📊 TP: {take_profit_price:.4f} | SL: {stop_price:.4f}")
            
        except Exception as e:
            print(f"[{utc_now_iso()}] ❌ Order execution failed for {symbol}: {e}")
    else:
        print(f"[DRY-RUN] Would place {side.upper()} MARKET {amount:.6f} {symbol} @ {entry_price:.4f}")
        print(f"[DRY-RUN] Would set STOP @ {stop_price:.4f} and TP @ {take_profit_price:.4f}")
    return results

def process_symbol(exchange, symbol, positions, open_orders):
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
        
        # عرض تفاصيل مراقبة أكثر وضوحاً
        trend = "صاعد 📈" if ema20 > ema50 else "هابط 📉"
        rsi_status = ""
        if rsi_v < 30:
            rsi_status = "تشبع بيعي 🟢"
        elif rsi_v > 70:
            rsi_status = "تشبع شرائي 🔴"
        elif rsi_v < 45:
            rsi_status = "قريب من التشبع البيعي 🟡"
        elif rsi_v > 55:
            rsi_status = "قريب من التشبع الشرائي 🟡"
        else:
            rsi_status = "متوسط ⚪"
        
        print(f"[{utc_now_iso()}] {symbol}:")
        print(f"   💰 السعر: {price:.4f} | 📊 RSI: {rsi_v:.2f} ({rsi_status})")
        print(f"   📈 EMA20: {ema20:.4f} | 📉 EMA50: {ema50:.4f} | الاتجاه: {trend}")
        
        # فحص أوامر وقف الخسارة للصفقات المفتوحة
        if symbol in open_orders and open_orders[symbol]:
            stop_info = open_orders[symbol].get("stop")
            if stop_info and price <= stop_info["stop_price"]:
                try:
                    # تنفيذ وقف الخسارة
                    if BOT_LIVE:
                        exchange.create_market_order(symbol, stop_info["side"], stop_info["amount"])
                        print(f"[{utc_now_iso()}] 🛑 STOP LOSS EXECUTED: {symbol} @ {price:.4f}")
                    else:
                        print(f"[DRY-RUN] Would execute STOP LOSS for {symbol} @ {price:.4f}")
                    
                    positions[symbol] = False
                    open_orders[symbol] = None
                except Exception as e:
                    print(f"[{utc_now_iso()}] Stop loss execution failed: {e}")
        
        if not positions[symbol]:
            if last["buy_sig"]:
                qty, notional = size_position_usdt(price)
                entry_price = price  # استخدام سعر السوق مباشرة
                stop_price = price * 0.98  # 2% stop loss
                tp_price = price + TAKE_PROFIT_R * (price - stop_price)
                
                print(f"[{utc_now_iso()}] 🟢 إشارة شراء قوية لـ {symbol}:")
                print(f"   📍 السعر: {price:.4f} | RSI: {rsi_v:.2f} | EMA20 > EMA50: {ema20 > ema50}")
                print(f"   💵 الكمية: {qty:.6f} | المخاطرة: ${RISK_PER_TRADE_USD}")
                print(f"   🎯 هدف الربح: {tp_price:.4f} | ⛔ وقف الخسارة: {stop_price:.4f}")
                results = place_orders(exchange, symbol, "buy", entry_price, stop_price, tp_price, qty)
                
                if results["entry"]:
                    positions[symbol] = True
                    open_orders[symbol] = results
                    print(f"[{utc_now_iso()}] 📈 Position opened for {symbol}")
                
        else:
            # شروط الإغلاق - مراجعة أكثر مرونة
            close_reason = ""
            should_close = False
            
            if rsi_v > 60:
                close_reason = f"RSI عالي ({rsi_v:.2f})"
                should_close = True
            elif last["sell_sig"]:
                close_reason = "إشارة بيع"
                should_close = True
            elif rsi_v > 55 and ema20 < ema50:
                close_reason = f"RSI متوسط ({rsi_v:.2f}) + اتجاه هابط"
                should_close = True
            
            if should_close:
                try:
                    print(f"[{utc_now_iso()}] 🔴 إشارة إغلاق لـ {symbol}: {close_reason}")
                    
                    if BOT_LIVE and symbol in open_orders and open_orders[symbol]:
                        # إلغاء أمر جني الأرباح المعلق
                        tp_order = open_orders[symbol].get("tp")
                        if tp_order:
                            try:
                                exchange.cancel_order(tp_order["id"], symbol)
                                print(f"[{utc_now_iso()}] ✅ تم إلغاء أمر جني الأرباح")
                            except:
                                pass
                        
                        # تنفيذ بيع بسعر السوق
                        qty = open_orders[symbol]["entry"]["amount"]
                        result = exchange.create_market_order(symbol, "sell", qty)
                        actual_exit = float(result["average"]) if result["average"] else price
                        print(f"[{utc_now_iso()}] 💰 تم إغلاق الصفقة: {symbol} @ {actual_exit:.4f}")
                    else:
                        print(f"[DRY-RUN] سيتم إغلاق الصفقة لـ {symbol} @ {price:.4f} | السبب: {close_reason}")
                    
                    positions[symbol] = False
                    open_orders[symbol] = None
                    
                except Exception as e:
                    print(f"[{utc_now_iso()}] فشل إغلاق الصفقة: {e}")
                
    except Exception as e:
        print(f"[{utc_now_iso()}] ERROR processing {symbol}: {e}")

def main():
    print(f"=== Multi-Pair RSI+EMA Bot | LIVE_TRADING={BOT_LIVE} | {utc_now_iso()} ===")
    print(f"Symbols: {SYMBOLS}")
    print(f"Account per pair: ${ACCOUNT_PER_PAIR}, Risk per trade: ${RISK_PER_TRADE_USD}")
    
    if not BOT_LIVE:
        print("⚠️  BOT في وضع DRY-RUN. لتفعيل التداول الحقيقي، اضبط BOT_LIVE=true في Secrets")
    
    exchange = make_exchange()
    try:
        markets = exchange.load_markets()
        for symbol in SYMBOLS:
            if symbol not in markets:
                print(f"Warning: {symbol} not found in markets")
    except Exception as e:
        print(f"Warning: Could not load markets: {e}")
    
    positions = {symbol: False for symbol in SYMBOLS}
    open_orders = {symbol: None for symbol in SYMBOLS}  # تتبع الأوامر المفتوحة
    
    iter_count = 0
    
    while True:
        try:
            print(f"\n--- Iteration {iter_count + 1} | {utc_now_iso()} ---")
            
            # معالجة كل زوج
            for symbol in SYMBOLS:
                process_symbol(exchange, symbol, positions, open_orders)
                time.sleep(2)  # تأخير أطول بين الأزواج لتجنب Rate Limits
            
            # طباعة الأرصدة والإحصائيات كل 10 iterations
            if iter_count % 10 == 0:
                try:
                    bal = exchange.fetch_balance()
                    usdt_free = bal.get('USDT', {}).get('free', 0.0)
                    btc_balance = bal.get('BTC', {}).get('free', 0.0)
                    eth_balance = bal.get('ETH', {}).get('free', 0.0)
                    print(f"[{utc_now_iso()}] 💰 Balances - USDT: {usdt_free:.2f}, BTC: {btc_balance:.6f}, ETH: {eth_balance:.6f}")
                except Exception as e:
                    print(f"[{utc_now_iso()}] fetch_balance() failed: {e}")
            
            # إحصائيات الصفقات وملخص المراقبة
            active_count = sum(1 for active in positions.values() if active)
            active_symbols = [s for s, active in positions.items() if active]
            
            print(f"\n📊 ملخص المراقبة:")
            print(f"   🔍 الأزواج المراقبة: {len(SYMBOLS)} أزواج")
            print(f"   📈 الصفقات النشطة: {active_count}/4 - {active_symbols}")
            print(f"   ⏰ دورة المراقبة كل {POLL_SECONDS} ثانية")
            print(f"   💼 رصيد كل زوج: ${ACCOUNT_PER_PAIR} | مخاطرة: ${RISK_PER_TRADE_USD}")
            
            # عرض حالة كل زوج
            if iter_count % 5 == 0:  # كل 5 دورات
                print(f"\n🎯 ملخص شروط الدخول:")
                print(f"   📉 شراء: RSI < 35 + (EMA20 > EMA50 أو RSI < 25)")
                print(f"   📈 بيع: RSI > 65 + (EMA20 < EMA50 أو RSI > 75)")
                print(f"   🔄 وضع التداول: {'مباشر' if BOT_LIVE else 'تجريبي'}")
            
            iter_count += 1
            time.sleep(POLL_SECONDS)
            
        except KeyboardInterrupt:
            print("Interrupted by user.")
            break
        except Exception as e:
            print(f"[{utc_now_iso()}] MAIN LOOP ERROR: {e}")
            print(f"[{utc_now_iso()}] Retrying in {POLL_SECONDS} seconds...")
            # إضافة معلومات تشخيصية إضافية
            if "timeout" in str(e).lower():
                print(f"[{utc_now_iso()}] Network timeout detected - checking connection...")
            elif "rate limit" in str(e).lower():
                print(f"[{utc_now_iso()}] Rate limit hit - extending delay...")
                time.sleep(POLL_SECONDS * 2)  # مضاعفة التأخير للـ rate limits
                continue
            time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
