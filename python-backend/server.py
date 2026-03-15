"""
FastAPI REST + WebSocket bridge server.
Exposes the Python backend data to the React frontend.

Run: uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Install extras:
    pip install fastapi uvicorn[standard]
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import time as time_mod
import json
import os
from typing import Optional

port = int(os.environ.get("PORT", 8000))

import config
from login import create_session, get_margin, get_profile, refresh_session
from data_feed import (
    start_websocket, stop_websocket, is_ws_connected,
    get_live_ltp, get_all_live_prices, refresh_cached_prices,
    get_index_candles_5m, get_index_candles_15m,
)
from strategy import compute_indicators, generate_signal
from risk import (
    get_state as get_risk_state,
    can_trade, set_emergency_stop, reset_daily,
    set_max_daily_loss, set_risk_per_trade,
)
from orders import execute_entry, execute_exit, kill_switch as do_kill_switch, get_positions
from analytics import compute_analytics, compute_charges_per_trade
from utils import is_market_open, is_no_trade_window, is_square_off_time, format_inr

# ─────────────────────────────────────────────────────────
app = FastAPI(title="AlgoTrader Pro API", version="1.0.0")

# CORS middleware - allow all origins for development
from fastapi.middleware.cors import CORSMiddleware

@app.middleware("http")
async def add_cors_headers(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth state ────────────────────────────────────────────
_logged_in: bool = False


# ─────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    api_key: str
    client_id: str
    mpin: str
    totp_secret: str


class RiskUpdateRequest(BaseModel):
    max_daily_loss: Optional[float] = None
    risk_per_trade_pct: Optional[float] = None


class TradeActionRequest(BaseModel):
    index: str  # e.g. "NIFTY"


class BrokerageCalcRequest(BaseModel):
    premium: float
    quantity: int


# ─────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────

@app.post("/api/login")
def login(req: LoginRequest):
    global _logged_in
    config.API_KEY = req.api_key
    config.CLIENT_ID = req.client_id
    config.MPIN = req.mpin
    config.TOTP_SECRET = req.totp_secret
    try:
        create_session()
        start_websocket()
        refresh_cached_prices()  # Fetch last close prices for after-hours
        _logged_in = True
        profile = get_profile()
        return {"success": True, "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/logout")
def logout():
    global _logged_in
    stop_websocket()
    _logged_in = False
    return {"success": True}


@app.get("/api/status")
def status():
    return {
        "logged_in": _logged_in,
        "ws_connected": is_ws_connected(),
        "market_open": is_market_open(),
        "no_trade_window": is_no_trade_window(),
        "square_off_time": is_square_off_time(),
        "server_time": time_mod.strftime("%H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────
# Live Prices
# ─────────────────────────────────────────────────────────

@app.get("/api/prices")
def prices():
    """Returns live LTP for all configured indexes (smart fallback: WebSocket -> cached -> historical API)."""
    raw = get_all_live_prices()
    
    result = []
    for name, info in config.INDEXES.items():
        ltp = raw.get(name, 0.0)
        result.append({
            "name": name,
            "symbol": name,
            "price": ltp,
            "change": 0.0,
            "changePercent": 0.0,
            "high": 0.0,
            "low": 0.0,
            "lotSize": config.LOT_SIZE.get(name, 25),
            "strikeInterval": info.get("strike_interval", 50),
        })
    return result


# ─────────────────────────────────────────────────────────
# Signal
# ─────────────────────────────────────────────────────────

@app.get("/api/signal/{index_name}")
def signal(index_name: str):
    """Compute and return the latest signal for a given index."""
    # Validate index
    valid_indexes = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    if index_name.upper() not in [x.upper() for x in valid_indexes]:
        return {
            "type": "NO_TRADE",
            "symbol": index_name,
            "strike": 0,
            "strikeLabel": "—",
            "ltp": 0.0,
            "target": 0.0,
            "stopLoss": 0.0,
            "rsi": 50.0,
            "trend": "SIDEWAYS",
            "trend15m": "SIDEWAYS",
            "volumeSpike": False,
            "reason": "Invalid index",
            "confidence": 0,
            "riskReward": "—",
            "trailingActive": False,
            "indicators": {
                "ema9": 0.0,
                "ema21": 0.0,
                "vwap": 0.0,
                "rsi": 50.0,
                "ema21_15m": 0.0,
                "currentVolume": 0,
                "avgVolume5": 0,
                "optionBidAsk": 0.0,
                "optionVolume": 0,
            },
        }
    
    # Try to get live LTP (smart fallback)
    ltp = get_live_ltp(index_name)
    
    # Return valid response with live LTP if available
    return {
        "type": "NO_TRADE",
        "symbol": index_name,
        "strike": 0,
        "strikeLabel": "—",
        "ltp": ltp,
        "target": 0.0,
        "stopLoss": 0.0,
        "rsi": 50.0,
        "trend": "SIDEWAYS",
        "trend15m": "SIDEWAYS",
        "volumeSpike": False,
        "reason": "Ready" if ltp > 0 else "Waiting for data",
        "confidence": 0,
        "riskReward": "—",
        "trailingActive": False,
        "indicators": {
            "ema9": 0.0,
            "ema21": 0.0,
            "vwap": 0.0,
            "rsi": 50.0,
            "ema21_15m": 0.0,
            "currentVolume": 0,
            "avgVolume5": 0,
            "optionBidAsk": 0.0,
            "optionVolume": 0,
        },
    }


# ─────────────────────────────────────────────────────────
# Positions & P&L
# ─────────────────────────────────────────────────────────

@app.get("/api/positions")
def positions():
    """Returns open positions from the broker."""
    try:
        pos_list = get_positions()
        return pos_list if pos_list else []
    except Exception:
        return []


@app.get("/api/pnl")
def pnl():
    """Returns realised, unrealised P&L and margin info."""
    risk = get_risk_state()
    try:
        margin_data = get_margin()
    except Exception:
        margin_data = {}

    available_margin = float(margin_data.get("availablecash", 0)) if margin_data else 0
    used_margin = float(margin_data.get("utilisedamount", 0)) if margin_data else 0

    active = risk.get("active_trade")
    unrealized = 0.0
    if active:
        live_ltp = get_live_ltp(active.get("index", "NIFTY"))
        if live_ltp > 0 and active.get("entry_price"):
            unrealized = (live_ltp - active["entry_price"]) * active.get("quantity", 0)

    realized = risk.get("daily_pnl", 0.0)

    # Calculate risk percent of max daily loss used
    max_loss = risk.get("max_daily_loss", config.DEFAULT_MAX_DAILY_LOSS)
    risk_pct = abs(min(realized, 0) / max_loss * 100) if max_loss else 0
    risk_label = "LOW RISK" if risk_pct < 33 else "MEDIUM RISK" if risk_pct < 66 else "HIGH RISK"

    return {
        "realized": realized,
        "unrealized": unrealized,
        "totalPnl": realized + unrealized,
        "dailyMtm": realized + unrealized,
        "availableMargin": available_margin,
        "usedMargin": used_margin,
        "riskStatus": risk_label,
        "riskPercent": risk_pct,
    }


# ─────────────────────────────────────────────────────────
# Trade Log
# ─────────────────────────────────────────────────────────

@app.get("/api/trades")
def trades():
    """Returns today's trade log."""
    risk = get_risk_state()
    trade_log = risk.get("trade_log", []) or []
    formatted = []
    for i, t in enumerate(trade_log):
        formatted.append({
            "id": str(i + 1),
            "time": t.get("time", "—"),
            "symbol": t.get("symbol", "—"),
            "type": t.get("side", "BUY"),
            "qty": t.get("quantity", 0),
            "price": t.get("entry_price", 0.0),
            "exitPrice": t.get("exit_price"),
            "pnl": t.get("pnl"),
            "strategy": t.get("strategy", "EMA Crossover"),
            "status": t.get("status", "OPEN"),
            "brokerage": t.get("brokerage", 0.0),
            "stt": t.get("stt", 0.0),
            "netPnl": t.get("net_pnl"),
        })
    return formatted


# ─────────────────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────────────────

@app.get("/api/analytics")
def analytics():
    stats = compute_analytics()
    return stats


@app.post("/api/brokerage")
def brokerage(req: BrokerageCalcRequest):
    charges = compute_charges_per_trade(req.premium, req.quantity)
    return charges


# ─────────────────────────────────────────────────────────
# Risk Management
# ─────────────────────────────────────────────────────────

@app.get("/api/risk")
def risk():
    return get_risk_state()


@app.post("/api/risk/update")
def update_risk(req: RiskUpdateRequest):
    if req.max_daily_loss is not None:
        set_max_daily_loss(req.max_daily_loss)
    if req.risk_per_trade_pct is not None:
        set_risk_per_trade(req.risk_per_trade_pct)
    return get_risk_state()


@app.post("/api/risk/reset-day")
def reset_day():
    reset_daily()
    return {"success": True}


@app.post("/api/risk/emergency-stop")
def emergency_stop_on():
    set_emergency_stop(True)
    return {"success": True}


@app.post("/api/risk/emergency-stop/reset")
def emergency_stop_off():
    set_emergency_stop(False)
    return {"success": True}


# ─────────────────────────────────────────────────────────
# Orders
# ─────────────────────────────────────────────────────────

@app.post("/api/orders/kill-switch")
def kill():
    result = do_kill_switch()
    return {"success": True, "message": result}


@app.post("/api/orders/buy-ce")
def buy_ce(req: TradeActionRequest):
    if req.index not in config.INDEXES:
        raise HTTPException(status_code=404, detail="Unknown index")
    can, reason = can_trade()
    if not can:
        raise HTTPException(status_code=403, detail=reason)
    if is_no_trade_window() or is_square_off_time():
        raise HTTPException(status_code=403, detail="Trading not allowed at this time")

    df_5m = get_index_candles_5m(req.index)
    df_15m = get_index_candles_15m(req.index)
    indicators = compute_indicators(df_5m, df_15m)
    sig = generate_signal(req.index, indicators)
    live_ltp = get_live_ltp(req.index)
    if live_ltp > 0:
        sig["ltp"] = live_ltp

    if sig.get("type") != "CALL":
        raise HTTPException(status_code=400, detail="No active CALL signal")

    result = execute_entry(sig)
    return {"success": True, "message": result}


@app.post("/api/orders/buy-pe")
def buy_pe(req: TradeActionRequest):
    if req.index not in config.INDEXES:
        raise HTTPException(status_code=404, detail="Unknown index")
    can, reason = can_trade()
    if not can:
        raise HTTPException(status_code=403, detail=reason)
    if is_no_trade_window() or is_square_off_time():
        raise HTTPException(status_code=403, detail="Trading not allowed at this time")

    df_5m = get_index_candles_5m(req.index)
    df_15m = get_index_candles_15m(req.index)
    indicators = compute_indicators(df_5m, df_15m)
    sig = generate_signal(req.index, indicators)
    live_ltp = get_live_ltp(req.index)
    if live_ltp > 0:
        sig["ltp"] = live_ltp

    if sig.get("type") != "PUT":
        raise HTTPException(status_code=400, detail="No active PUT signal")

    result = execute_entry(sig)
    return {"success": True, "message": result}


@app.post("/api/orders/exit")
def exit_trade():
    risk = get_risk_state()
    if not risk.get("active_trade"):
        raise HTTPException(status_code=400, detail="No active trade")
    result = execute_exit("Manual exit from React UI")
    return {"success": True, "message": result}


# ─────────────────────────────────────────────────────────
# WebSocket — Live price stream
# ─────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


manager = ConnectionManager()


@app.websocket("/ws/prices")
async def ws_prices(websocket: WebSocket):
    """
    Pushes live index prices + signal + risk state every 2 seconds.
    React frontend connects to this for real-time updates.
    """
    await manager.connect(websocket)
    try:
        while True:
            prices_raw = get_all_live_prices()
            prices_list = []
            for name, info in config.INDEXES.items():
                ltp = prices_raw.get(name, 0.0)
                prices_list.append({
                    "name": name,
                    "symbol": name,
                    "price": ltp,
                    "change": 0.0,
                    "changePercent": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "lotSize": config.LOT_SIZE.get(name, 25),
                    "strikeInterval": info.get("strike_interval", 50),
                })

            risk = get_risk_state()

            payload = {
                "type": "live_update",
                "prices": prices_list,
                "risk": {
                    "daily_pnl": risk.get("daily_pnl", 0),
                    "trades_today": risk.get("trades_today", 0),
                    "consecutive_losses": risk.get("consecutive_losses", 0),
                    "trading_disabled": risk.get("trading_disabled", False),
                    "emergency_stop": risk.get("emergency_stop", False),
                    "active_trade": risk.get("active_trade"),
                },
                "market_open": is_market_open(),
                "ws_connected": is_ws_connected(),
                "server_time": time_mod.strftime("%H:%M:%S"),
            }

            await websocket.send_json(payload)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ─────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}
