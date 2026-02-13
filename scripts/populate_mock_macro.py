#!/usr/bin/env python3
"""
populate_mock_macro.py — FRED 不可用時，填入基線宏觀經濟數據

用途：
    當 FRED API Key 不存在時，在 macro_data 表中寫入 2022-01-01 至今的
    基線宏觀數據（美國利率、失業率、CPI、GDP、10Y-2Y 利差），
    確保 ML 特徵工程不會因宏觀欄位全為 NaN 而失敗。

執行方式：
    python scripts/populate_mock_macro.py
    或在 Docker 中：docker-compose exec strategies python scripts/populate_mock_macro.py
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

# 添加專案路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "strategies" / "src"))

from dotenv import load_dotenv
load_dotenv(dotenv_path=project_root / ".env")

from sqlalchemy import text

from utils.db import get_engine


# =============================================
# 基線宏觀數值（近似 2024 Q4 真實值）
# =============================================
BASELINE_VALUES = {
    "UNRATE": Decimal("4.2"),       # 失業率 %
    "GDP":    Decimal("29352.0"),    # 名目 GDP (十億美元, 近似)
    "DFF":    Decimal("5.33"),       # 聯邦基金利率 %
    "CPIAUCSL": Decimal("315.5"),   # CPI 指數
    "T10Y2Y": Decimal("0.15"),      # 10年-2年利差 %
}

# 月度微調（模擬隨時間自然波動）
MONTHLY_DRIFT = {
    "UNRATE":   Decimal("0.02"),    # 每月微小漂移
    "GDP":      Decimal("50.0"),
    "DFF":      Decimal("-0.02"),
    "CPIAUCSL": Decimal("0.5"),
    "T10Y2Y":   Decimal("0.01"),
}


def populate(engine, start_date: str = "2022-01-01"):
    """
    填入基線宏觀數據，從 start_date 到今天，每月第一個工作日寫一筆。
    使用 INSERT IGNORE 避免重複。
    """
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.now().date()

    rows = []
    current = start
    month_index = 0

    while current <= end:
        for ticker, base_val in BASELINE_VALUES.items():
            drift = MONTHLY_DRIFT.get(ticker, Decimal("0"))
            value = base_val + drift * month_index
            rows.append({
                "date": current,
                "ticker": ticker,
                "value": float(value),
            })
        # 前進一個月
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=1)
        else:
            current = current.replace(month=current.month + 1, day=1)
        month_index += 1

    # 批次寫入
    inserted = 0
    with engine.begin() as conn:
        for row in rows:
            try:
                conn.execute(
                    text("""
                        INSERT IGNORE INTO macro_data (date, ticker, value)
                        VALUES (:date, :ticker, :value)
                    """),
                    row,
                )
                inserted += 1
            except Exception as e:
                print(f"⚠️  跳過 {row['date']} {row['ticker']}: {e}")

    print(f"✅ 已寫入 {inserted} 筆基線宏觀數據 ({start_date} → {end})")
    print(f"   指標: {', '.join(BASELINE_VALUES.keys())}")


def main():
    print("=" * 60)
    print(" 🌐 填入 Mock 宏觀經濟數據")
    print("=" * 60)

    engine = get_engine()

    # 先檢查是否已有資料
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM macro_data"))
        count = result.scalar()

    if count > 0:
        print(f"ℹ️  macro_data 已有 {count} 筆資料")
        resp = input("是否繼續寫入基線數據？(y/N): ").strip().lower()
        if resp != "y":
            print("已取消")
            return

    populate(engine)
    engine.dispose()


if __name__ == "__main__":
    main()
