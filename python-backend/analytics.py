"""
Trade analytics: win rate, profit factor, equity curve, brokerage calculation.
"""

import config
from risk import get_trade_log


def compute_analytics() -> dict:
    log = get_trade_log()
    if not log:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "profit_factor": 0,
            "total_pnl": 0,
            "net_pnl": 0,
            "total_charges": 0,
            "max_consecutive_losses": 0,
            "equity_curve": [],
        }

    wins = [t for t in log if t.get("pnl", 0) > 0]
    losses = [t for t in log if t.get("pnl", 0) <= 0]

    total_win = sum(t["pnl"] for t in wins) if wins else 0
    total_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0

    avg_win = total_win / len(wins) if wins else 0
    avg_loss = total_loss / len(losses) if losses else 0
    profit_factor = total_win / total_loss if total_loss > 0 else float("inf")

    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for t in log:
        if t.get("pnl", 0) <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0

    # Equity curve
    equity = []
    running = 0
    for i, t in enumerate(log):
        running += t.get("pnl", 0)
        equity.append({"trade": i + 1, "equity": running})

    # Total charges
    total_charges = compute_total_charges(log)
    total_pnl = sum(t.get("pnl", 0) for t in log)

    return {
        "total_trades": len(log),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(log) * 100) if log else 0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "net_pnl": total_pnl - total_charges,
        "total_charges": total_charges,
        "max_consecutive_losses": max_consec,
        "equity_curve": equity,
    }


def compute_charges_per_trade(premium: float, quantity: int) -> dict:
    turnover = premium * quantity
    brokerage = config.BROKERAGE_PER_ORDER * 2  # Entry + Exit
    stt = turnover * config.STT_PCT / 100  # Sell side only, simplified
    gst = brokerage * config.GST_PCT / 100
    sebi = turnover * config.SEBI_CHARGES / 100
    stamp = turnover * config.STAMP_DUTY / 100
    slippage = config.ESTIMATED_SLIPPAGE_POINTS * quantity

    total = brokerage + stt + gst + sebi + stamp + slippage

    return {
        "brokerage": brokerage,
        "stt": stt,
        "gst": gst,
        "sebi": sebi,
        "stamp_duty": stamp,
        "slippage": slippage,
        "total": total,
    }


def compute_total_charges(log: list) -> float:
    total = 0
    for t in log:
        qty = t.get("quantity", 0)
        price = t.get("entry_price", 0)
        charges = compute_charges_per_trade(price, qty)
        total += charges["total"]
    return total
