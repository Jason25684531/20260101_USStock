"""
部位控管與風險管理測試
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path('strategies/src')))

from core.position_sizing import calc_atr_position_size, calc_equal_risk_weights
from core.risk_manager import RiskManager
from datetime import date

print("=" * 60)
print("💰 ATR 部位規模計算")
print("=" * 60)

# 場景：ATR=2.5, 現價=$150, 總資金=$100k, 風險=2%
shares = calc_atr_position_size(
    atr=2.5,
    current_price=150.0,
    total_equity=100_000,
    risk_per_trade=0.02
)

position_value = shares * 150
weight = position_value / 100_000

print(f'\n輸入參數:')
print(f'  ATR: $2.5')
print(f'  現價: $150')
print(f'  總資金: $100,000')
print(f'  風險比例: 2%')
print(f'\n計算結果:')
print(f'  建議持股數: {shares:.0f} 股')
print(f'  部位金額: ${position_value:,.0f}')
print(f'  資金佔比: {weight*100:.1f}% {"✅" if weight <= 0.20 else "❌"} (上限20%)')

print("\n" + "=" * 60)
print("🛡️ 風險管理測試")
print("=" * 60)

rm = RiskManager()

# 建立部位
rm.add_position('AAPL', entry_price=150, entry_date=date(2026, 1, 1), atr=3.0)
print(f'\n📍 進場: AAPL @ $150 (ATR=$3.0, Trailing Stop: 3×ATR=$9)')

# 情景1: 價格上漲至 $160
results = rm.check_all({'AAPL': 160}, {'AAPL': 3.0}, date(2026, 1, 10))
should_exit, reason = results['AAPL']
print(f'\n情景1: 價格上漲至 $160 (+6.7%)')
print(f'  止損觸發: {"❌ 是" if should_exit else "✅ 否"}')
if reason:
    print(f'  原因: {reason}')

# 情景2: 價格跌至 $140（接近止損）
results = rm.check_all({'AAPL': 140}, {'AAPL': 3.0}, date(2026, 1, 15))
should_exit, reason = results['AAPL']
print(f'\n情景2: 價格跌至 $140 (-6.7%)')
print(f'  止損觸發: {"❌ 是" if should_exit else "✅ 否"}')
if reason:
    print(f'  原因: {reason}')

# 情景3: 持有超過30天且虧損
results = rm.check_all({'AAPL': 148}, {'AAPL': 3.0}, date(2026, 2, 10))
should_exit, reason = results['AAPL']
hold_days = (date(2026, 2, 10) - date(2026, 1, 1)).days
print(f'\n情景3: 持有 {hold_days} 天，價格 $148 (-1.3%)')
print(f'  止損觸發: {"❌ 是" if should_exit else "✅ 否"}')
if reason:
    print(f'  原因: {reason}')

print("\n✅ 所有測試完成")
