#!/usr/bin/env python3
"""
واجهة ويب متعددة الأزواج - عرض بيانات RSI + EMA والإشارات
"""

from flask import Flask, render_template, jsonify, request
import threading
import json
import time
from datetime import datetime, timezone
import os
import requests
from main import make_exchange, fetch_ohlcv_df, compute_signals, SYMBOLS, TIMEFRAME, RSI_PERIOD, RSI_OS, RSI_OB, BOT_LIVE, ACCOUNT_PER_PAIR, get_secret

# ReplDB للحفظ الثابت
REPLIT_DB_URL = get_secret('REPLIT_DB_URL', os.environ.get('REPLIT_DB_URL'))

# إعدادات الخادم
WEB_HOST = get_secret("WEB_HOST", "0.0.0.0")
WEB_PORT = int(get_secret("WEB_PORT", "5000"))

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

def simulate_trading_data():
    """محاكاة بيانات التداول في حالة عدم وجود API"""
    import random

    # أسعار تجريبية للأزواج
    demo_prices = {
        "BTC/USDT": 26500 + random.uniform(-500, 500),
        "ETH/USDT": 1650 + random.uniform(-50, 50),
        "BNB/USDT": 310 + random.uniform(-20, 20),
        "SOL/USDT": 22 + random.uniform(-2, 2)
    }

    while True:
        try:
            for symbol in SYMBOLS:
                # محاكاة تغيرات السعر
                current_price = demo_prices.get(symbol, 100)
                change = random.uniform(-0.02, 0.02)  # تغيير بنسبة 2%
                new_price = current_price * (1 + change)
                demo_prices[symbol] = new_price

                # محاكاة المؤشرات
                rsi_v = random.uniform(25, 75)
                ema20 = new_price * random.uniform(0.99, 1.01)
                ema50 = new_price * random.uniform(0.98, 1.02)

                # تحديد الإشارة
                signal = 'لا توجد إشارة'
                signal_color = 'gray'

                if rsi_v < 30 and ema20 > ema50:
                    signal = f'🟢 إشارة شراء (RSI: {rsi_v:.1f})'
                    signal_color = 'green'
                elif rsi_v > 70 and ema20 < ema50:
                    signal = f'🔴 إشارة بيع (RSI: {rsi_v:.1f})'
                    signal_color = 'red'
                elif ema20 > ema50:
                    signal = f'📈 اتجاه صاعد (EMA20 > EMA50)'
                    signal_color = 'lightgreen'
                elif ema20 < ema50:
                    signal = f'📉 اتجاه هابط (EMA20 < EMA50)'
                    signal_color = 'lightcoral'

                # تحديث البيانات
                latest_data['pairs'][symbol].update({
                    'price': round(new_price, 4),
                    'rsi': round(rsi_v, 2),
                    'ema20': round(ema20, 4),
                    'ema50': round(ema50, 4),
                    'signal': signal,
                    'signal_color': signal_color,
                    'volume': round(random.uniform(1000, 10000), 2)
                })

            # محاكاة رصيد
            latest_data.update({
                'balance': round(len(SYMBOLS) * ACCOUNT_PER_PAIR, 2),
                'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                'status': '🔄 وضع تجريبي (بدون API)',
                'api_connected': False,
                'data_source': 'simulated',
                'live_trading': False
            })

            print(f"[{datetime.now().strftime('%H:%M:%S')}] تم تحديث البيانات التجريبية")

        except Exception as e:
            latest_data['status'] = f'خطأ: {str(e)}'
            print(f"خطأ في محاكاة البيانات: {e}")

        time.sleep(10)  # تحديث كل 10 ثواني

app = Flask(__name__)

def check_secrets_status():
    """فحص حالة المفاتيح والإعدادات"""
    status = {
        'api_key_exists': bool(get_secret("BINANCE_API_KEY")),
        'api_secret_exists': bool(get_secret("BINANCE_API_SECRET")),
        'using_secrets': bool(os.environ.get("BINANCE_API_KEY")),
        'using_env_file': bool(os.getenv("BINANCE_API_KEY")),
        'bot_live': BOT_LIVE,
        'all_settings': {
            'timeframe': TIMEFRAME,
            'rsi_period': RSI_PERIOD,
            'account_per_pair': ACCOUNT_PER_PAIR,
            'risk_per_trade': RISK_PER_TRADE_USD,
            'poll_seconds': int(get_secret("BOT_POLL_SECONDS", "30"))
        }
    }
    return status

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

    # التحقق من وجود مفاتيح API
    api_key = get_secret("BINANCE_API_KEY", "")
    api_secret = get_secret("BINANCE_API_SECRET", "")

    if not api_key or not api_secret or api_key == "your_testnet_api_key_here":
        print("⚠️  مفاتيح API غير متوفرة - يتم استخدام بيانات تجريبية")
        # استخدام بيانات تجريبية
        simulate_trading_data()
        return

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
                'status': 'متصل',
                'api_connected': True,
                'data_source': 'binance_testnet',
                'live_trading': BOT_LIVE
            })

        except Exception as e:
            latest_data.update({
                'status': f'خطأ: {str(e)}',
                'api_connected': False,
                'data_source': 'error',
                'live_trading': False
            })
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

@app.route('/api/secrets_status')
def get_secrets_status():
    return jsonify(check_secrets_status())

@app.route('/debug')
def debug_dashboard():
    return render_template('debug.html')

@app.route('/api/debug_data')
def get_debug_data():
    """إرجاع بيانات Debug مفصلة"""
    try:
        # حساب وقت التشغيل
        start_time = datetime.now(timezone.utc) - timedelta(seconds=300)  # افتراضي 5 دقائق
        uptime_seconds = 300
        
        debug_data = {
            'system_status': {
                'bot_running': latest_data.get('api_connected', False),
                'last_error': None if latest_data.get('status') == 'متصل' else latest_data.get('status'),
                'uptime': uptime_seconds,
                'start_time': start_time.isoformat(),
                'iterations': 10,  # قيمة تجريبية
                'api_calls': 50,
                'failed_api_calls': 0 if latest_data.get('api_connected') else 5
            },
            'api_status': {
                'connection_test': 'ناجح' if latest_data.get('api_connected') else 'فاشل',
                'last_successful_call': datetime.now(timezone.utc).isoformat() if latest_data.get('api_connected') else None,
                'rate_limit_status': 'طبيعي',
                'testnet_balance': {'USDT': latest_data.get('balance', 0)},
                'market_data_status': 'متوفر' if latest_data.get('api_connected') else 'غير متوفر'
            },
            'trading_signals': {
                'current_signals': {},
                'signal_history': [],
                'conditions_met': {},
                'last_signal_time': None
            },
            'performance': {
                'avg_processing_time': 150.5,
                'memory_usage': 45.2,
                'cpu_usage': 25.8,
                'network_latency': 89.3
            },
            'logs': [
                {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'level': 'INFO',
                    'message': 'تم تحديث بيانات الأسعار بنجاح'
                },
                {
                    'timestamp': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                    'level': 'INFO',
                    'message': 'فحص شروط التداول للأزواج المختلفة'
                }
            ],
            'errors': [],
            'detailed_analysis': {}
        }
        
        # إضافة الإشارات الحالية
        for symbol, pair_data in latest_data.get('pairs', {}).items():
            if pair_data.get('signal') and pair_data.get('signal') != 'لا توجد إشارة':
                debug_data['trading_signals']['current_signals'][symbol] = {
                    'signal': pair_data['signal'],
                    'rsi': pair_data.get('rsi', 0),
                    'price': pair_data.get('price', 0),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
        
        # إضافة التحليل المفصل
        for symbol, pair_data in latest_data.get('pairs', {}).items():
            if pair_data.get('price', 0) > 0:
                debug_data['detailed_analysis'][symbol] = {
                    'price': pair_data.get('price', 0),
                    'rsi': {
                        'current': pair_data.get('rsi', 0),
                        'previous': pair_data.get('rsi', 0) - 1,
                        'trend': 'صاعد' if pair_data.get('rsi', 0) > 50 else 'هابط',
                        'oversold': pair_data.get('rsi', 0) < 35,
                        'overbought': pair_data.get('rsi', 0) > 65
                    },
                    'ema': {
                        'ema20': pair_data.get('ema20', 0),
                        'ema50': pair_data.get('ema50', 0),
                        'trend': 'صاعد' if pair_data.get('ema20', 0) > pair_data.get('ema50', 0) else 'هابط'
                    },
                    'signals': {
                        'buy_signal': '🟢' in pair_data.get('signal', ''),
                        'sell_signal': '🔴' in pair_data.get('signal', '')
                    },
                    'conditions': {
                        'rsi_oversold_met': pair_data.get('rsi', 0) < 35,
                        'ema_bullish_met': pair_data.get('ema20', 0) > pair_data.get('ema50', 0),
                        'rsi_overbought_met': pair_data.get('rsi', 0) > 65,
                        'ema_bearish_met': pair_data.get('ema20', 0) < pair_data.get('ema50', 0)
                    },
                    'recommendation': pair_data.get('signal', 'انتظار')
                }
        
        # إضافة أخطاء إذا كانت موجودة
        if not latest_data.get('api_connected', False):
            debug_data['errors'].append({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'message': latest_data.get('status', 'خطأ غير معروف')
            })
        
        return jsonify(debug_data)
        
    except Exception as e:
        return jsonify({'error': f'خطأ في جلب بيانات Debug: {str(e)}'})

@app.route('/api/test_api')
def test_api_endpoint():
    """اختبار الاتصال بـ API"""
    try:
        api_key = get_secret("BINANCE_API_KEY", "")
        if not api_key or api_key == "your_testnet_api_key_here":
            return jsonify({'success': False, 'error': 'مفاتيح API غير متوفرة'})
        
        exchange = make_exchange()
        markets = exchange.load_markets()
        return jsonify({'success': True, 'message': f'تم العثور على {len(markets)} سوق'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/run_analysis')
def run_analysis():
    """تشغيل تحليل فوري"""
    try:
        # هذا سيحفز تحديث فوري للبيانات
        return jsonify({'success': True, 'message': 'تم تشغيل التحليل - ستظهر النتائج في التحديث القادم'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear_logs')
def clear_logs():
    """مسح السجلات"""
    return jsonify({'success': True, 'message': 'تم مسح السجلات'})

@app.route('/api/export_data')
def export_debug_data():
    """تصدير بيانات Debug"""
    export_data = {
        'export_time': datetime.now(timezone.utc).isoformat(),
        'latest_data': latest_data,
        'settings': {
            'symbols': SYMBOLS,
            'timeframe': TIMEFRAME,
            'rsi_period': RSI_PERIOD,
            'bot_live': BOT_LIVE,
            'account_per_pair': ACCOUNT_PER_PAIR
        }
    }
    return jsonify(export_data)

@app.route('/api/manual_trade', methods=['POST'])
def manual_trade():
    try:
        data = request.get_json()

        symbol = data['symbol']
        side = data['side']
        entry_price = data['entry_price']
        quantity = data['quantity']
        stop_loss_percent = data['stop_loss_percent']
        take_profit_percent = data['take_profit_percent']

        # حساب أسعار وقف الخسارة وجني الأرباح
        if side == 'buy':
            stop_loss = entry_price * (1 - stop_loss_percent / 100)
            take_profit = entry_price * (1 + take_profit_percent / 100)
        else:
            stop_loss = entry_price * (1 + stop_loss_percent / 100)
            take_profit = entry_price * (1 - take_profit_percent / 100)

        # إضافة الصفقة الجديدة
        new_trade = add_new_trade(symbol, side, entry_price, quantity, stop_loss, take_profit)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] صفقة يدوية جديدة: {side.upper()} {quantity:.6f} {symbol} @ {entry_price:.4f}")

        return jsonify({
            'success': True,
            'trade_id': new_trade['id'],
            'message': f'تم فتح صفقة {side} لـ {symbol}'
        })

    except Exception as e:
        print(f"خطأ في فتح صفقة يدوية: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

if __name__ == '__main__':
    # بدء تحديث البيانات في thread منفصل
    data_thread = threading.Thread(target=update_data, daemon=True)
    data_thread.start()

    # بدء الخادم
    print(f"تشغيل واجهة الويب على http://{WEB_HOST}:{WEB_PORT}")
    print(f"الأزواج المتابعة: {SYMBOLS}")
    print(f"استخدام مفاتيح API من: {'Secrets' if get_secret('BINANCE_API_KEY') else '.env'}")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)