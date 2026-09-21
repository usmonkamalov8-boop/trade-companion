import os
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

API_TOKEN = os.getenv("API_TOKEN", "")
BINANCE_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_API_SECRET", "")
BOT_SERVICE = os.getenv("BOT_SERVICE", "crypto_bot")
CONTROL_FILE = Path(os.getenv("CONTROL_FILE", str(BASE / "control.json")))

# The 8 pairs the bot trades (Binance USDT-M futures)
CRYPTO = ["BTC", "ETH", "SOL", "RENDER", "INJ", "FET", "NEAR", "AVAX"]
PAIRS = [s + "USDT" for s in CRYPTO]

# name -> (Yahoo Finance symbol, price decimals)
FOREX = {
    "EURUSD": ("EURUSD=X", 5),
    "GBPUSD": ("GBPUSD=X", 5),
    "USDJPY": ("JPY=X", 3),
    "USDCHF": ("CHF=X", 5),
    "AUDUSD": ("AUDUSD=X", 5),
    "USDCAD": ("CAD=X", 5),
    "NZDUSD": ("NZDUSD=X", 5),
    "XAUUSD": ("GC=F", 2),
    "DXY": ("DX-Y.NYB", 3),
}

LABELS = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "RENDER": "Render",
    "INJ": "Injective", "FET": "Fetch.ai", "NEAR": "NEAR", "AVAX": "Avalanche",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "USDCHF": "USD/CHF", "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD",
    "NZDUSD": "NZD/USD", "XAUUSD": "Gold XAU/USD", "DXY": "US Dollar Index",
}

# Pairs where USD is the QUOTE currency (they fall when USD strengthens)
USD_QUOTE = {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"}
# Pairs where USD is the BASE currency (they rise when USD strengthens)
USD_BASE = {"USDJPY", "USDCHF", "USDCAD"}

# Free RSS feeds. Edit freely; a dead feed is skipped automatically.
FEEDS = {
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed",
    ],
    "forex": [
        "https://www.fxstreet.com/rss/news",
        "https://www.investing.com/rss/news_1.rss",
        "https://www.investing.com/rss/news_11.rss",
    ],
}


# --- extra scanner assets (step 10): the bot still only trades what it is configured to trade
for _n in ("OP", "XRP", "TRX", "DOGE"):
    if _n not in CRYPTO:
        CRYPTO.append(_n)
PAIRS = [_s + "USDT" for _s in CRYPTO]
LABELS.update({"OP": "Optimism", "XRP": "XRP", "TRX": "Tron", "DOGE": "Dogecoin"})
