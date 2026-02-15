"""
Web 服務共用常量

集中管理 web/ 內部共用的常量，避免 app.py 和 bot/handler.py 之間重複定義。

注意: strategies/ 和 web/ 是獨立的 Docker 服務，
      strategies/src/strategies/sector.py 中有完整的 SECTOR_MAP。
      此處為 web 端的 fallback 副本。
"""

# 股票 → 產業 映射（用於 DB 無 sector 欄位時的 fallback）
# 完整版見 strategies/src/strategies/sector.py::SECTOR_MAP
SECTOR_MAP_FALLBACK = {
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'AMD': 'Technology',
    'AVGO': 'Technology', 'CRM': 'Technology', 'ADBE': 'Technology', 'ACN': 'Technology',
    'CSCO': 'Technology', 'INTC': 'Technology', 'INTU': 'Technology', 'QCOM': 'Technology',
    'IBM': 'Technology', 'TXN': 'Technology',
    'GOOGL': 'Communication', 'META': 'Communication', 'NFLX': 'Communication',
    'DIS': 'Communication', 'CMCSA': 'Communication', 'VZ': 'Communication',
    'AMZN': 'Consumer Discretionary', 'TSLA': 'Consumer Discretionary',
    'HD': 'Consumer Discretionary', 'MCD': 'Consumer Discretionary', 'COST': 'Consumer Discretionary',
    'PG': 'Consumer Staples', 'KO': 'Consumer Staples', 'PEP': 'Consumer Staples', 'WMT': 'Consumer Staples',
    'BRK-B': 'Financials', 'JPM': 'Financials', 'V': 'Financials',
    'MA': 'Financials', 'BAC': 'Financials', 'WFC': 'Financials',
    'LLY': 'Health Care', 'UNH': 'Health Care', 'JNJ': 'Health Care',
    'MRK': 'Health Care', 'ABBV': 'Health Care', 'TMO': 'Health Care',
    'ABT': 'Health Care', 'AMGN': 'Health Care', 'PFE': 'Health Care',
    'XOM': 'Energy', 'CVX': 'Energy',
    'LIN': 'Materials', 'HON': 'Industrials',
}
