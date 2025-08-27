
#!/usr/bin/env python3
"""
واجهة ويب لبوت التداول - عرض بيانات RSI والإشارات
"""

from flask import Flask, render_template, jsonify
import threading
import json
import time
from datetime import datetime, timezone
import os
from main import make_exchange, fetch_ohlcv_df, compute_signals, SYMBOL, TIMEFRAME, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT, LIVE_TRADING

def add_new_trade(side, entry_price, quantity, stop_loss, take_profit):
    """إضافة صفقة جديدة"""
    global trade_counter, current_position
    trade_counter += 1
    
    trade = {
        'id': trade_counter,
        'symbol': SYMBOL,
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
    current_position = trade
    return trade

def update_active_trades(current_price):
    """تحديث الصفقات النشطة"""
    global current_position
    
    for trade in latest_data['trades']['active']:
        trade['current_price'] = current_price
        
        if trade['side'] == 'buy':
            trade['pnl'] = (current_price - trade['entry_price']) * trade['quantity']
            trade['pnl_percentage'] = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
        else:
            trade['pnl'] = (trade['entry_price'] - current_price) * trade['quantity']
            trade['pnl_percentage'] = ((trade['entry_price'] - current_price) / trade['entry_price']) * 100

def close_trade(trade_id, exit_price, reason="يدوي"):
    """إغلاق صفقة"""
    global current_position
    
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
            current_position = None
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

# متغيرات عامة لحفظ البيانات
latest_data = {
    'price': 0,
    'rsi': 0,
    'signal': 'لا توجد إشارة',
    'balance': 0,
    'timestamp': '',
    'status': 'متصل',
    'history': [],
    'trades': {
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
    }
}

# متغير لتتبع الصفقات
current_position = None
trade_counter = 0

def update_data():
    """تحديث البيانات في الخلفية"""
    global latest_data
    exchange = make_exchange()
    
    while True:
        try:
            # جلب البيانات
            df = fetch_ohlcv_df(exchange, SYMBOL, TIMEFRAME, limit=max(200, RSI_PERIOD + 10))
            df = compute_signals(df).dropna()
            last = df.iloc[-1]
            
            price = float(last["close"])
            rsi_v = float(last["rsi"])
            
            # تحديث الصفقات النشطة
            update_active_trades(price)
            
            # تحديد الإشارة وإدارة الصفقات
            signal = 'لا توجد إشارة'
            signal_color = 'gray'
            
            if last["buy_sig"] and not current_position:
                signal = 'إشارة شراء'
                signal_color = 'green'
                # إضافة صفقة جديدة (محاكاة)
                quantity = 100 / price  # $100 worth
                stop_loss = price * 0.99
                take_profit = price * 1.015
                if LIVE_TRADING:
                    add_new_trade('buy', price, quantity, stop_loss, take_profit)
            elif last["sell_sig"] and current_position and current_position['side'] == 'buy':
                signal = 'إشارة بيع'
                signal_color = 'red'
                if LIVE_TRADING and current_position:
                    close_trade(current_position['id'], price, "إشارة RSI")
            elif current_position:
                # فحص شروط الإغلاق
                if current_position['side'] == 'buy':
                    if price <= current_position['stop_loss']:
                        close_trade(current_position['id'], price, "Stop Loss")
                    elif price >= current_position['take_profit']:
                        close_trade(current_position['id'], price, "Take Profit")
                    else:
                        signal = f'صفقة نشطة - ربح/خسارة: {current_position["pnl"]:.2f}$'
                        signal_color = 'green' if current_position['pnl'] > 0 else 'red'
            
            # محاولة جلب الرصيد
            balance = 0
            try:
                bal = exchange.fetch_balance()
                balance = bal.get('USDT', {}).get('free', 0.0)
            except:
                balance = 10000  # رصيد افتراضي
            
            # تحديث البيانات
            latest_data.update({
                'price': round(price, 2),
                'rsi': round(rsi_v, 2),
                'signal': signal,
                'signal_color': signal_color,
                'balance': round(balance, 2),
                'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                'status': 'متصل'
            })
            
            # إضافة للتاريخ (آخر 50 نقطة)
            latest_data['history'].append({
                'time': latest_data['timestamp'],
                'rsi': latest_data['rsi'],
                'price': latest_data['price']
            })
            if len(latest_data['history']) > 50:
                latest_data['history'].pop(0)
                
        except Exception as e:
            latest_data['status'] = f'خطأ: {str(e)}'
            print(f"خطأ في تحديث البيانات: {e}")
        
        time.sleep(30)  # تحديث كل 30 ثانية

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    return jsonify(latest_data)

@app.route('/api/trades')
def get_trades():
    return jsonify(latest_data['trades'])

@app.route('/api/close_trade/<int:trade_id>')
def close_trade_api(trade_id):
    current_price = latest_data['price']
    close_trade(trade_id, current_price, "إغلاق يدوي")
    return jsonify({'success': True})

if __name__ == '__main__':
    # بدء تحديث البيانات في thread منفصل
    data_thread = threading.Thread(target=update_data, daemon=True)
    data_thread.start()
    
    # بدء الخادم
    app.run(host='0.0.0.0', port=5000, debug=False)
