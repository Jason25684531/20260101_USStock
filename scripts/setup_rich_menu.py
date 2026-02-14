"""
LINE Bot Rich Menu 自動設定腳本

建立 6 格 Rich Menu (2×3)，對應主要命令：
  Top5 | /stock | /market
  /sector | /history | /help

使用方式:
  python scripts/setup_rich_menu.py

需要環境變數:
  LINE_CHANNEL_TOKEN=your_token
"""

import os
import sys
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))
try:
    from security import get_secret
    TOKEN = get_secret('line_channel_token', '')
except ImportError:
    TOKEN = os.getenv('LINE_CHANNEL_TOKEN', '')

if not TOKEN:
    print("❌ 需要 LINE_CHANNEL_TOKEN 環境變數")
    sys.exit(1)

API = "https://api.line.me/v2/bot"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


def create_rich_menu():
    """建立 Rich Menu 物件"""
    menu = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "美股量化系統",
        "chatBarText": "📈 功能選單",
        "areas": [
            # Row 1
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "Top5"},
            },
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {"type": "message", "text": "/stock AAPL"},
            },
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "/market"},
            },
            # Row 2
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {"type": "message", "text": "/sector"},
            },
            {
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                "action": {"type": "message", "text": "/history"},
            },
            {
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                "action": {"type": "message", "text": "/help"},
            },
        ],
    }

    resp = requests.post(f"{API}/richmenu", headers=HEADERS, json=menu)
    if resp.status_code != 200:
        print(f"❌ 建立 Rich Menu 失敗: {resp.status_code} {resp.text}")
        return None
    rich_menu_id = resp.json().get("richMenuId")
    print(f"✅ Rich Menu 建立成功: {rich_menu_id}")
    return rich_menu_id


def upload_image(rich_menu_id: str, image_path: str):
    """上傳 Rich Menu 圖片"""
    if not os.path.exists(image_path):
        print(f"⚠️  圖片不存在: {image_path}")
        print("   請製作 2500×1686 PNG 圖片放到該路徑後重新執行")
        return False

    with open(image_path, 'rb') as f:
        resp = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "image/png",
            },
            data=f,
        )
    if resp.status_code == 200:
        print("✅ 圖片上傳成功")
        return True
    else:
        print(f"❌ 圖片上傳失敗: {resp.status_code} {resp.text}")
        return False


def set_default(rich_menu_id: str):
    """設定為預設 Rich Menu"""
    resp = requests.post(
        f"{API}/user/all/richmenu/{rich_menu_id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if resp.status_code == 200:
        print("✅ 已設為預設 Rich Menu")
    else:
        print(f"❌ 設定預設失敗: {resp.status_code} {resp.text}")


def main():
    print("🚀 LINE Bot Rich Menu 設定")
    print("=" * 40)

    # 1) Create
    rm_id = create_rich_menu()
    if not rm_id:
        return

    # 2) Upload image (optional)
    img_path = os.path.join(os.path.dirname(__file__), '..', 'web', 'static', 'rich_menu.png')
    if os.path.exists(img_path):
        upload_image(rm_id, img_path)
    else:
        print(f"⚠️  跳過圖片上傳（請製作 2500×1686 PNG: {img_path}）")
        print("   圖片佈局:")
        print("   ┌──────────┬──────────┬──────────┐")
        print("   │  🏆 Top5 │ 🔍 個股  │ 🌍 宏觀  │")
        print("   ├──────────┼──────────┼──────────┤")
        print("   │ 🏭 產業  │ 📅 歷史  │ ❓ 幫助  │")
        print("   └──────────┴──────────┴──────────┘")

    # 3) Set default
    set_default(rm_id)

    print("\n✅ Rich Menu 設定完成!")
    print(f"   ID: {rm_id}")


if __name__ == '__main__':
    main()
