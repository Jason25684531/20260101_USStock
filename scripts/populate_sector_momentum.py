#!/usr/bin/env python3
"""
填充產業動能數據

用途：在數據庫中生成產業動能記錄，讓前端宏觀頁面能夠顯示產業排行
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

# 添加專案路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "web"))

from dotenv import load_dotenv
load_dotenv(dotenv_path=project_root / ".env")

from sqlalchemy import text
from db import get_engine


# 美股主要產業及其ETF
SECTORS = [
    {'name': 'Technology', 'etf': 'XLK'},
    {'name': 'Healthcare', 'etf': 'XLV'},
    {'name': 'Financials', 'etf': 'XLF'},
    {'name': 'Consumer Discretionary', 'etf': 'XLY'},
    {'name': 'Communication Services', 'etf': 'XLC'},
    {'name': 'Industrials', 'etf': 'XLI'},
    {'name': 'Consumer Staples', 'etf': 'XLP'},
    {'name': 'Energy', 'etf': 'XLE'},
    {'name': 'Utilities', 'etf': 'XLU'},
    {'name': 'Real Estate', 'etf': 'XLRE'},
    {'name': 'Materials', 'etf': 'XLB'},
]


def populate_sector_momentum(engine, days_back=60):
    """填充產業動能數據"""
    print(f"\n📊 填充產業動能數據（最近 {days_back} 天）...")
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days_back)
    
    with engine.begin() as conn:
        # 先檢查現有數據
        result = conn.execute(text("SELECT COUNT(*) FROM sector_momentum"))
        existing_count = result.scalar()
        
        if existing_count > 0:
            print(f"   ℹ️  已有 {existing_count} 筆數據")
            resp = input("   是否清空並重新生成？(y/N): ").strip().lower()
            if resp == 'y':
                conn.execute(text("TRUNCATE TABLE sector_momentum"))
                print("   ✅ 已清空舊數據")
        
        # 生成每日產業動能數據
        rows = []
        current_date = start_date
        
        while current_date <= end_date:
            # 只生成工作日數據
            if current_date.weekday() < 5:  # 週一到週五
                # 為這一天的所有產業生成動能數據並排序
                day_sectors = []
                
                for sector in SECTORS:
                    # 生成模擬的動能數據
                    import random
                    
                    # 20日動能: -10% ~ +20%
                    return_20d = random.uniform(-10, 20)
                    
                    # 63日動能: -15% ~ +25%
                    return_63d = random.uniform(-15, 25)
                    
                    # 252日動能: -20% ~ +40%
                    return_252d = random.uniform(-20, 40)
                    
                    day_sectors.append({
                        'sector': sector['name'],
                        'etf_symbol': sector['etf'],
                        'return_20d': round(return_20d, 4),
                        'return_63d': round(return_63d, 4),
                        'return_252d': round(return_252d, 4)
                    })
                
                # 按20日動能排序並分配排名
                day_sectors.sort(key=lambda x: x['return_20d'], reverse=True)
                
                for rank, sector_data in enumerate(day_sectors, 1):
                    rows.append({
                        'report_date': current_date,
                        'sector': sector_data['sector'],
                        'etf_symbol': sector_data['etf_symbol'],
                        'return_20d': sector_data['return_20d'],
                        'return_63d': sector_data['return_63d'],
                        'return_252d': sector_data['return_252d'],
                        'rank_position': rank
                    })
            
            current_date += timedelta(days=1)
        
        if rows:
            conn.execute(text("""
                INSERT INTO sector_momentum 
                (report_date, sector, etf_symbol, return_20d, return_63d, return_252d, rank_position)
                VALUES 
                (:report_date, :sector, :etf_symbol, :return_20d, :return_63d, :return_252d, :rank_position)
            """), rows)
            
            print(f"   ✅ 成功寫入 {len(rows)} 筆產業動能數據")
            print(f"   產業數: {len(SECTORS)}")
            print(f"   日期範圍: {start_date} → {end_date}")
    
    print("\n✅ 產業動能數據填充完成！")


def main():
    print("=" * 60)
    print(" 🏭 填充產業動能數據")
    print("=" * 60)
    
    engine = get_engine()
    
    try:
        populate_sector_momentum(engine, days_back=60)
        print("\n🎉 宏觀頁面現在應該可以顯示產業動能了！")
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
