
#!/usr/bin/env python3
"""
لوحة Debug للبوت - مراقبة شاملة ومفصلة
"""

from flask import Flask, render_template, jsonify, request
import threading
import json
import time
import os
import traceback
from datetime import datetime, timezone, timedelta
import requests
from main import (
    make_exchange, fetch_ohlcv_df, compute_signals, SYMBOLS, TIMEFRAME, 
    RSI_PERIOD, BOT_LIVE, ACCOUNT_PER_PAIR, get_secret, process_symbol
)

# إعدادات الخادم
DEBUG_HOST = "0.0.0.0"
DEBUG_PORT = 5001

app = Flask(__name__)

# بيانات Debug
debug_data = {
    'system_status': {
        'bot_running': False,
        'last_error': None,
        'uptime': 0,
        'start_time': None,
        'iterations': 0,
        'api_calls': 0,
        'failed_api_calls': 0
    },
    'api_status': {
        'connection_test': 'غير مختبر',
        'last_successful_call': None,
        'rate_limit_status': 'طبيعي',
        'testnet_balance': {},
        'market_data_status': 'غير معروف'
    },
    'trading_signals': {
        'current_signals': {},
        'signal_history': [],
        'conditions_met': {},
        'last_signal_time': None
    },
    'performance': {
        'avg_processing_time': 0,
        'memory_usage': 0,
        'cpu_usage': 0,
        'network_latency': 0
    },
    'logs': [],
    'errors': [],
    'detailed_analysis': {}
}

class DebugLogger:
    def __init__(self):
        self.max_logs = 100
        self.max_errors = 50
    
    def log(self, level, message, data=None):
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': level,
            'message': message,
            'data': data
        }
        
        debug_data['logs'].insert(0, log_entry)
        if len(debug_data['logs']) > self.max_logs:
            debug_data['logs'] = debug_data['logs'][:self.max_logs]
        
        if level == 'ERROR':
            debug_data['errors'].insert(0, log_entry)
            if len(debug_data['errors']) > self.max_errors:
                debug_data['errors'] = debug_data['errors'][:self.max_errors]
        
        print(f"[DEBUG-{level}] {message}")

debug_logger = DebugLogger()

def test_api_connection():
    """اختبار الاتصال بـ API"""
    try:
        debug_logger.log('INFO', 'اختبار الاتصال بـ Binance API...')
        exchange = make_exchange()
        
        # اختبار جلب معلومات السوق
        start_time = time.time()
        markets = exchange.load_markets()
        api_time = time.time() - start_time
        
        debug_data['performance']['network_latency'] = round(api_time * 1000, 2)
        debug_data['api_status']['connection_test'] = 'ناجح'
        debug_data['api_status']['last_successful_call'] = datetime.now(timezone.utc).isoformat()
        debug_data['system_status']['api_calls'] += 1
        
        # اختبار جلب الرصيد
        try:
            balance = exchange.fetch_balance()
            debug_data['api_status']['testnet_balance'] = {
                'USDT': balance.get('USDT', {}).get('free', 0),
                'BTC': balance.get('BTC', {}).get('free', 0),
                'ETH': balance.get('ETH', {}).get('free', 0)
            }
            debug_logger.log('INFO', f'تم جلب الرصيد بنجاح: {debug_data["api_status"]["testnet_balance"]}')
        except Exception as e:
            debug_logger.log('WARNING', f'فشل في جلب الرصيد: {str(e)}')
        
        # اختبار جلب بيانات الأسعار
        test_symbol = SYMBOLS[0]
        try:
            ohlcv = exchange.fetch_ohlcv(test_symbol, TIMEFRAME, limit=10)
            debug_data['api_status']['market_data_status'] = 'متوفر'
            debug_logger.log('INFO', f'تم جلب بيانات السوق لـ {test_symbol}')
        except Exception as e:
            debug_data['api_status']['market_data_status'] = f'خطأ: {str(e)}'
            debug_logger.log('ERROR', f'فشل في جلب بيانات السوق: {str(e)}')
        
        return True
        
    except Exception as e:
        debug_data['api_status']['connection_test'] = f'فاشل: {str(e)}'
        debug_data['system_status']['failed_api_calls'] += 1
        debug_logger.log('ERROR', f'فشل اختبار API: {str(e)}')
        return False

def analyze_trading_conditions():
    """تحليل مفصل لشروط التداول"""
    try:
        exchange = make_exchange()
        
        for symbol in SYMBOLS:
            debug_logger.log('INFO', f'تحليل شروط التداول لـ {symbol}...')
            
            try:
                # جلب البيانات
                df = fetch_ohlcv_df(exchange, symbol, TIMEFRAME, limit=max(200, RSI_PERIOD + 50))
                df = compute_signals(df).dropna()
                
                if df.empty:
                    debug_logger.log('WARNING', f'لا توجد بيانات لـ {symbol}')
                    continue
                
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else last
                
                # حساب المؤشرات
                current_price = float(last["close"])
                rsi_current = float(last["rsi"])
                rsi_prev = float(prev["rsi"])
                ema20 = float(last["ema20"])
                ema50 = float(last["ema50"])
                
                # تحليل الشروط
                analysis = {
                    'price': current_price,
                    'rsi': {
                        'current': rsi_current,
                        'previous': rsi_prev,
                        'trend': 'صاعد' if rsi_current > rsi_prev else 'هابط',
                        'oversold': rsi_current < 35,
                        'overbought': rsi_current > 65,
                        'extreme_oversold': rsi_current < 25,
                        'extreme_overbought': rsi_current > 75
                    },
                    'ema': {
                        'ema20': ema20,
                        'ema50': ema50,
                        'trend': 'صاعد' if ema20 > ema50 else 'هابط',
                        'distance': abs(ema20 - ema50) / current_price * 100
                    },
                    'signals': {
                        'buy_signal': bool(last["buy_sig"]),
                        'sell_signal': bool(last["sell_sig"])
                    },
                    'conditions': {
                        'rsi_oversold_met': rsi_current < 35,
                        'ema_bullish_met': ema20 > ema50,
                        'extreme_rsi_met': rsi_current < 25 and rsi_prev > rsi_current,
                        'rsi_overbought_met': rsi_current > 65,
                        'ema_bearish_met': ema20 < ema50,
                        'extreme_high_rsi_met': rsi_current > 75 and rsi_prev < rsi_current
                    },
                    'recommendation': 'انتظار'
                }
                
                # تحديد التوصية
                if analysis['signals']['buy_signal']:
                    analysis['recommendation'] = 'شراء قوي'
                elif analysis['conditions']['rsi_oversold_met'] and analysis['conditions']['ema_bullish_met']:
                    analysis['recommendation'] = 'شراء محتمل'
                elif analysis['signals']['sell_signal']:
                    analysis['recommendation'] = 'بيع قوي'
                elif analysis['conditions']['rsi_overbought_met'] and analysis['conditions']['ema_bearish_met']:
                    analysis['recommendation'] = 'بيع محتمل'
                
                debug_data['detailed_analysis'][symbol] = analysis
                debug_data['trading_signals']['current_signals'][symbol] = {
                    'signal': analysis['recommendation'],
                    'rsi': rsi_current,
                    'price': current_price,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                
                debug_logger.log('INFO', f'{symbol}: {analysis["recommendation"]} (RSI: {rsi_current:.2f})')
                
            except Exception as e:
                debug_logger.log('ERROR', f'خطأ في تحليل {symbol}: {str(e)}')
                debug_data['detailed_analysis'][symbol] = {'error': str(e)}
                
    except Exception as e:
        debug_logger.log('ERROR', f'خطأ في تحليل شروط التداول: {str(e)}')

def monitor_system_resources():
    """مراقبة موارد النظام"""
    try:
        import psutil
        
        # استخدام الذاكرة
        memory = psutil.virtual_memory()
        debug_data['performance']['memory_usage'] = round(memory.percent, 2)
        
        # استخدام المعالج
        cpu_percent = psutil.cpu_percent(interval=1)
        debug_data['performance']['cpu_usage'] = round(cpu_percent, 2)
        
        debug_logger.log('INFO', f'استخدام الذاكرة: {memory.percent:.1f}% | المعالج: {cpu_percent:.1f}%')
        
    except ImportError:
        debug_logger.log('WARNING', 'مكتبة psutil غير متوفرة لمراقبة الموارد')
    except Exception as e:
        debug_logger.log('ERROR', f'خطأ في مراقبة الموارد: {str(e)}')

def debug_monitoring_loop():
    """حلقة مراقبة Debug"""
    debug_data['system_status']['start_time'] = datetime.now(timezone.utc).isoformat()
    debug_data['system_status']['bot_running'] = True
    
    debug_logger.log('INFO', 'بدء مراقبة Debug...')
    
    while True:
        try:
            start_time = time.time()
            
            # زيادة عداد التكرارات
            debug_data['system_status']['iterations'] += 1
            
            # حساب وقت التشغيل
            if debug_data['system_status']['start_time']:
                start = datetime.fromisoformat(debug_data['system_status']['start_time'].replace('Z', '+00:00'))
                uptime = datetime.now(timezone.utc) - start
                debug_data['system_status']['uptime'] = int(uptime.total_seconds())
            
            # اختبار API كل 10 تكرارات
            if debug_data['system_status']['iterations'] % 10 == 1:
                test_api_connection()
            
            # تحليل شروط التداول
            analyze_trading_conditions()
            
            # مراقبة الموارد كل 5 تكرارات
            if debug_data['system_status']['iterations'] % 5 == 0:
                monitor_system_resources()
            
            # حساب متوسط وقت المعالجة
            processing_time = (time.time() - start_time) * 1000
            if debug_data['performance']['avg_processing_time'] == 0:
                debug_data['performance']['avg_processing_time'] = processing_time
            else:
                debug_data['performance']['avg_processing_time'] = (
                    debug_data['performance']['avg_processing_time'] * 0.9 + 
                    processing_time * 0.1
                )
            
            debug_logger.log('INFO', f'اكتمل التكرار #{debug_data["system_status"]["iterations"]} في {processing_time:.1f}ms')
            
            time.sleep(30)  # كل 30 ثانية
            
        except KeyboardInterrupt:
            debug_logger.log('INFO', 'تم إيقاف المراقبة بواسطة المستخدم')
            break
        except Exception as e:
            debug_data['system_status']['last_error'] = str(e)
            debug_logger.log('ERROR', f'خطأ في حلقة المراقبة: {str(e)}')
            debug_logger.log('ERROR', f'تفاصيل الخطأ: {traceback.format_exc()}')
            time.sleep(30)
    
    debug_data['system_status']['bot_running'] = False

@app.route('/')
def debug_dashboard():
    return render_template('debug.html')

@app.route('/api/debug_data')
def get_debug_data():
    return jsonify(debug_data)

@app.route('/api/test_api')
def test_api_endpoint():
    success = test_api_connection()
    return jsonify({'success': success, 'timestamp': datetime.now(timezone.utc).isoformat()})

@app.route('/api/run_analysis')
def run_analysis():
    try:
        analyze_trading_conditions()
        return jsonify({'success': True, 'message': 'تم تشغيل التحليل بنجاح'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear_logs')
def clear_logs():
    debug_data['logs'] = []
    debug_data['errors'] = []
    debug_logger.log('INFO', 'تم مسح السجلات')
    return jsonify({'success': True})

@app.route('/api/export_data')
def export_debug_data():
    """تصدير بيانات Debug كملف JSON"""
    export_data = {
        'export_time': datetime.now(timezone.utc).isoformat(),
        'debug_data': debug_data,
        'settings': {
            'symbols': SYMBOLS,
            'timeframe': TIMEFRAME,
            'rsi_period': RSI_PERIOD,
            'bot_live': BOT_LIVE,
            'account_per_pair': ACCOUNT_PER_PAIR
        }
    }
    return jsonify(export_data)

if __name__ == '__main__':
    print(f"🔍 تشغيل لوحة Debug على http://{DEBUG_HOST}:{DEBUG_PORT}")
    print("الميزات المتوفرة:")
    print("- مراقبة حالة API والاتصال")
    print("- تحليل مفصل للمؤشرات والإشارات")
    print("- مراقبة الأخطاء والسجلات")
    print("- إحصائيات الأداء والموارد")
    print("- اختبارات يدوية وتصدير البيانات")
    
    # بدء مراقبة Debug في thread منفصل
    debug_thread = threading.Thread(target=debug_monitoring_loop, daemon=True)
    debug_thread.start()
    
    # بدء الخادم
    app.run(host=DEBUG_HOST, port=DEBUG_PORT, debug=False)
