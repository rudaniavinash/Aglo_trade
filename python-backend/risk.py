"""
Risk management: trade limits, daily loss, trailing SL, consecutive loss tracking.
"""

import config
from utils import log_trade

# ── Session State ────────────────────────────────
_state = {
    "trades_today": 0,
    "daily_pnl": 0.0,
    "consecutive_losses": 0,
    "trading_disabled": False,
    "emergency_stop": False,
    "active_trade": None,  # dict or None
    "trade_log": [],
    "max_daily_loss": config.DEFAULT_MAX_DAILY_LOSS,
    "risk_per_trade_pct": config.RISK_PER_TRADE_PCT,
}


def get_state() -> dict:
    return dict(_state)


def reset_daily():
    _state["trades_today"] = 0
    _state["daily_pnl"] = 0.0
    _state["consecutive_losses"] = 0
    _state["trading_disabled"] = False
    _state["emergency_stop"] = False
    _state["active_trade"] = None
    _state["trade_log"] = []


def can_trade() -> tuple[bool, str]:
    if _state["emergency_stop"]:
        return False, "Emergency stop active"
    if _state["trading_disabled"]:
        return False, "Trading disabled — limit hit"
    if _state["trades_today"] >= config.MAX_TRADES_PER_DAY:
        _state["trading_disabled"] = True
        return False, f"Max trades ({config.MAX_TRADES_PER_DAY}) reached"
    if _state["daily_pnl"] <= -abs(_state["max_daily_loss"]):
        _state["trading_disabled"] = True
        return False, f"Max daily loss (₹{_state['max_daily_loss']}) hit"
    if _state["consecutive_losses"] >= config.MAX_CONSECUTIVE_LOSSES:
        _state["trading_disabled"] = True
        return False, f"Max consecutive losses ({config.MAX_CONSECUTIVE_LOSSES}) hit"
    if _state["active_trade"] is not None:
        return False, "Active trade exists — one at a time"
    return True, "OK"


def set_emergency_stop(active: bool):
    _state["emergency_stop"] = active
    if active:
        _state["trading_disabled"] = True


def record_entry(trade: dict):
    _state["active_trade"] = trade
    _state["trades_today"] += 1
    log_trade("ENTRY", trade)


def record_exit(pnl: float, trade: dict):
    _state["active_trade"] = None
    _state["daily_pnl"] += pnl
    trade["pnl"] = pnl
    _state["trade_log"].append(trade)

    if pnl < 0:
        _state["consecutive_losses"] += 1
    else:
        _state["consecutive_losses"] = 0

    log_trade("EXIT", {"pnl": pnl, **trade})

    # Check limits after recording
    can_trade()


def compute_lot_size(capital: float, ltp: float) -> int:
    """Compute lots based on risk per trade %."""
    risk_amount = capital * (_state["risk_per_trade_pct"] / 100)
    risk_per_lot = config.STOPLOSS_POINTS * 1  # per unit
    lots = int(risk_amount / (risk_per_lot * ltp / 100)) if ltp > 0 else 1
    return max(1, lots)


def check_trailing_sl(entry_price: float, current_price: float, current_sl: float) -> float:
    """If profit exceeds trigger, move SL to cost."""
    profit = current_price - entry_price
    if profit >= config.TRAILING_TRIGGER and current_sl < entry_price:
        return entry_price  # Trail to cost
    return current_sl


def set_max_daily_loss(amount: float):
    _state["max_daily_loss"] = abs(amount)


def set_risk_per_trade(pct: float):
    _state["risk_per_trade_pct"] = pct


def get_trade_log() -> list:
    return list(_state["trade_log"])
