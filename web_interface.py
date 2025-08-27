
#!/usr/bin/env python3
"""
واجهة ويب متعددة الأزواج - عرض بيانات RSI + EMA والإشارات
"""

from flask import Flask, render_template, jsonify
import threading
import json
import time
from datetime import datetime, timezone
import os
import requests
from main import make_exchange, fetch_ohlcv_df, compute_signals, SYMBOLS, TIMEFRAME, RSI_PERIOD, RSI_OS, RSI_OB, BOT_LIVE, ACCOUNT_PER_PAIR

# ReplDB للحفظ الثابت
REPLIT_DB_URL = os.environ.get('REPLIT_DB_URL')

def save_to_db(key, data):
    """حفظ البيانات في ReplDB"""
    if REPLIT_DB_URL:
        try:
            requests.post(f"{REPLIT_DB_URL}/{key}", data=json.dumps(data))
        except:
            pass

def load_from_db(key, default=None):
    """تحميل البيانات من ReplDB"""
    if REPLIT_DB_URL:
        try:
            response = requests.get(f"{REPLIT_DB_URL}/{key}")
            if response.status_code == 200:
                return json.loads(response.text)
        except:
            pass
    return default

def add_new_trade(symbol, side, entry_price, quantity, stop_loss, take_profit):
    """إضافة صفقة جديدة"""
    global trade_counter
    trade_counter += 1
    
    trade = {
        'id': trade_counter,
        'symbol': symbol,
        'side': side,
        'entry_price': entry_price,
        'quantity': quantity,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'entry_time': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'نشط',
        'current_price': entry_price,
        'pnl': 0,
        'pnl_percentage': 0
    }
    
    latest_data['trades']['active'].append(trade)
    
    # حفظ في قاعدة البيانات
    save_to_db('trades_data', latest_data['trades'])
    save_to_db('trade_counter', trade_counter)
    
    return trade

def update_active_trades():
    """تحديث الصفقات النشطة بأسعار حالية"""
    for trade in latest_data['trades']['active']:
        symbol = trade['symbol']
        if symbol in latest_data['pairs']:
            current_price = latest_data['pairs'][symbol]['price']
            trade['current_price'] = current_price
            
            if trade['side'] == 'buy':
                trade['pnl'] = (current_price - trade['entry_price']) * trade['quantity']
                trade['pnl_percentage'] = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            else:
                trade['pnl'] = (trade['entry_price'] - current_price) * trade['quantity']
                trade['pnl_percentage'] = ((trade['entry_price'] - current_price) / trade['entry_price']) * 100

def close_trade(trade_id, exit_price, reason="يدوي"):
    """إغلاق صفقة"""
    for i, trade in enumerate(latest_data['trades']['active']):
        if trade['id'] == trade_id:
            trade['exit_price'] = exit_price
            trade['exit_time'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            trade['status'] = 'مغلق'
            trade['close_reason'] = reason
            
            # حساب الربح/الخسارة النهائي
            if trade['side'] == 'buy':
                final_pnl = (exit_price - trade['entry_price']) * trade['quantity']
            else:
                final_pnl = (trade['entry_price'] - exit_price) * trade['quantity']
            
            trade['final_pnl'] = final_pnl
            trade['final_pnl_percentage'] = ((final_pnl / (trade['entry_price'] * trade['quantity'])) * 100)
            
            # نقل إلى الصفقات المكتملة
            latest_data['trades']['completed'].append(trade)
            latest_data['trades']['active'].pop(i)
            
            # تحديث الإحصائيات
            update_trade_stats()
            
            # حفظ في قاعدة البيانات
            save_to_db('trades_data', latest_data['trades'])
            
            break

def update_trade_stats():
    """تحديث إحصائيات التداول"""
    completed = latest_data['trades']['completed']
    stats = latest_data['trades']['stats']
    
    if not completed:
        return
    
    stats['total_trades'] = len(completed)
    winning = [t for t in completed if t['final_pnl'] > 0]
    losing = [t for t in completed if t['final_pnl'] < 0]
    
    stats['winning_trades'] = len(winning)
    stats['losing_trades'] = len(losing)
    stats['win_rate'] = (len(winning) / len(completed)) * 100 if completed else 0
    
    stats['total_profit'] = sum(t['final_pnl'] for t in completed)
    stats['avg_profit'] = sum(t['final_pnl'] for t in winning) / len(winning) if winning else 0
    stats['avg_loss'] = sum(t['final_pnl'] for t in losing) / len(losing) if losing else 0
    stats['max_profit'] = max(t['final_pnl'] for t in completed) if completed else 0
    stats['max_loss'] = min(t['final_pnl'] for t in completed) if completed else 0
    stats['total_volume'] = sum(t['entry_price'] * t['quantity'] for t in completed)

app = Flask(__name__)

# تحميل البيانات المحفوظة
saved_trades = load_from_db('trades_data', {
    'active': [],
    'completed': [],
    'stats': {
        'total_trades': 0,
        'winning_trades': 0,
        'losing_trades': 0,
        'total_profit': 0,
        'win_rate': 0,
        'avg_profit': 0,
        'avg_loss': 0,
        'max_profit': 0,
        'max_loss': 0,
        'total_volume': 0
    }
})

# متغيرات عامة لحفظ البيانات
latest_data = {
    'pairs': {},  # {symbol: {price, rsi, ema20, ema50, signal, etc}}
    'balance': 0,
    'timestamp': '',
    'status': 'متصل',
    'trades': saved_trades
}

# إنشاء بيانات أولية للأزواج
for symbol in SYMBOLS:
    latest_data['pairs'][symbol] = {
        'price': 0,
        'rsi': 0,
        'ema20': 0,
        'ema50': 0,
        'signal': 'لا توجد إشارة',
        'signal_color': 'gray',
        'volume': 0
    }

# متغير لتتبع الصفقات
trade_counter = load_from_db('trade_counter', 0)

print(f"تم تحميل {len(latest_data['trades']['completed'])} صفقة مكتملة و {len(latest_data['trades']['active'])} صفقة نشطة")
print(f"الأزواج المتابعة: {SYMBOLS}")

def update_data():
    """تحديث البيانات في الخلفية"""
    global latest_data
    exchange = make_exchange()
    
    while True:
        try:
            for symbol in SYMBOLS:
                try:
                    # جلب البيانات
                    df = fetch_ohlcv_df(exchange, symbol, TIMEFRAME, limit=max(200, RSI_PERIOD + 50))
                    df = compute_signals(df).dropna()
                    
                    if df.empty:
                        continue
                        
                    last = df.iloc[-1]
                    
                    price = float(last["close"])
                    rsi_v = float(last["rsi"])
                    ema20 = float(last["ema20"])
                    ema50 = float(last["ema50"])
                    volume = float(last["volume"])
                    
                    # تحديد الإشارة
                    signal = 'لا توجد إشارة'
                    signal_color = 'gray'
                    
                    if last["buy_sig"]:
                        signal = f'🟢 إشارة شراء (RSI: {rsi_v:.1f})'
                        signal_color = 'green'
                        # إضافة صفقة جديدة (محاكاة)
                        if BOT_LIVE:
                            quantity = ACCOUNT_PER_PAIR / price
                            stop_loss = price * 0.98
                            take_profit = price * 1.03
                            add_new_trade(symbol, 'buy', price, quantity, stop_loss, take_profit)
                    elif last["sell_sig"]:
                        signal = f'🔴 إشارة بيع (RSI: {rsi_v:.1f})'
                        signal_color = 'red'
                    elif ema20 > ema50:
                        signal = f'📈 اتجاه صاعد (EMA20 > EMA50)'
                        signal_color = 'lightgreen'
                    elif ema20 < ema50:
                        signal = f'📉 اتجاه هابط (EMA20 < EMA50)'
                        signal_color = 'lightcoral'
                    
                    # تحديث بيانات الزوج
                    latest_data['pairs'][symbol].update({
                        'price': round(price, 4),
                        'rsi': round(rsi_v, 2),
                        'ema20': round(ema20, 4),
                        'ema50': round(ema50, 4),
                        'signal': signal,
                        'signal_color': signal_color,
                        'volume': round(volume, 2)
                    })
                    
                except Exception as e:
                    print(f"خطأ في معالجة {symbol}: {e}")
                    latest_data['pairs'][symbol]['signal'] = f'خطأ: {str(e)[:30]}'
                    latest_data['pairs'][symbol]['signal_color'] = 'red'
            
            # تحديث الصفقات النشطة
            update_active_trades()
            
            # محاولة جلب الرصيد
            try:
                bal = exchange.fetch_balance()
                balance = bal.get('USDT', {}).get('free', 0.0)
            except:
                balance = len(SYMBOLS) * ACCOUNT_PER_PAIR  # رصيد افتراضي
            
            # تحديث البيانات العامة
            latest_data.update({
                'balance': round(balance, 2),
                'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                'status': 'متصل'
            })
                
        except Exception as e:
            latest_data['status'] = f'خطأ: {str(e)}'
            print(f"خطأ في تحديث البيانات: {e}")
        
        time.sleep(30)  # تحديث كل 30 ثانية

@app.route('/')
def index():
    return render_template('index.html', symbols=SYMBOLS)

@app.route('/api/data')
def get_data():
    return jsonify(latest_data)

@app.route('/api/trades')
def get_trades():
    return jsonify(latest_data['trades'])

@app.route('/api/close_trade/<int:trade_id>')
def close_trade_api(trade_id):
    # العثور على الصفقة وإغلاقها بالسعر الحالي
    for trade in latest_data['trades']['active']:
        if trade['id'] == trade_id:
            current_price = latest_data['pairs'][trade['symbol']]['price']
            close_trade(trade_id, current_price, "إغلاق يدوي")
            break
    return jsonify({'success': True})

if __name__ == '__main__':
    # بدء تحديث البيانات في thread منفصل
    data_thread = threading.Thread(target=update_data, daemon=True)
    data_thread.start()
    
    # بدء الخادم
    print(f"تشغيل واجهة الويب على http://0.0.0.0:5000")
    print(f"الأزواج المتابعة: {SYMBOLS}")
    app.run(host='0.0.0.0', port=5000, debug=False)
