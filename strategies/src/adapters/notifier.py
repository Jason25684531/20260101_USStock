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
import requests
from datetime import datetime, date
from typing import Optional, Dict, List

import pandas as pd

try:
    from utils.security import get_secret
except ImportError:
    from strategies.src.utils.security import get_secret


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

    # ===========================================================
    # Flex Message 每日推薦報告
    # ===========================================================

    def send_flex_report(self, recommendations: List[Dict]) -> bool:
        """
        發送 Flex Message 格式的每日選股推薦報告

        Args:
            recommendations: get_top_recommendations() 的結果列表
                每個 dict 需包含: rank, symbol, signal, total_score,
                current_price, ml_confidence, support_1, resistance_1,
                breakout_pass, acceleration_pass, peg_pass, dupont_pass

        Returns:
            是否發送成功
        """
        if not recommendations:
            return self.send_text("📊 今日無推薦標的")

        bubbles = [self._build_stock_bubble(rec) for rec in recommendations[:10]]

        scan_date = date.today().strftime('%Y/%m/%d')
        flex_message = {
            "type": "flex",
            "altText": f"📊 每日選股推薦 Top {len(recommendations)} — {scan_date}",
            "contents": {
                "type": "carousel",
                "contents": bubbles,
            }
        }

        return self._send_message([flex_message])

    def build_daily_screener_flex(self, top_n_df: pd.DataFrame) -> Dict:
        """將 ml_strategy 的 Top N DataFrame 轉為每日情報 Flex Carousel。"""
        if top_n_df is None or top_n_df.empty:
            return {
                "type": "flex",
                "altText": "📊 今日無推薦標的",
                "contents": {
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [{"type": "text", "text": "今日無推薦標的", "weight": "bold"}],
                    },
                },
            }

        bubbles = [self._build_daily_screener_bubble(record) for record in top_n_df.to_dict(orient="records")[:5]]
        latest_date = str(top_n_df["latest_date"].iloc[0]) if "latest_date" in top_n_df.columns else date.today().isoformat()
        return {
            "type": "flex",
            "altText": f"📊 每日情報 Top {len(bubbles)} — {latest_date}",
            "contents": {
                "type": "carousel",
                "contents": bubbles,
            },
        }

    def send_daily_screener_flex(self, top_n_df: pd.DataFrame) -> bool:
        """推送每日量化 screener 結果；未配置 token 時以 dry-run 成功結束。"""
        flex_message = self.build_daily_screener_flex(top_n_df)
        if not self.is_enabled:
            preview = json.dumps(flex_message["contents"], ensure_ascii=False)[:400]
            print("⚠️  Line Token/User ID 未配置，Dry-run 成功，Flex payload 預覽如下:")
            print(preview)
            return True

        return self._send_message([flex_message])

    def _build_daily_screener_bubble(self, rec: Dict) -> Dict:
        valuation_status = str(rec.get("valuation_status") or "FAIR").upper()
        status_label_map = {
            "UNDERVALUED": ("🟢 便宜 / UNDERVALUED", "#0B6E4F"),
            "FAIR": ("🟡 合理 / FAIR", "#A16207"),
            "OVERVALUED": ("🔴 偏貴 / OVERVALUED", "#B42318"),
        }
        status_text, header_color = status_label_map.get(valuation_status, status_label_map["FAIR"])

        xgboost_score = rec.get("xgboost_score")
        buy_price = rec.get("buy_price")
        suggested_allocation_pct = rec.get("suggested_allocation_pct")
        ai_reason = str(rec.get("ai_reason") or "未提供 AI 摘要")[:60]

        body_rows = [
            self._flex_kv("AI 勝率", f"{float(xgboost_score):.2f}" if xgboost_score is not None else "N/A"),
            self._flex_kv("建議買入價", f"< ${float(buy_price):.2f}" if buy_price is not None else "N/A"),
            self._flex_kv("建議資金佔比", f"{float(suggested_allocation_pct):.1f}%" if suggested_allocation_pct is not None else "N/A"),
        ]

        return {
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
                    {"type": "text", "text": "AI 理由", "size": "xs", "color": "#667085", "weight": "bold"},
                    {"type": "text", "text": ai_reason, "size": "sm", "wrap": True, "color": "#111827", "margin": "sm"},
                ],
                "paddingAll": "14px",
            },
        }

    def _build_stock_bubble(self, rec: Dict) -> Dict:
        """
        建構單支股票的 Flex Bubble

        Args:
            rec: 單支推薦結果 dict

        Returns:
            LINE Flex Bubble JSON dict
        """
        signal = rec.get('signal', 'N/A')
        signal_color = "#00C853" if signal == 'BUY' else "#FF1744"
        ml_conf = rec.get('ml_confidence', 0) or 0
        ml_str = f"{ml_conf:.0%}" if ml_conf > 0 else "—"

        # 策略通過指標
        strats = []
        if rec.get('breakout_pass'):
            strats.append("突破")
        if rec.get('acceleration_pass'):
            strats.append("加速")
        if rec.get('peg_pass'):
            strats.append("PEG")
        if rec.get('dupont_pass'):
            strats.append("杜邦")

        body_rows = [
            self._flex_kv("💰 價格", f"${rec['current_price']:.2f}"),
            self._flex_kv("📊 評分", f"{rec['total_score']:.1f}/5"),
            self._flex_kv("🤖 ML 信心度", ml_str),
            self._flex_kv("✅ 策略", " | ".join(strats) if strats else "—"),
        ]

        s1 = rec.get('support_1')
        r1 = rec.get('resistance_1')
        if s1:
            body_rows.append(self._flex_kv("📉 支撐", f"${s1:.2f}"))
        if r1:
            body_rows.append(self._flex_kv("📈 壓力", f"${r1:.2f}"))

        return {
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": f"#{rec.get('rank', '?')} {rec['symbol']}",
                        "weight": "bold",
                        "size": "lg",
                        "color": "#FFFFFF",
                    },
                    {
                        "type": "text",
                        "text": signal,
                        "weight": "bold",
                        "size": "sm",
                        "align": "end",
                        "color": "#FFFFFF",
                    },
                ],
                "backgroundColor": signal_color,
                "paddingAll": "15px",
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": body_rows,
                "spacing": "sm",
                "paddingAll": "13px",
            },
        }

    @staticmethod
    def _flex_kv(label: str, value: str) -> Dict:
        """
        建構 Flex Message 鍵值對行

        Args:
            label: 左側標籤
            value: 右側數值

        Returns:
            LINE Flex Box JSON dict
        """
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#555555", "flex": 0},
                {"type": "text", "text": value, "size": "sm", "color": "#111111", "align": "end"},
            ],
        }


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
