"""
Utility functions: logging, time checks, formatting.
"""

from datetime import datetime, time
from loguru import logger
import config

logger.add("logs/algo_{time}.log", rotation="1 day", retention="7 days", level="INFO")


def now() -> datetime:
    return datetime.now()


def current_time() -> time:
    return datetime.now().time()


def is_market_open() -> bool:
    t = current_time()
    return time(9, 15) <= t <= time(15, 30)


def is_no_trade_window() -> bool:
    t = current_time()
    for start_str, end_str in config.NO_TRADE_WINDOWS:
        h1, m1 = map(int, start_str.split(":"))
        h2, m2 = map(int, end_str.split(":"))
        if time(h1, m1) <= t <= time(h2, m2):
            return True
    return False


def is_square_off_time() -> bool:
    t = current_time()
    h, m = map(int, config.AUTO_SQUARE_OFF_TIME.split(":"))
    return t >= time(h, m)


def format_inr(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}₹{value:,.2f}"


def log_trade(action: str, details: dict):
    logger.info(f"[TRADE] {action} | {details}")


def log_signal(signal: dict):
    logger.info(f"[SIGNAL] {signal.get('type', 'NONE')} | {signal.get('strike_label', '')} | RSI={signal.get('rsi', 0):.1f}")


def log_error(context: str, error: Exception):
    logger.error(f"[ERROR] {context}: {error}")
