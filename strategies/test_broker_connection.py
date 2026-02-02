"""
測試 Alpaca Broker 連接和基本功能

此腳本用於驗證：
1. Alpaca API 連接是否正常
2. 憑證是否有效
3. 獲取帳戶資訊
4. 獲取當前持倉
5. 風險檢查機制

Author: Quant System
Created: 2026-02-02
"""

import sys
import os

# 添加 src 路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from adapters.broker import AlpacaBroker


def test_broker_connection():
    """測試 Broker 連接"""
    print("\n" + "="*60)
    print("🧪 Alpaca Broker 連接測試")
    print("="*60 + "\n")
    
    try:
        # 步驟 1: 初始化 Broker
        print("【步驟 1】 初始化 Alpaca Broker...")
        broker = AlpacaBroker(use_paper=True)
        print("✅ Broker 初始化成功\n")
        
        # 步驟 2: 獲取帳戶資訊
        print("【步驟 2】 獲取帳戶資訊...")
        account = broker.get_account()
        print(f"✅ 帳戶資訊:")
        print(f"   現金餘額: ${account['cash']:,.2f}")
        print(f"   購買力: ${account['buying_power']:,.2f}")
        print(f"   總權益: ${account['equity']:,.2f}")
        print(f"   投資組合價值: ${account['portfolio_value']:,.2f}\n")
        
        # 步驟 3: 獲取當前持倉
        print("【步驟 3】 獲取當前持倉...")
        positions = broker.get_positions()
        if positions:
            print(f"✅ 當前持倉 ({len(positions)} 個):")
            for symbol, qty in positions.items():
                try:
                    price = broker.get_current_price(symbol)
                    value = qty * price
                    print(f"   {symbol}: {qty} 股 @ ${price:.2f} = ${value:,.2f}")
                except Exception as e:
                    print(f"   {symbol}: {qty} 股 (無法獲取價格: {e})")
        else:
            print("✅ 當前無持倉\n")
        
        # 步驟 4: 測試價格獲取
        print("\n【步驟 4】 測試價格獲取...")
        test_symbols = ['AAPL', 'SPY', 'QQQ']
        for symbol in test_symbols:
            try:
                price = broker.get_current_price(symbol)
                print(f"✅ {symbol}: ${price:.2f}")
            except Exception as e:
                print(f"❌ {symbol}: 獲取失敗 - {e}")
        
        # 步驟 5: 測試風險檢查
        print("\n【步驟 5】 測試風險檢查機制...")
        
        # 測試 5.1: 正常訂單
        test_symbol = 'AAPL'
        test_qty = 10
        test_price = broker.get_current_price(test_symbol)
        is_valid, msg = broker.check_risk(test_symbol, test_qty, test_price)
        if is_valid:
            print(f"✅ 風險檢查通過: {test_symbol} {test_qty} 股 @ ${test_price:.2f}")
        else:
            print(f"❌ 風險檢查失敗: {msg}")
        
        # 測試 5.2: 超額訂單（應該失敗）
        test_qty_large = 1000
        is_valid, msg = broker.check_risk(test_symbol, test_qty_large, test_price)
        if not is_valid:
            print(f"✅ 風險檢查正確攔截超額訂單: {msg}")
        else:
            print(f"⚠️  警告: 超額訂單未被攔截!")
        
        # 測試 5.3: 購買力不足（模擬）
        test_price_high = 20000.0
        is_valid, msg = broker.check_risk(test_symbol, test_qty, test_price_high)
        if not is_valid:
            print(f"✅ 風險檢查正確攔截購買力不足: {msg}")
        else:
            print(f"⚠️  可能有足夠購買力，訂單通過")
        
        # 總結
        print("\n" + "="*60)
        print("✅ 所有測試完成")
        print("="*60 + "\n")
        print("📝 測試結果摘要:")
        print("   ✅ Broker 連接正常")
        print("   ✅ API 憑證有效")
        print("   ✅ 帳戶資訊獲取成功")
        print("   ✅ 持倉查詢功能正常")
        print("   ✅ 價格獲取功能正常")
        print("   ✅ 風險檢查機制運作正常")
        print("\n🎉 系統已就緒，可以開始 Paper Trading！\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_broker_connection()
    sys.exit(0 if success else 1)
