"""
Line Bot 通知適配器

提供 Line Bot 推送通知功能，用於發送交易信號、系統警報、
及 Flex Message 格式的每日選股推薦報告。
使用 Docker Secrets 安全管理 Channel Access Token

Author: Quant System
Created: 2026-01-31
Updated: 2026-02-12 - 新增 Flex Message 推薦報告
"""

import json
import logging
import sys
from pathlib import Path
import requests
from datetime import datetime, date
from typing import Optional, Dict, List

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_STRATEGIES_SRC = _PROJECT_ROOT / 'strategies' / 'src'
_STRATEGIES_SRC_STR = str(_STRATEGIES_SRC)
if _STRATEGIES_SRC_STR not in sys.path:
    sys.path.insert(0, _STRATEGIES_SRC_STR)

try:
    from utils.line_flex import (
        build_decision_bubble,
        build_recommendation_flex_message,
        flex_kv,
        format_currency,
        sanitize_line_message,
    )
    from utils.security import get_secret
except ImportError:
    from strategies.src.utils.line_flex import (
        build_decision_bubble,
        build_recommendation_flex_message,
        flex_kv,
        format_currency,
        sanitize_line_message,
    )
    from strategies.src.utils.security import get_secret


logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)


class LineNotifier:
    """Line Bot 通知器"""
    
    def __init__(self):
        """初始化 Line Bot 通知器"""
        self.channel_token = get_secret('line_channel_access_token', default=get_secret('line_channel_token'))
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
        """Send one or more LINE messages after payload sanitization."""
        if not self.is_enabled:
            print("Line notifier is not enabled. Skip sending.")
            return False

        sanitized_messages = [sanitize_line_message(message) for message in messages]
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_token}"
        }

        payload = {
            "to": self.user_id,
            "messages": sanitized_messages
        }

        for message in sanitized_messages:
            if message.get("type") == "flex":
                logger.debug(json.dumps(message.get("contents", {}), ensure_ascii=False))

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=10
            )
        except requests.RequestException as error:
            logger.exception("LINE push request failed with payload=%s", json.dumps(payload, ensure_ascii=False))
            print(f"Line push request failed: {error}")
            return False

        if response.status_code == 200:
            print("Line push sent successfully.")
            return True

        logger.error("LINE push failed payload=%s", json.dumps(payload, ensure_ascii=False))
        print(f"Line push failed: {response.status_code} - {response.text}")
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

    # ===========================================================
    # Flex Message 每日推薦報告
    def send_flex_report(self, recommendations: List[Dict]) -> bool:
        """Send recommendation Flex cards using the shared canonical builder."""
        if not recommendations:
            return self.send_text("No recommendations available.")

        scan_date = date.today().strftime('%Y/%m/%d')
        flex_message = build_recommendation_flex_message(
            recommendations,
            title=f"Daily recommendations {scan_date}",
            limit=10,
        )

        return self._send_message([flex_message])

    def build_daily_screener_flex(self, top_n_df: pd.DataFrame) -> Dict:
        """Build the daily screener Flex carousel with the shared canonical builder."""
        if top_n_df is None or top_n_df.empty:
            return build_recommendation_flex_message([], title="Daily Screener", limit=5)

        latest_date = str(top_n_df["latest_date"].iloc[0]) if "latest_date" in top_n_df.columns else date.today().isoformat()
        return build_recommendation_flex_message(
            top_n_df.to_dict(orient="records"),
            title=f"Daily Screener {latest_date}",
            limit=5,
        )

    def send_daily_screener_flex(self, top_n_df: pd.DataFrame) -> bool:
        """Push the daily screener Flex payload; dry-run when LINE credentials are missing."""
        flex_message = sanitize_line_message(self.build_daily_screener_flex(top_n_df))
        if not self.is_enabled:
            preview = json.dumps(flex_message["contents"], ensure_ascii=False)[:400]
            print("Line token/user id not configured. Dry-run preview:")
            print(preview)
            return True

        return self._send_message([flex_message])

    def _build_daily_screener_bubble(self, rec: Dict) -> Dict:
        valuation_status = str(rec.get("valuation_status") or "FAIR").upper()
        status_label_map = {
            "UNDERVALUED": ("UNDERVALUED", "#0B6E4F"),
            "FAIR": ("FAIR", "#A16207"),
            "PREMIUM_GROWTH": ("FAIR", "#A16207"),
            "OVERVALUED": ("OVERVALUED", "#B42318"),
        }
        status_text, header_color = status_label_map.get(valuation_status, status_label_map["FAIR"])

        xgboost_score = rec.get("xgboost_score")
        buy_price = rec.get("buy_price")
        suggested_allocation_pct = rec.get("suggested_allocation_pct")
        ai_reason = str(rec.get("ai_reason") or "No AI summary")[:60]

        score_text = "N/A"
        if xgboost_score is not None and not pd.isna(xgboost_score):
            score_text = f"{float(xgboost_score):.2f}"

        buy_price_text = format_currency(buy_price)
        if buy_price_text != "N/A":
            buy_price_text = f"< {buy_price_text}"

        allocation_text = "N/A"
        if suggested_allocation_pct is not None and not pd.isna(suggested_allocation_pct):
            allocation_text = f"{float(suggested_allocation_pct):.1f}%"

        body_rows = [
            flex_kv("AI Score", score_text),
            flex_kv("Buy Below", buy_price_text),
            flex_kv("Allocation", allocation_text),
        ]

        return sanitize_line_message({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": header_color,
                "paddingAll": "14px",
                "contents": [
                    {"type": "text", "text": str(rec.get("symbol", "N/A")), "weight": "bold", "size": "xl", "color": "#FFFFFF"},
                    {"type": "text", "text": status_text, "size": "sm", "color": "#F9FAFB", "wrap": True, "margin": "sm"},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": body_rows,
                "paddingAll": "14px",
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "AI Reason", "size": "xs", "color": "#667085", "weight": "bold"},
                    {"type": "text", "text": ai_reason, "size": "sm", "wrap": True, "color": "#111827", "margin": "sm"},
                ],
                "paddingAll": "14px",
            },
        })

    def _build_stock_bubble(self, rec: Dict) -> Dict:
        """
        建構單支股票的 Flex Bubble

        Args:
            rec: 單支推薦結果 dict

        Returns:
            LINE Flex Bubble JSON dict
        """
        return build_decision_bubble(rec)

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
