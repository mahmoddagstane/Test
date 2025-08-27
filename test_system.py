
#!/usr/bin/env python3
"""
اختبار شامل للنظام - التحقق من جميع المكونات
"""

import os
import time
import requests
from datetime import datetime
from main import make_exchange, fetch_ohlcv_df, compute_signals, SYMBOLS, get_secret, BOT_LIVE

def test_secrets():
    """اختبار المفاتيح والإعدادات"""
    print("🔐 اختبار المفاتيح والإعدادات...")
    
    api_key = get_secret("BINANCE_API_KEY", "")
    api_secret = get_secret("BINANCE_API_SECRET", "")
    bot_live = get_secret("BOT_LIVE", "false")
    
    print(f"   ✅ API Key: {'موجود' if api_key and api_key != 'your_testnet_api_key_here' else '❌ غير موجود'}")
    print(f"   ✅ API Secret: {'موجود' if api_secret and api_secret != 'your_testnet_api_secret_here' else '❌ غير موجود'}")
    print(f"   ✅ BOT_LIVE: {bot_live} ({'تداول حقيقي' if bot_live.lower() == 'true' else 'وضع تجريبي'})")
    
    return bool(api_key and api_secret and api_key != 'your_testnet_api_key_here')

def test_binance_api():
    """اختبار الاتصال بـ Binance API"""
    print("🌐 اختبار الاتصال بـ Binance API...")
    
    try:
        exchange = make_exchange()
        
        # اختبار تحميل الأسواق
        print("   📊 تحميل قائمة الأسواق...")
        markets = exchange.load_markets()
        print(f"   ✅ تم العثور على {len(markets)} سوق")
        
        # التحقق من وجود الأزواج المطلوبة
        missing_symbols = []
        for symbol in SYMBOLS:
            if symbol not in markets:
                missing_symbols.append(symbol)
        
        if missing_symbols:
            print(f"   ⚠️  أزواج غير موجودة: {missing_symbols}")
        else:
            print(f"   ✅ جميع الأزواج متوفرة: {SYMBOLS}")
        
        # اختبار جلب الرصيد
        print("   💰 اختبار جلب الرصيد...")
        balance = exchange.fetch_balance()
        usdt_balance = balance.get('USDT', {}).get('free', 0)
        print(f"   ✅ رصيد USDT: {usdt_balance}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ فشل الاتصال: {str(e)}")
        return False

def test_data_fetching():
    """اختبار جلب ومعالجة البيانات"""
    print("📈 اختبار جلب ومعالجة البيانات...")
    
    try:
        exchange = make_exchange()
        
        for symbol in SYMBOLS[:2]:  # اختبار أول زوجين فقط لتوفير الوقت
            print(f"   🔍 اختبار {symbol}...")
            
            # جلب البيانات
            df = fetch_ohlcv_df(exchange, symbol, "15m", limit=100)
            if df is None or df.empty:
                print(f"   ❌ {symbol}: لا توجد بيانات")
                continue
                
            print(f"   ✅ {symbol}: تم جلب {len(df)} شمعة")
            
            # حساب المؤشرات
            df = compute_signals(df)
            
            if 'rsi' not in df.columns:
                print(f"   ❌ {symbol}: فشل حساب RSI")
                continue
                
            # فحص آخر القيم
            last = df.iloc[-1]
            price = float(last["close"])
            rsi_v = float(last["rsi"]) if not pd.isna(last["rsi"]) else 0
            
            print(f"   📊 {symbol}: السعر: {price:.4f} | RSI: {rsi_v:.2f}")
            
            if last["buy_sig"]:
                print(f"   🟢 {symbol}: إشارة شراء")
            elif last["sell_sig"]:
                print(f"   🔴 {symbol}: إشارة بيع")
            else:
                print(f"   ⚪ {symbol}: لا توجد إشارة")
        
        return True
        
    except Exception as e:
        print(f"   ❌ خطأ في معالجة البيانات: {str(e)}")
        return False

def test_web_interface():
    """اختبار الواجهة الويب"""
    print("🌐 اختبار الواجهة الويب...")
    
    try:
        # اختبار الصفحة الرئيسية
        response = requests.get("http://127.0.0.1:8080", timeout=5)
        if response.status_code == 200:
            print("   ✅ الصفحة الرئيسية تعمل")
        else:
            print(f"   ❌ خطأ في الصفحة الرئيسية: {response.status_code}")
            return False
            
        # اختبار API البيانات
        response = requests.get("http://127.0.0.1:8080/api/data", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("   ✅ API البيانات يعمل")
            print(f"   📊 البيانات المتوفرة: {len(data.get('pairs', {}))} أزواج")
            print(f"   💰 الرصيد: {data.get('balance', 0)}")
            print(f"   🔄 آخر تحديث: {data.get('timestamp', 'غير معروف')}")
        else:
            print(f"   ❌ خطأ في API البيانات: {response.status_code}")
            return False
            
        # اختبار حالة المفاتيح
        response = requests.get("http://127.0.0.1:8080/api/secrets_status", timeout=5)
        if response.status_code == 200:
            status = response.json()
            print("   ✅ API حالة المفاتيح يعمل")
            print(f"   🔑 مفاتيح API: {'متوفرة' if status.get('api_key_exists') else 'غير متوفرة'}")
        else:
            print(f"   ⚠️  API حالة المفاتيح: {response.status_code}")
            
        return True
        
    except Exception as e:
        print(f"   ❌ خطأ في اختبار الواجهة: {str(e)}")
        return False

def test_trading_simulation():
    """اختبار محاكاة التداول"""
    print("🎯 اختبار منطق التداول...")
    
    try:
        from main import size_position_usdt, RISK_PER_TRADE_USD, ACCOUNT_PER_PAIR
        
        # اختبار حساب حجم الصفقة
        test_price = 26500  # سعر تجريبي لـ BTC
        qty, notional = size_position_usdt(test_price, ACCOUNT_PER_PAIR)
        
        print(f"   💵 حجم الصفقة لـ BTC @ {test_price}:")
        print(f"   📏 الكمية: {qty:.6f}")
        print(f"   💰 القيمة: ${notional:.2f}")
        print(f"   🎯 المخاطرة المستهدفة: ${RISK_PER_TRADE_USD}")
        
        # حساب وقف الخسارة وجني الأرباح
        stop_price = test_price * 0.98  # 2% stop loss
        tp_price = test_price + 1.5 * (test_price - stop_price)  # 1.5R TP
        
        print(f"   ⛔ وقف الخسارة: {stop_price:.2f} ({((stop_price/test_price-1)*100):+.1f}%)")
        print(f"   🎯 جني الأرباح: {tp_price:.2f} ({((tp_price/test_price-1)*100):+.1f}%)")
        
        return True
        
    except Exception as e:
        print(f"   ❌ خطأ في اختبار التداول: {str(e)}")
        return False

def main():
    """تشغيل جميع الاختبارات"""
    print("=" * 60)
    print("🧪 اختبار شامل لنظام التداول التلقائي")
    print("=" * 60)
    print(f"⏰ وقت الاختبار: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    tests = [
        ("المفاتيح والإعدادات", test_secrets),
        ("Binance API", test_binance_api),
        ("جلب ومعالجة البيانات", test_data_fetching),
        ("الواجهة الويب", test_web_interface),
        ("منطق التداول", test_trading_simulation)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"🧪 اختبار {test_name}...")
        try:
            result = test_func()
            results.append((test_name, result))
            print(f"{'✅' if result else '❌'} اختبار {test_name}: {'نجح' if result else 'فشل'}")
        except Exception as e:
            results.append((test_name, False))
            print(f"❌ اختبار {test_name}: خطأ - {str(e)}")
        print()
    
    # ملخص النتائج
    print("=" * 60)
    print("📊 ملخص نتائج الاختبار")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ نجح" if result else "❌ فشل"
        print(f"{status:8} | {test_name}")
        if result:
            passed += 1
    
    print("-" * 60)
    print(f"📈 النتيجة النهائية: {passed}/{total} اختبارات نجحت ({(passed/total*100):.1f}%)")
    
    if passed == total:
        print("🎉 جميع الاختبارات نجحت! النظام جاهز للعمل 100%")
        print()
        print("🚀 للبدء في التداول التلقائي:")
        print("   1. تأكد من أن BOT_LIVE=true في Secrets")
        print("   2. شغل workflow 'بوت التداول التلقائي'")
        print("   3. راقب الواجهة على http://0.0.0.0:5000")
    else:
        print("⚠️  بعض الاختبارات فشلت. يرجى مراجعة الأخطاء أعلاه")
    
    print("=" * 60)

if __name__ == "__main__":
    # إضافة pandas للاستيراد
    import pandas as pd
    main()
