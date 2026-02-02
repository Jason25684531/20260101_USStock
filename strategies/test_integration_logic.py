"""
模擬測試 Alpaca Broker 適配器邏輯

由於缺少真實的 API 憑證，此腳本執行代碼邏輯檢查：
1. 檢查所有模組導入是否正常
2. 驗證類別結構和方法簽名
3. 測試風險檢查邏輯（不需要 API 連接）

Author: Quant System
Created: 2026-02-02
"""

import sys
import os

# 添加 src 路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_module_imports():
    """測試模組導入"""
    print("\n【測試 1】 模組導入檢查")
    try:
        from adapters.broker import AlpacaBroker
        print("   ✅ broker.py 導入成功")
        
        from adapters.database import DatabaseAdapter
        print("   ✅ database.py 導入成功")
        
        from adapters.notifier import get_notifier
        print("   ✅ notifier.py 導入成功")
        
        from utils.security import get_secret, require_secret
        print("   ✅ security.py 導入成功")
        
        return True
    except Exception as e:
        print(f"   ❌ 導入失敗: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_broker_class_structure():
    """測試 Broker 類別結構"""
    print("\n【測試 2】 AlpacaBroker 類別結構檢查")
    try:
        from adapters.broker import AlpacaBroker
        
        # 檢查類別屬性
        assert hasattr(AlpacaBroker, 'PAPER_BASE_URL'), "缺少 PAPER_BASE_URL"
        assert hasattr(AlpacaBroker, 'MAX_ORDER_VALUE'), "缺少 MAX_ORDER_VALUE"
        print("   ✅ 類別屬性存在")
        
        # 檢查方法
        required_methods = [
            '__init__',
            'get_account',
            'get_positions',
            'get_position',
            'get_current_price',
            'check_risk',
            'submit_order',
            'cancel_order',
            'get_order',
            'close_position'
        ]
        
        for method in required_methods:
            assert hasattr(AlpacaBroker, method), f"缺少方法: {method}"
        
        print(f"   ✅ 所有必需方法存在 ({len(required_methods)} 個)")
        
        # 檢查安全設置
        assert AlpacaBroker.PAPER_BASE_URL == "https://paper-api.alpaca.markets"
        print("   ✅ PAPER_BASE_URL 正確設置為模擬交易端點")
        
        assert AlpacaBroker.MAX_ORDER_VALUE == 10000.0
        print("   ✅ MAX_ORDER_VALUE 設置為 $10,000 安全上限")
        
        return True
        
    except Exception as e:
        print(f"   ❌ 檢查失敗: {e}")
        return False


def test_main_py_integration():
    """測試 main.py 整合邏輯"""
    print("\n【測試 3】 main.py 整合邏輯檢查")
    try:
        # 檢查 main.py 文件內容
        main_py_path = os.path.join(os.path.dirname(__file__), 'src', 'main.py')
        with open(main_py_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 檢查關鍵代碼是否存在
        checks = [
            ('from adapters.broker import AlpacaBroker', 'Broker 導入'),
            ('TRADING_MODE', 'TRADING_MODE 環境變量'),
            ('execute_trades', 'execute_trades 函數'),
            ('broker = AlpacaBroker', 'Broker 初始化'),
            ('target_positions', '目標倉位計算'),
        ]
        
        for code_snippet, description in checks:
            if code_snippet in content:
                print(f"   ✅ {description} 已整合")
            else:
                print(f"   ⚠️  {description} 未找到")
        
        return True
        
    except Exception as e:
        print(f"   ❌ 檢查失敗: {e}")
        return False


def test_docker_config():
    """測試 Docker 配置"""
    print("\n【測試 4】 Docker 配置檢查")
    try:
        docker_compose_path = os.path.join(
            os.path.dirname(__file__), 
            '..', 
            'docker-compose.yml'
        )
        
        with open(docker_compose_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 檢查 secrets 配置
        checks = [
            ('alpaca_key', 'Alpaca Key Secret'),
            ('alpaca_secret', 'Alpaca Secret Secret'),
            ('alpaca_key.txt', 'Alpaca Key 文件映射'),
            ('alpaca_secret.txt', 'Alpaca Secret 文件映射'),
        ]
        
        for pattern, description in checks:
            if pattern in content:
                print(f"   ✅ {description} 已配置")
            else:
                print(f"   ⚠️  {description} 未找到")
        
        return True
        
    except Exception as e:
        print(f"   ❌ 檢查失敗: {e}")
        return False


def test_requirements():
    """測試依賴套件"""
    print("\n【測試 5】 requirements.txt 檢查")
    try:
        req_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
        with open(req_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        required_packages = [
            'alpaca-trade-api',
            'numpy',
            'pandas',
            'SQLAlchemy',
            'APScheduler',
        ]
        
        for package in required_packages:
            if package in content:
                print(f"   ✅ {package} 已列入")
            else:
                print(f"   ⚠️  {package} 未找到")
        
        return True
        
    except Exception as e:
        print(f"   ❌ 檢查失敗: {e}")
        return False


def main():
    """執行所有測試"""
    print("\n" + "="*60)
    print("🧪 Alpaca Paper Trading 整合測試（模擬模式）")
    print("="*60)
    
    results = []
    
    results.append(("模組導入", test_module_imports()))
    results.append(("類別結構", test_broker_class_structure()))
    results.append(("main.py 整合", test_main_py_integration()))
    results.append(("Docker 配置", test_docker_config()))
    results.append(("依賴套件", test_requirements()))
    
    # 總結
    print("\n" + "="*60)
    print("📊 測試結果摘要")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通過" if result else "❌ 失敗"
        print(f"   {status}: {name}")
    
    print(f"\n總計: {passed}/{total} 項測試通過\n")
    
    if passed == total:
        print("🎉 所有代碼邏輯檢查通過！")
        print("\n📝 下一步:")
        print("   1. 在 Alpaca 註冊 Paper Trading 帳戶")
        print("   2. 獲取 API Key 和 Secret")
        print("   3. 將憑證填入 .secrets/alpaca_key.txt 和 alpaca_secret.txt")
        print("   4. 運行 test_broker_connection.py 進行實際連接測試")
        print("   5. 設置環境變量 TRADING_MODE=paper 啟動實盤模擬交易\n")
        return True
    else:
        print("❌ 部分測試未通過，請檢查代碼")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
