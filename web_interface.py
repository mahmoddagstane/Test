
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
from main import make_exchange, fetch_ohlcv_df, compute_signals, SYMBOL, TIMEFRAME, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT

app = Flask(__name__)

# متغيرات عامة لحفظ البيانات
latest_data = {
    'price': 0,
    'rsi': 0,
    'signal': 'لا توجد إشارة',
    'balance': 0,
    'timestamp': '',
    'status': 'متصل',
    'history': []
}

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
            
            # تحديد الإشارة
            signal = 'لا توجد إشارة'
            signal_color = 'gray'
            if last["buy_sig"]:
                signal = 'إشارة شراء'
                signal_color = 'green'
            elif last["sell_sig"]:
                signal = 'إشارة بيع'
                signal_color = 'red'
            
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

if __name__ == '__main__':
    # بدء تحديث البيانات في thread منفصل
    data_thread = threading.Thread(target=update_data, daemon=True)
    data_thread.start()
    
    # بدء الخادم
    app.run(host='0.0.0.0', port=5000, debug=False)
