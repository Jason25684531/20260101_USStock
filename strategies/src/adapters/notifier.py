"""
Line Bot 通知適配器

提供 Line Bot 推送通知功能，用於發送交易信號和系統警報
使用 Docker Secrets 安全管理 Channel Access Token

Author: Quant System
Created: 2026-01-31
"""

import os
import json
import requests
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

# Docker Secrets 路徑
SECRETS_PATH = Path("/run/secrets")


def get_secret(secret_name: str, default: Optional[str] = None) -> Optional[str]:
    """從 Docker Secrets 或環境變量獲取密鑰"""
    secret_file = SECRETS_PATH / secret_name
    if secret_file.exists():
        try:
            return secret_file.read_text().strip()
        except (IOError, PermissionError):
            pass
    
    if SECRETS_PATH.exists():
        return default
    
    return os.environ.get(secret_name.upper(), default)


class LineNotifier:
    """Line Bot 通知器"""
    
    def __init__(self):
        """初始化 Line Bot 通知器"""
        self.channel_token = get_secret('line_channel_token')
        self.user_id = get_secret('line_user_id')  # 接收通知的用戶 ID
        self.api_url = "https://api.line.me/v2/bot/message/push"
        
        if not self.channel_token:
            print("⚠️  Line Channel Token 未配置，通知功能將被禁用")
        if not self.user_id:
            print("⚠️  Line User ID 未配置，通知功能將被禁用")
    
    @property
    def is_enabled(self) -> bool:
        """檢查通知功能是否啟用"""
        return bool(self.channel_token and self.user_id)
    
    def _send_message(self, messages: list) -> bool:
        """
        發送消息到 Line
        
        Args:
            messages: Line 消息對象列表
            
        Returns:
            是否發送成功
        """
        if not self.is_enabled:
            print("⚠️  Line 通知未啟用，跳過發送")
            return False
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_token}"
        }
        
        payload = {
            "to": self.user_id,
            "messages": messages
        }
        
        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"✅ Line 通知發送成功")
                return True
            else:
                print(f"❌ Line 通知發送失敗: {response.status_code} - {response.text}")
                return False
                
        except requests.RequestException as e:
            print(f"❌ Line 通知請求失敗: {str(e)}")
            return False
    
    def send_text(self, message: str) -> bool:
        """
        發送純文本消息
        
        Args:
            message: 消息內容
            
        Returns:
            是否發送成功
        """
        return self._send_message([{
            "type": "text",
            "text": message
        }])
    
    def send_signal(
        self,
        symbol: str,
        action: str,
        price: float,
        reason: str,
        strategy: str = "Unknown"
    ) -> bool:
        """
        發送交易信號通知
        
        Args:
            symbol: 股票代碼
            action: 動作 (BUY/SELL/HOLD)
            price: 當前價格
            reason: 觸發原因
            strategy: 策略名稱
            
        Returns:
            是否發送成功
        """
        # 動作表情
        action_emoji = {
            "BUY": "🟢",
            "SELL": "🔴",
            "HOLD": "🟡"
        }.get(action.upper(), "⚪")
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"""
{action_emoji} 交易信號 {action_emoji}

📊 股票代碼: {symbol}
📈 動作: {action.upper()}
💰 價格: ${price:,.2f}
🎯 策略: {strategy}
📝 原因: {reason}

⏰ 時間: {timestamp}
""".strip()
        
        return self.send_text(message)
    
    def send_daily_summary(
        self,
        total_trades: int,
        pnl: float,
        win_rate: float,
        top_performers: list
    ) -> bool:
        """
        發送每日交易摘要
        
        Args:
            total_trades: 總交易數
            pnl: 當日損益
            win_rate: 勝率
            top_performers: 表現最好的股票列表
            
        Returns:
            是否發送成功
        """
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        timestamp = datetime.now().strftime("%Y-%m-%d")
        
        performers_str = "\n".join([f"  • {p}" for p in top_performers[:5]])
        
        message = f"""
📊 每日交易摘要 - {timestamp}

📋 總交易數: {total_trades}
{pnl_emoji} 當日損益: ${pnl:+,.2f}
🎯 勝率: {win_rate:.1f}%

🏆 表現最佳:
{performers_str}

💡 系統運行正常
""".strip()
        
        return self.send_text(message)
    
    def send_error_alert(self, error_type: str, details: str) -> bool:
        """
        發送錯誤警報
        
        Args:
            error_type: 錯誤類型
            details: 錯誤詳情
            
        Returns:
            是否發送成功
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"""
🚨 系統警報 🚨

⚠️ 錯誤類型: {error_type}
📝 詳細信息: {details}

⏰ 時間: {timestamp}

請檢查系統狀態
""".strip()
        
        return self.send_text(message)


# 全局通知器實例
_notifier: Optional[LineNotifier] = None


def get_notifier() -> LineNotifier:
    """獲取全局通知器實例"""
    global _notifier
    if _notifier is None:
        _notifier = LineNotifier()
    return _notifier


def send_signal(
    symbol: str,
    action: str,
    price: float,
    reason: str,
    strategy: str = "Unknown"
) -> bool:
    """
    發送交易信號（便捷函數）
    
    Args:
        symbol: 股票代碼
        action: 動作 (BUY/SELL/HOLD)
        price: 當前價格
        reason: 觸發原因
        strategy: 策略名稱
        
    Returns:
        是否發送成功
    """
    return get_notifier().send_signal(symbol, action, price, reason, strategy)
