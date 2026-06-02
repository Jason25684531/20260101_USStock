from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategies.src.adapters.institutional_activity import (
    DEFAULT_ACTIVITY_SYMBOLS,
    fetch_and_store_institutional_activity,
)


def main() -> int:
    parser = argparse.ArgumentParser(description='Ingest US institutional / mutual fund / insider activity snapshots')
    parser.add_argument('--symbols', type=str, default=None, help='逗號分隔股票代碼；未指定則使用 UNIVERSE + SPY')
    parser.add_argument('--sleep', type=float, default=0.5, help='每檔之間等待秒數')
    args = parser.parse_args()

    if args.symbols:
        symbols = [symbol.strip().upper() for symbol in args.symbols.split(',') if symbol.strip()]
    else:
        symbols = list(DEFAULT_ACTIVITY_SYMBOLS)

    print('🚀 啟動美股主力籌碼快照更新...')
    print(f'   股票池: {len(symbols)} 檔')

    success = 0
    for index, symbol in enumerate(symbols):
        try:
            snapshot = fetch_and_store_institutional_activity(symbol)
            if snapshot:
                success += 1
                print(
                    f"✅ {symbol}: 機構={snapshot.get('institution_total_shares')} | "
                    f"基金={snapshot.get('mutualfund_total_shares')} | 內部人近6M={snapshot.get('insider_net_shares_6m')}"
                )
            else:
                print(f'⚠️ {symbol}: 無可寫入的主力籌碼快照')
        except Exception as error:
            print(f'❌ {symbol}: 主力籌碼快照更新失敗 - {error}')

        if index < len(symbols) - 1 and args.sleep > 0:
            time.sleep(args.sleep)

    print(f'🎉 完成: {success}/{len(symbols)} 檔成功寫入')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())