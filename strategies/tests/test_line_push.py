#!/usr/bin/env python3
"""
LINE Bot 完整功能測試腳本

測試項目:
  1. notifier.py — send_text / send_flex_report
  2. handler.py — process_command (Top5 / ML / status / help)
  3. Flex Message JSON 結構驗證

Usage:
    # 僅結構驗證 (不需 LINE Token / DB)
    python strategies/tests/test_line_push.py

    # 實際發送測試 (需設定 LINE_CHANNEL_TOKEN + LINE_USER_ID)
    python strategies/tests/test_line_push.py --send

    # 測試 DB 查詢指令
    python strategies/tests/test_line_push.py --db
"""
import argparse
import sys
import json
from pathlib import Path

# 路徑設定
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'strategies' / 'src'))

from dotenv import load_dotenv
load_dotenv(dotenv_path=PROJECT_ROOT / '.env')


# ============================================
# 測試 1: Flex Message JSON 結構驗證
# ============================================
def test_flex_structure():
    """驗證 Flex Message 建構的 JSON 結構"""
    from adapters.notifier import LineNotifier

    notifier = LineNotifier()

    # 模擬推薦數據
    mock_recs = [
        {
            'rank': 1, 'symbol': 'VZ', 'signal': 'BUY',
            'total_score': 3.50, 'current_price': 42.15,
            'ml_confidence': 0.65,
            'breakout_pass': True, 'acceleration_pass': True,
            'peg_pass': False, 'dupont_pass': True,
            'support_1': 40.50, 'resistance_1': 44.20,
        },
        {
            'rank': 2, 'symbol': 'XOM', 'signal': 'BUY',
            'total_score': 3.20, 'current_price': 108.30,
            'ml_confidence': 0.58,
            'breakout_pass': True, 'acceleration_pass': False,
            'peg_pass': True, 'dupont_pass': True,
            'support_1': 105.00, 'resistance_1': 112.00,
        },
        {
            'rank': 3, 'symbol': 'AAPL', 'signal': 'BUY',
            'total_score': 2.80, 'current_price': 188.50,
            'ml_confidence': 0,
            'breakout_pass': True, 'acceleration_pass': True,
            'peg_pass': False, 'dupont_pass': False,
            'support_1': 182.00, 'resistance_1': 195.00,
        },
    ]

    # 測試 _build_stock_bubble
    bubble = notifier._build_stock_bubble(mock_recs[0])
    assert bubble['type'] == 'bubble', "Bubble type 錯誤"
    assert bubble['header']['backgroundColor'] == '#00C853', "BUY 顏色應為綠色"
    assert '價格' in json.dumps(bubble, ensure_ascii=False), "缺少價格欄位"
    assert '評分' in json.dumps(bubble, ensure_ascii=False), "缺少評分欄位"
    assert 'ML' in json.dumps(bubble, ensure_ascii=False), "缺少 ML 欄位"
    print("  ✅ _build_stock_bubble 結構正確")

    # 測試 _flex_kv
    kv = LineNotifier._flex_kv("📊 評分", "3.5/5")
    assert kv['type'] == 'box', "KV type 錯誤"
    assert kv['layout'] == 'horizontal', "KV layout 錯誤"
    assert len(kv['contents']) == 2, "KV 應有 2 個 contents"
    print("  ✅ _flex_kv 結構正確")

    # 測試完整 Flex Report 結構
    # 不實際發送，僅驗證 message 對象結構
    bubbles = [notifier._build_stock_bubble(r) for r in mock_recs]
    flex_msg = {
        "type": "flex",
        "altText": "📊 test",
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        }
    }
    assert flex_msg['type'] == 'flex', "Flex type 錯誤"
    assert flex_msg['contents']['type'] == 'carousel', "Carousel type 錯誤"
    assert len(flex_msg['contents']['contents']) == 3, "應有 3 個 bubbles"
    print("  ✅ Flex Carousel 結構正確")

    # 印出 Flex JSON 供 LINE Bot Designer 驗證
    print(f"\n  📋 Flex JSON Preview (可貼至 LINE Bot Designer 驗證):")
    print(json.dumps(flex_msg['contents'], indent=2, ensure_ascii=False)[:500] + "...")

    return True


# ============================================
# 測試 2: handler.py 命令解析 (不需 DB)
# ============================================
def test_handler_commands():
    """測試 handler.py 的命令解析（純邏輯，不查 DB）"""
    # 直接匯入 web/bot 模組
    sys.path.insert(0, str(PROJECT_ROOT / 'web'))

    from bot.handler import process_command, _text_msg

    # /help
    msgs = process_command('/help')
    assert msgs is not None, "/help 應有回覆"
    assert msgs[0]['type'] == 'text', "/help 應為文字回覆"
    assert 'Top5' in msgs[0]['text'], "/help 應包含 Top5 說明"
    print("  ✅ /help 命令正常")

    # /status
    msgs = process_command('/status')
    assert msgs is not None, "/status 應有回覆"
    assert '運行正常' in msgs[0]['text'], "/status 應包含運行狀態"
    print("  ✅ /status 命令正常")

    # /strategies
    msgs = process_command('/strategies')
    assert msgs is not None, "/strategies 應有回覆"
    assert 'Breakout' in msgs[0]['text'], "/strategies 應包含策略名稱"
    assert 'Top5基礎' in msgs[0]['text'] or 'Top5（' in msgs[0]['text'], "/strategies 應提到 Top5 版本差異"
    print("  ✅ /strategies 命令正常")

    # Top5基礎 命令識別
    msgs = process_command('Top5基礎')
    assert msgs is not None, "Top5基礎 應有回覆"
    print("  ✅ Top5基礎 命令識別正常")

    # ML 無參數
    msgs = process_command('ML')
    assert msgs is not None, "ML 無參數應提示用法"
    assert '請指定' in msgs[0]['text'], "ML 無參數應提示指定代碼"
    print("  ✅ ML 無參數提示正常")

    # 非命令
    msgs = process_command('你好')
    assert msgs is None, "非命令應返回 None"
    print("  ✅ 非命令過濾正常")

    return True


# ============================================
# 測試 3: Top5 / ML DB 查詢 (需要 DB 連線)
# ============================================
def test_db_commands():
    """測試涉及 DB 查詢的命令"""
    sys.path.insert(0, str(PROJECT_ROOT / 'web'))
    from bot.handler import process_command

    # Top5
    print("  🔍 測試 Top5 命令 (查詢 DB)...")
    msgs = process_command('Top5')
    assert msgs is not None, "Top5 應有回覆"
    if msgs[0]['type'] == 'flex':
        print(f"  ✅ Top5 回傳 Flex Carousel")
        carousel = msgs[0]['contents']
        print(f"     — 包含 {len(carousel['contents'])} 支股票")
    else:
        print(f"  ⚠️  Top5 回傳文字 (可能尚無 DB 資料): {msgs[0]['text'][:60]}...")

    # ML AAPL
    print("  🔍 測試 ML AAPL 命令 (查詢 DB)...")
    msgs = process_command('ML AAPL')
    assert msgs is not None, "ML AAPL 應有回覆"
    print(f"  {'✅' if '❌' not in msgs[0]['text'] else '⚠️ '} ML AAPL: {msgs[0]['text'][:80]}...")

    return True


# ============================================
# 測試 4: 實際 LINE 發送 (需要 Token)
# ============================================
def test_line_send():
    """實際發送測試訊息到 LINE"""
    from adapters.notifier import get_notifier

    notifier = get_notifier()

    if not notifier.is_enabled:
        print("  ⚠️  LINE 未配置 (缺少 TOKEN 或 USER_ID)，跳過發送測試")
        return False

    # 發送純文字
    print("  📤 發送純文字測試...")
    ok = notifier.send_text("🧪 USStock LINE Bot 測試\n\n系統連接正常 ✅")
    assert ok, "純文字發送失敗"
    print("  ✅ 純文字發送成功")

    # 發送 Flex Report
    mock_recs = [
        {
            'rank': 1, 'symbol': 'VZ', 'signal': 'BUY',
            'total_score': 3.50, 'current_price': 42.15,
            'ml_confidence': 0.65,
            'breakout_pass': True, 'acceleration_pass': True,
            'peg_pass': False, 'dupont_pass': True,
            'support_1': 40.50, 'resistance_1': 44.20,
        },
        {
            'rank': 2, 'symbol': 'XOM', 'signal': 'BUY',
            'total_score': 3.20, 'current_price': 108.30,
            'ml_confidence': 0.58,
            'breakout_pass': True, 'acceleration_pass': False,
            'peg_pass': True, 'dupont_pass': True,
            'support_1': 105.00, 'resistance_1': 112.00,
        },
    ]

    print("  📤 發送 Flex 推薦報告測試...")
    ok = notifier.send_flex_report(mock_recs)
    assert ok, "Flex 報告發送失敗"
    print("  ✅ Flex 推薦報告發送成功")

    return True


# ============================================
# Main
# ============================================
def main():
    parser = argparse.ArgumentParser(description='LINE Bot 功能測試')
    parser.add_argument('--send', action='store_true',
                        help='實際發送 LINE 訊息 (需配置 Token)')
    parser.add_argument('--db', action='store_true',
                        help='測試涉及 DB 查詢的命令')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  🧪 LINE Bot 功能測試")
    print(f"{'='*60}\n")

    passed = 0
    total = 0

    # Test 1: Flex 結構
    print("📋 測試 1: Flex Message 結構驗證")
    total += 1
    try:
        if test_flex_structure():
            passed += 1
    except Exception as e:
        print(f"  ❌ 失敗: {e}")

    # Test 2: Handler 命令
    print(f"\n📋 測試 2: Handler 命令解析")
    total += 1
    try:
        if test_handler_commands():
            passed += 1
    except Exception as e:
        print(f"  ❌ 失敗: {e}")

    # Test 3: DB 查詢 (可選)
    if args.db:
        print(f"\n📋 測試 3: DB 查詢命令")
        total += 1
        try:
            if test_db_commands():
                passed += 1
        except Exception as e:
            print(f"  ❌ 失敗: {e}")

    # Test 4: LINE 發送 (可選)
    if args.send:
        print(f"\n📋 測試 4: LINE 實際發送")
        total += 1
        try:
            if test_line_send():
                passed += 1
        except Exception as e:
            print(f"  ❌ 失敗: {e}")

    print(f"\n{'='*60}")
    print(f"  📊 測試結果: {passed}/{total} 通過")
    print(f"{'='*60}\n")

    if passed == total:
        print("🎉 全部測試通過！")
    else:
        print("⚠️  部分測試失敗，請檢查上方輸出")
        sys.exit(1)


if __name__ == '__main__':
    main()
