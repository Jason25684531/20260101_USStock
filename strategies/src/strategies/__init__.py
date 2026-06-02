"""Strategies package — 含 Registry 自動註冊機制"""
from .registry import (
    BaseScreenStrategy,
    get_all_strategies,
    get_strategies_by_category,
    evaluate_all_strategies,
    calc_composite_score,
)
from .momentum import (
    run_momentum_strategy,
    run_multi_symbol_momentum,
    screen_breakout,
    screen_acceleration,
    BreakoutStrategy,
    AccelerationStrategy,
)
from .value import run_value_strategy, run_multi_symbol_value
from .fundamental import (
    calculate_valuation_targets,
    screen_peg,
    screen_dupont,
    PEGStrategy,
    DuPontStrategy,
)
from .institutional import screen_institutional, InstitutionalStrategy
from .volume_analysis import (
    screen_volume_structure,
    screen_money_flow,
    VolumeStructureStrategy,
    MoneyFlowStrategy,
)
from .enhanced_momentum import (
    screen_multi_tf_momentum,
    screen_relative_strength,
    MultiTFMomentumStrategy,
    RelativeStrengthStrategy,
)
from .earnings_quality import screen_earnings_quality, EarningsQualityStrategy
from .sector import (
    screen_sector_rotation,
    apply_sector_constraint,
    get_sector,
    SECTOR_MAP,
    SectorRotationStrategy,
)
from .macro_filter import (
    MacroRegime,
    BULL_MARKET,
    BEAR_MARKET,
    classify_macro_regime,
    get_market_regime,
    get_regime_strategy_filter,
)

__all__ = [
    # Registry
    'BaseScreenStrategy', 'get_all_strategies', 'get_strategies_by_category',
    'evaluate_all_strategies', 'calc_composite_score',
    # Legacy
    'run_momentum_strategy', 'run_multi_symbol_momentum',
    'run_value_strategy', 'run_multi_symbol_value',
    'screen_breakout', 'screen_acceleration', 'calculate_valuation_targets', 'screen_peg', 'screen_dupont',
    # New strategies
    'screen_institutional', 'screen_volume_structure', 'screen_money_flow',
    'screen_multi_tf_momentum', 'screen_relative_strength',
    'screen_earnings_quality', 'screen_sector_rotation',
    'apply_sector_constraint', 'get_sector', 'SECTOR_MAP',
    'MacroRegime', 'BULL_MARKET', 'BEAR_MARKET', 'classify_macro_regime', 'get_market_regime', 'get_regime_strategy_filter',
]
