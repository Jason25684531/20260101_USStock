"""
測試腳本：Line Bot 通知功能

用於驗證 Line Bot 配置是否正確
可以發送測試消息到您的 Line 帳號

使用方式：
1. 確保已配置 .secrets/line_channel_token.txt 和 .secrets/line_user_id.txt
2. 運行: python test_line_notification.py

Author: Quant System
Created: 2026-01-31
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# 添加 src 目錄到路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def test_notifier():
    """測試 Line 通知器"""
    print("\n" + "="*60)
    print("🧪 Line Bot 通知測試")
    print("="*60 + "\n")
    
    # 檢查 secrets 文件
    secrets_path = Path(__file__).parent.parent / '.secrets'
    
    token_file = secrets_path / 'line_channel_token.txt'
    user_id_file = secrets_path / 'line_user_id.txt'
    
    print("📋 檢查配置文件...")
    
    if not token_file.exists():
        print(f"❌ 缺少 {token_file}")
        print("   請創建此文件並填入 Line Channel Access Token")
        return False
    
    if not user_id_file.exists():
        print(f"❌ 缺少 {user_id_file}")
        print("   請創建此文件並填入您的 Line User ID")
        return False
    
    # 讀取配置
    token = token_file.read_text().strip()
    user_id = user_id_file.read_text().strip()
    
    if token.startswith("YOUR_"):
        print("⚠️  Line Channel Token 尚未配置（仍為佔位符）")
        print("   請替換為真實的 Token")
        return False
    
    if user_id.startswith("YOUR_"):
        print("⚠️  Line User ID 尚未配置（仍為佔位符）")
        print("   請替換為真實的 User ID")
        return False
    
    print("✅ 配置文件檢查通過\n")
    
    # 測試發送消息
    print("📤 發送測試消息...")
    
    import requests
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    test_message = f"""
🧪 測試消息

這是來自美股交易策略系統的測試通知。

如果您收到這條消息，表示 Line Bot 配置正確！

⏰ 發送時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""".strip()
    
    payload = {
        "to": user_id,
        "messages": [{
            "type": "text",
            "text": test_message
        }]
    }
    
    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=headers,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            print("✅ 測試消息發送成功！")
            print("   請檢查您的 Line 是否收到消息")
            return True
        else:
            print(f"❌ 發送失敗: {response.status_code}")
            print(f"   錯誤信息: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ 請求失敗: {str(e)}")
        return False


def test_signal():
    """測試交易信號通知"""
    print("\n" + "-"*60)
    print("📊 測試交易信號通知")
    print("-"*60 + "\n")
    
    try:
        from adapters.notifier import send_signal
        
        result = send_signal(
            symbol="AAPL",
            action="BUY",
            price=185.50,
            reason="SMA 黃金交叉 + 機構持股 > 60%",
            strategy="Chips + Momentum"
        )
        
        if result:
            print("✅ 交易信號通知發送成功！")
        else:
            print("⚠️  交易信號通知未發送（可能未配置 Line Bot）")
            
    except ImportError as e:
        print(f"⚠️  無法導入通知模塊: {e}")
        print("   這在本地測試時是正常的")


if __name__ == '__main__':
    success = test_notifier()
    
    if success:
        test_signal()
    
    print("\n" + "="*60)
    print("測試完成")
    print("="*60 + "\n")
