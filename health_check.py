
#!/usr/bin/env python3
"""
نظام فحص الصحة العامة للبوت
"""

import time
import requests
from datetime import datetime, timezone
from main import make_exchange, SYMBOLS, get_secret, BOT_LIVE

def check_system_health():
    """فحص شامل لصحة النظام"""
    health_status = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'overall_status': 'healthy',
        'checks': {}
    }
    
    # فحص مفاتيح API
    try:
        api_key = get_secret("BINANCE_API_KEY", "")
        api_secret = get_secret("BINANCE_API_SECRET", "")
        
        if api_key and api_secret and api_key != "your_testnet_api_key_here":
            health_status['checks']['api_keys'] = 'OK'
        else:
            health_status['checks']['api_keys'] = 'MISSING'
            health_status['overall_status'] = 'warning'
    except Exception as e:
        health_status['checks']['api_keys'] = f'ERROR: {str(e)}'
        health_status['overall_status'] = 'error'
    
    # فحص الاتصال بـ API
    try:
        exchange = make_exchange()
        markets = exchange.load_markets()
        health_status['checks']['api_connection'] = f'OK - {len(markets)} markets'
        
        # فحص الرصيد
        balance = exchange.fetch_balance()
        usdt_balance = balance.get('USDT', {}).get('free', 0)
        health_status['checks']['balance'] = f'USDT: {usdt_balance}'
        
    except Exception as e:
        health_status['checks']['api_connection'] = f'FAILED: {str(e)}'
        health_status['overall_status'] = 'error'
    
    # فحص الواجهة الويب
    try:
        response = requests.get("http://127.0.0.1:5000/api/data", timeout=5)
        if response.status_code == 200:
            health_status['checks']['web_interface'] = 'OK'
        else:
            health_status['checks']['web_interface'] = f'HTTP {response.status_code}'
            health_status['overall_status'] = 'warning'
    except Exception as e:
        health_status['checks']['web_interface'] = f'FAILED: {str(e)}'
        health_status['overall_status'] = 'warning'
    
    # فحص البيانات للأزواج
    try:
        from main import fetch_ohlcv_df, compute_signals
        exchange = make_exchange()
        
        working_pairs = 0
        for symbol in SYMBOLS:
            try:
                df = fetch_ohlcv_df(exchange, symbol, "15m", limit=50)
                if df is not None and not df.empty:
                    df_signals = compute_signals(df)
                    if not df_signals.empty and 'rsi' in df_signals.columns:
                        working_pairs += 1
            except:
                continue
                
        health_status['checks']['market_data'] = f'{working_pairs}/{len(SYMBOLS)} pairs working'
        
        if working_pairs < len(SYMBOLS):
            health_status['overall_status'] = 'warning'
            
    except Exception as e:
        health_status['checks']['market_data'] = f'ERROR: {str(e)}'
        health_status['overall_status'] = 'error'
    
    # تقييم الحالة العامة
    error_count = sum(1 for check in health_status['checks'].values() 
                     if 'ERROR' in str(check) or 'FAILED' in str(check))
    warning_count = sum(1 for check in health_status['checks'].values() 
                       if 'HTTP' in str(check) and 'OK' not in str(check))
    
    if error_count > 0:
        health_status['overall_status'] = 'error'
    elif warning_count > 0:
        health_status['overall_status'] = 'warning'
    else:
        health_status['overall_status'] = 'healthy'
    
    return health_status

def print_health_report():
    """طباعة تقرير الصحة"""
    health = check_system_health()
    
    status_icons = {
        'healthy': '🟢',
        'warning': '🟡', 
        'error': '🔴'
    }
    
    print(f"\n{'='*50}")
    print(f"🏥 تقرير الصحة العامة للنظام")
    print(f"{'='*50}")
    print(f"⏰ الوقت: {health['timestamp']}")
    print(f"{status_icons[health['overall_status']]} الحالة العامة: {health['overall_status'].upper()}")
    print(f"\n📋 فحص المكونات:")
    
    for check_name, result in health['checks'].items():
        icon = '✅' if 'OK' in str(result) else '⚠️' if 'HTTP' in str(result) else '❌'
        print(f"   {icon} {check_name}: {result}")
    
    print(f"{'='*50}")
    
    return health['overall_status'] == 'healthy'

if __name__ == "__main__":
    print_health_report()
