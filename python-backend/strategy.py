"""
Indicator calculations and signal generation engine.
EMA 9/21, VWAP, RSI(14), volume spike on 5m.
15m EMA 21 for higher timeframe confirmation.
"""

import pandas as pd
import numpy as np
import config


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def compute_indicators(df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> dict:
    """Compute all indicators from 5m and 15m candle DataFrames."""
    if df_5m.empty or len(df_5m) < config.EMA_SLOW + 5:
        return {}

    close = df_5m["close"]

    ema9 = ema(close, config.EMA_FAST).iloc[-1]
    ema21 = ema(close, config.EMA_SLOW).iloc[-1]
    vwap_val = vwap(df_5m).iloc[-1]
    rsi_val = rsi(close, config.RSI_PERIOD).iloc[-1]
    ltp = close.iloc[-1]

    vol = df_5m["volume"]
    current_vol = vol.iloc[-1]
    avg_vol_5 = vol.iloc[-6:-1].mean() if len(vol) >= 6 else vol.mean()

    # 15m EMA 21
    ema21_15m = 0.0
    if not df_15m.empty and len(df_15m) >= config.EMA_SLOW:
        ema21_15m = ema(df_15m["close"], config.EMA_SLOW).iloc[-1]

    return {
        "ema9": ema9,
        "ema21": ema21,
        "vwap": vwap_val,
        "rsi": rsi_val,
        "current_volume": current_vol,
        "avg_volume_5": avg_vol_5,
        "ltp": ltp,
        "ema21_15m": ema21_15m,
    }


def generate_signal(index_name: str, indicators: dict) -> dict:
    """Generate CALL/PUT/NO_TRADE signal from indicators."""
    if not indicators:
        return _no_trade("Insufficient data")

    ema9 = indicators["ema9"]
    ema21 = indicators["ema21"]
    vwap_val = indicators["vwap"]
    rsi_val = indicators["rsi"]
    ltp = indicators["ltp"]
    current_vol = indicators["current_volume"]
    avg_vol_5 = indicators["avg_volume_5"]
    ema21_15m = indicators["ema21_15m"]

    volume_spike = current_vol > avg_vol_5
    ema_bullish = ema9 > ema21
    ema_bearish = ema9 < ema21
    above_vwap = ltp > vwap_val
    below_vwap = ltp < vwap_val

    trend = "BULLISH" if (ema_bullish and above_vwap) else ("BEARISH" if (ema_bearish and below_vwap) else "SIDEWAYS")
    trend_15m = "BULLISH" if ltp > ema21_15m else ("BEARISH" if ltp < ema21_15m else "SIDEWAYS")

    from strike_selector import get_atm_strike
    strike_interval = config.INDEXES.get(index_name, {}).get("strike_interval", 50)
    atm = get_atm_strike(ltp, strike_interval)

    strong_momentum = rsi_val > config.RSI_STRONG_BULL or rsi_val < config.RSI_STRONG_BEAR

    signal_type = "NO_TRADE"
    strike = atm
    strike_label = "—"
    confidence = 0

    # CALL
    if ema_bullish and above_vwap and rsi_val > config.RSI_CALL_THRESHOLD and volume_spike and trend_15m == "BULLISH":
        signal_type = "CALL"
        strike = atm + strike_interval if strong_momentum else atm
        strike_label = f"{index_name} {strike} CE"
        confidence = min(95, 50 + (rsi_val - 55) * 2 + (15 if volume_spike else 0))

    # PUT
    elif ema_bearish and below_vwap and rsi_val < config.RSI_PUT_THRESHOLD and volume_spike and trend_15m == "BEARISH":
        signal_type = "PUT"
        strike = atm - strike_interval if strong_momentum else atm
        strike_label = f"{index_name} {strike} PE"
        confidence = min(95, 50 + (45 - rsi_val) * 2 + (15 if volume_spike else 0))

    target = ltp + config.TARGET_POINTS if signal_type != "NO_TRADE" else 0
    stoploss = ltp - config.STOPLOSS_POINTS if signal_type != "NO_TRADE" else 0
    rr = f"1:{config.TARGET_POINTS / config.STOPLOSS_POINTS:.2f}" if signal_type != "NO_TRADE" else "—"

    if signal_type == "NO_TRADE":
        if config.RSI_PUT_THRESHOLD <= rsi_val <= config.RSI_CALL_THRESHOLD:
            reason = "RSI in no-trade zone (45-55)"
        elif not volume_spike:
            reason = "Low volume — no confirmation"
        elif trend_15m == "SIDEWAYS":
            reason = "15m trend unclear"
        else:
            reason = "Mixed signals"
    else:
        reason = f"EMA {'bullish' if signal_type == 'CALL' else 'bearish'} | {'Above' if signal_type == 'CALL' else 'Below'} VWAP | RSI {rsi_val:.0f} | Vol spike ✓ | 15m {trend_15m} ✓"

    return {
        "type": signal_type,
        "symbol": index_name,
        "strike": strike,
        "strike_label": strike_label,
        "ltp": ltp,
        "target": target,
        "stoploss": stoploss,
        "rsi": rsi_val,
        "trend": trend,
        "trend_15m": trend_15m,
        "volume_spike": volume_spike,
        "reason": reason,
        "confidence": confidence,
        "risk_reward": rr,
        "ema9": indicators["ema9"],
        "ema21": indicators["ema21"],
        "vwap": indicators["vwap"],
    }


def _no_trade(reason: str) -> dict:
    return {
        "type": "NO_TRADE",
        "symbol": "",
        "strike": 0,
        "strike_label": "—",
        "ltp": 0,
        "target": 0,
        "stoploss": 0,
        "rsi": 0,
        "trend": "SIDEWAYS",
        "trend_15m": "SIDEWAYS",
        "volume_spike": False,
        "reason": reason,
        "confidence": 0,
        "risk_reward": "—",
        "ema9": 0,
        "ema21": 0,
        "vwap": 0,
    }
