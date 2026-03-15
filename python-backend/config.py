"""
Configuration for Angel One SmartAPI Algo Trading System.
All user-configurable parameters in one place.
"""

# ── Angel One Credentials ──────────────────────────
API_KEY = "S3O15gz8"
CLIENT_ID = "P145829"
MPIN = "8090"
TOTP_SECRET = "EO6SMVC24MSXELYPRCI5KYW5DA"  # Base32 secret from Angel One for pyotp

# ── Supported Indexes ──────────────────────────────
INDEXES = {
    "NIFTY": {"token": "99926000", "exchange": "NSE", "strike_interval": 50},
    "BANKNIFTY": {"token": "99926009", "exchange": "NSE", "strike_interval": 100},
    "FINNIFTY": {"token": "99926037", "exchange": "NSE", "strike_interval": 50},
    "MIDCPNIFTY": {"token": "99926074", "exchange": "NSE", "strike_interval": 50},
    "SENSEX": {"token": "99919000", "exchange": "BSE", "strike_interval": 100},
}

# ── Strategy Parameters ───────────────────────────
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_CALL_THRESHOLD = 55
RSI_PUT_THRESHOLD = 45
RSI_STRONG_BULL = 65
RSI_STRONG_BEAR = 35
VOLUME_LOOKBACK = 5

# ── Risk Parameters ──────────────────────────────
TARGET_POINTS = 20
STOPLOSS_POINTS = 12
TRAILING_TRIGGER = 15  # After this profit, move SL to cost
MAX_TRADES_PER_DAY = 3
MAX_CONSECUTIVE_LOSSES = 2
DEFAULT_MAX_DAILY_LOSS = 5000  # INR
RISK_PER_TRADE_PCT = 2  # % of capital

# ── Time Filters ─────────────────────────────────
NO_TRADE_WINDOWS = [
    ("09:15", "09:20"),
    ("12:00", "13:00"),
]
AUTO_SQUARE_OFF_TIME = "15:15"

# ── Order Defaults ───────────────────────────────
ORDER_TYPE = "MARKET"
PRODUCT_TYPE = "INTRADAY"
LOT_SIZE = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 50,
    "SENSEX": 10,
}

# ── Brokerage & Charges ─────────────────────────
BROKERAGE_PER_ORDER = 20  # INR flat
STT_PCT = 0.0625  # % on sell side
GST_PCT = 18  # % on brokerage
SEBI_CHARGES = 0.0001  # %
STAMP_DUTY = 0.003  # % on buy side
ESTIMATED_SLIPPAGE_POINTS = 1

# ── Liquidity Filter ────────────────────────────
MIN_OPTION_VOLUME = 1000
MAX_BID_ASK_SPREAD = 3.0  # INR
