from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategies.src.agents.sentiment_agent import SentimentAgent
from strategies.src.config import UNIVERSE_TICKERS


def main() -> int:
    agent = SentimentAgent()
    print("開始執行 Phase 3.5 Gemini Sentiment Agent Dry-Run...")

    for symbol in UNIVERSE_TICKERS:
        result = agent.analyze_sentiment(symbol)
        print(
            f"[{result['symbol']}] score={result['score']:.4f} | news_count={result['news_count']} | reason={result['reason']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())