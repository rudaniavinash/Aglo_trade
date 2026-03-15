"""
ATM strike selection and liquidity filtering.
"""

import config


def get_atm_strike(ltp: float, strike_interval: int) -> int:
    """Round LTP to nearest strike interval."""
    return round(ltp / strike_interval) * strike_interval


def get_strike_for_index(index_name: str, ltp: float) -> int:
    interval = config.INDEXES.get(index_name, {}).get("strike_interval", 50)
    return get_atm_strike(ltp, interval)


def select_strike(index_name: str, ltp: float, rsi: float) -> dict:
    """
    Select optimal strike based on RSI momentum.
    Strong RSI → 1 strike OTM, else ATM.
    """
    interval = config.INDEXES.get(index_name, {}).get("strike_interval", 50)
    atm = get_atm_strike(ltp, interval)

    if rsi > config.RSI_STRONG_BULL:
        # Strong bullish → 1 OTM CE
        return {"strike": atm + interval, "type": "OTM_CE", "atm": atm}
    elif rsi < config.RSI_STRONG_BEAR:
        # Strong bearish → 1 OTM PE
        return {"strike": atm - interval, "type": "OTM_PE", "atm": atm}
    else:
        return {"strike": atm, "type": "ATM", "atm": atm}


def passes_liquidity_filter(option_volume: float, bid_ask_spread: float) -> bool:
    """Check if option has enough liquidity."""
    return option_volume >= config.MIN_OPTION_VOLUME and bid_ask_spread <= config.MAX_BID_ASK_SPREAD
