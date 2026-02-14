"""
宏觀環境與產業分散測試
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path('strategies/src')))

from strategies.macro_filter import classify_macro_regime, get_regime_strategy_filter
from strategies.sector import apply_sector_constraint, get_sector

print("=" * 60)
print("📈 宏觀環境分類測試")
print("=" * 60)

# 模擬三種市場環境
scenarios = [
    {'vix': 15, 'yield_curve': 0.5, 'unemployment_rate': 3.5, 'label': '風險偏好（看漲）'},
    {'vix': 25, 'yield_curve': 0.1, 'unemployment_rate': 5.0, 'label': '中立'},
    {'vix': 35, 'yield_curve': -0.5, 'unemployment_rate': 7.0, 'label': '風險厭惡（看空）'},
]

for scenario in scenarios:
    label = scenario.pop('label')
    regime, desc = classify_macro_regime(**scenario)
    
    filter_info = get_regime_strategy_filter(regime)
    
    print(f'\n{label}:')
    print(f'  環境: {regime.name}')
    print(f'  描述: {desc}')
    print(f'  啟用分類: {filter_info["enabled_categories"]}')
    print(f'  最大持倉: {filter_info["max_positions"]}')

print("\n" + "=" * 60)
print("🏢 產業分散約束測試")
print("=" * 60)

# 模擬推薦列表
recommendations = [
    {'symbol': 'AAPL', 'total_score': 5.0},
    {'symbol': 'MSFT', 'total_score': 4.5},
    {'symbol': 'NVDA', 'total_score': 4.2},
    {'symbol': 'JPM', 'total_score': 3.8},
    {'symbol': 'JNJ', 'total_score': 3.6},
    {'symbol': 'AMZN', 'total_score': 3.5},
    {'symbol': 'V', 'total_score': 3.2},
]

print("\n原始推薦列表（按評分排序）:")
for rec in recommendations:
    symbol = rec['symbol']
    sector = get_sector(symbol)
    print(f"  {symbol:6s} ({sector:15s}) → 評分 {rec['total_score']:.1f}")

# 套用產業分散約束
result = apply_sector_constraint(recommendations, max_per_sector=2, total_n=5)

print("\n經過產業分散約束後（每產業最多2支，推薦前5名）:")
for rec in result:
    symbol = rec['symbol']
    sector = get_sector(symbol)
    print(f"  {symbol:6s} ({sector:15s}) → 評分 {rec['total_score']:.1f}")

print(f"\n✅ 最終推薦數量: {len(result)}")
