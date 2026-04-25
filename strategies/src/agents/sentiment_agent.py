from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
from google import genai
from sqlalchemy import create_engine, text

from strategies.src.config import DB_URI, GEMINI_API_KEY, NEWS_LOOKBACK_DAYS


@dataclass
class SentimentResult:
    symbol: str
    score: float
    reason: str
    news_count: int


class SentimentAgent:
    def __init__(self, db_uri: str = DB_URI, lookback_days: int = NEWS_LOOKBACK_DAYS):
        self.engine = create_engine(db_uri)
        self.lookback_days = lookback_days
        self.model_name = "gemini-2.5-flash"
        self.api_key = GEMINI_API_KEY
        self.config_error: str | None = None
        self.client: genai.Client | None = None
        self.quota_exhausted = False

        if not self.api_key:
            self.config_error = "GEMINI_API_KEY missing; fallback to neutral sentiment."
            print(f"[SentimentAgent] {self.config_error}")
        else:
            self.client = genai.Client(api_key=self.api_key)

    def load_news_from_db(self, symbol: str) -> pd.DataFrame:
        cutoff = pd.Timestamp.now().tz_localize(None) - pd.Timedelta(days=self.lookback_days)
        query = text(
            """
            SELECT symbol, date, title, summary, url, provider
            FROM news_cache
            WHERE symbol = :symbol
              AND date >= :cutoff
            ORDER BY date DESC
            """
        )

        try:
            news_df = pd.read_sql(
                query,
                con=self.engine,
                params={"symbol": symbol.upper(), "cutoff": cutoff.to_pydatetime()},
            )
        except Exception as error:
            print(f"⚠️ [{symbol}] 讀取 news_cache 失敗: {error}")
            return pd.DataFrame(columns=["symbol", "date", "title", "summary", "url", "provider"])

        if news_df.empty:
            return news_df

        news_df["date"] = pd.to_datetime(news_df["date"], errors="coerce")
        return news_df.dropna(subset=["date"]).reset_index(drop=True)

    def _safe_result(self, symbol: str, score: float, reason: str, news_count: int) -> dict:
        safe_score = min(max(float(score), 0.0), 1.0)
        safe_reason = str(reason).strip() or "AI 分析失敗"
        if len(safe_reason) > 50:
            safe_reason = safe_reason[:50]
        return SentimentResult(
            symbol=symbol.upper(),
            score=round(safe_score, 4),
            reason=safe_reason,
            news_count=int(news_count),
        ).__dict__

    def _build_news_text(self, news_df: pd.DataFrame) -> str:
        items: list[str] = []
        for row in news_df.head(8).itertuples(index=False):
            published = pd.to_datetime(row.date).strftime("%Y-%m-%d %H:%M")
            title = str(row.title).strip()
            summary = str(row.summary).strip()
            items.append(f"日期: {published}\n標題: {title}\n摘要: {summary or '無摘要'}")
        return "\n\n".join(items)

    def analyze_sentiment(self, symbol: str) -> dict:
        news_df = self.load_news_from_db(symbol)
        if news_df.empty:
            return self._safe_result(symbol, 0.5, "近期無相關新聞", 0)

        if self.config_error:
            return self._safe_result(symbol, 0.5, self.config_error, len(news_df))

        if self.quota_exhausted:
            return self._safe_result(symbol, 0.5, "Gemini quota exhausted", len(news_df))

        prompt = (
            f"你是一位資深的華爾街量化分析師。請閱讀以下關於 {symbol.upper()} 的近期新聞，"
            "並給出一個 0.0 到 1.0 的市場情緒分數。"
            "0.0 代表極度悲觀（重大訴訟、破產、財報爆雷），1.0 代表極度樂觀（財報超預期、重大突破），0.5 代表中性。"
            "請以 JSON 格式回傳，必須包含兩個 key：'score' (浮點數) 與 'reason' (繁體中文，限 50 字內說明原因)。\n\n"
            f"近期新聞如下：\n{self._build_news_text(news_df)}"
        )

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                )
                parsed = json.loads(response.text)

                score = parsed.get("score", 0.5)
                reason = parsed.get("reason", "AI 分析失敗")
                return self._safe_result(symbol, score, reason, len(news_df))
            except Exception as error:
                last_error = error
                error_text = str(error)
                if "429" in error_text and "RESOURCE_EXHAUSTED" in error_text:
                    self.quota_exhausted = True
                    print("[SentimentAgent] Gemini quota exhausted; skip remaining AI reviews in this run.")
                    break
                transient_error = any(token in str(error) for token in ["503", "UNAVAILABLE", "INTERNAL"])
                if transient_error and attempt < 2:
                    continue
                break

        failure = f"AI 分析失敗: {type(last_error).__name__}"
        print(f"[{symbol}] Gemini 分析失敗: {last_error}")
        return self._safe_result(symbol, 0.5, failure, len(news_df))