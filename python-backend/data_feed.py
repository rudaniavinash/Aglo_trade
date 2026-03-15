"""
Live data feed via Angel One SmartAPI WebSocket.
Provides real-time LTP and historical candle data.
"""

import json
import threading
import time as time_mod
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from loguru import logger
import config
from login import get_session, get_auth_token, get_feed_token, refresh_session
from utils import log_error
import pandas as pd

# Live price store
_live_prices: dict[str, float] = {}
_cached_close_prices: dict[str, float] = {}  # Cache of last close prices (from historical API)
_ws: SmartWebSocketV2 | None = None
_ws_thread: threading.Thread | None = None
_ws_connected = False


def get_live_ltp(index_name: str) -> float:
    """
    Get live LTP for an index.
    Priority:
    1. WebSocket live data (real-time during market hours)
    2. Cached close price from historical API (after market hours)
    """
    # First try WebSocket data
    ltp = _live_prices.get(index_name.upper(), 0.0)
    
    # If no WebSocket data, try cached close price
    if ltp <= 0:
        ltp = _cached_close_prices.get(index_name.upper(), 0.0)
    
    # If still no data, fetch fresh from historical API
    if ltp <= 0:
        ltp = _fetch_last_close_from_api(index_name)
    
    return ltp


def _fetch_last_close_from_api(index_name: str) -> float:
    """Fetch last closing price from Angel One Historical API."""
    try:
        info = config.INDEXES.get(index_name.upper(), {})
        if not info:
            return 0.0
        
        # Try primary exchange
        df = fetch_candles(info["token"], info["exchange"], "ONE_MINUTE", days=1)
        if not df.empty:
            close_price = float(df.iloc[-1]["close"])
            _cached_close_prices[index_name.upper()] = close_price
            return close_price
        
        # Special handling for SENSEX - try different token/exchange combinations
        if index_name.upper() == "SENSEX":
            # Try multiple SENSEX tokens on different exchanges
            sensex_tokens = [
                ("99919000", "NSE"),
                ("99919001", "NSE"),
                ("99919000", "BSE"),
                ("99919001", "BSE"),
                ("51110", "NSE"),
                ("53011", "NSE"),
            ]
            for token, exchange in sensex_tokens:
                try:
                    df = fetch_candles(token, exchange, "ONE_MINUTE", days=1)
                    if not df.empty:
                        close_price = float(df.iloc[-1]["close"])
                        if close_price > 30000:
                            _cached_close_prices["SENSEX"] = close_price
                            return close_price
                except:
                    continue
            
            # Try to get SENSEX via SmartAPI LTP API
            sensex_price = _fetch_sensex_ltp_api()
            if sensex_price > 0:
                _cached_close_prices["SENSEX"] = sensex_price
                return sensex_price
            
            # Try Yahoo Finance as last resort for SENSEX only
            sensex_price = _fetch_sensex_from_yahoo()
            if sensex_price > 0:
                _cached_close_prices["SENSEX"] = sensex_price
                return sensex_price
            
            # Try WebSocket if available
            if not is_ws_connected():
                try:
                    from login import get_auth_token, get_feed_token
                    start_websocket()
                    import time
                    time.sleep(2)
                except:
                    pass
            
            ws_price = _live_prices.get("SENSEX", 0.0)
            if ws_price > 0:
                return ws_price
                        
    except Exception as e:
        log_error(f"Fetch last close for {index_name}", e)
    return 0.0


def _fetch_sensex_ltp_api() -> float:
    """Try to get SENSEX LTP via SmartAPI market data."""
    try:
        from login import get_session
        api = get_session()
        
        # Try different SENSEX tokens for LTP
        sensex_tokens = [
            ("99919000", "NSE"),
            ("99919000", "BSE"),
        ]
        
        for token, exchange in sensex_tokens:
            try:
                params = {
                    "exchange": exchange,
                    "tokens": [token]
                }
                data = api.getLTPData(params)
                if data and data.get("status"):
                    ltp_data = data.get("data", {})
                    for key, value in ltp_data.items():
                        ltp = value.get("ltp", 0)
                        if ltp > 0:
                            return float(ltp) / 100 if ltp > 1000 else float(ltp)
            except:
                continue
    except Exception as e:
        log_error("Fetch SENSEX LTP API", e)
    return 0.0


def refresh_cached_prices():
    """Refresh cached close prices for all indexes (call after market hours)."""
    for index_name in config.INDEXES.keys():
        _fetch_last_close_from_api(index_name)


def get_all_live_prices() -> dict[str, float]:
    """Get all live prices with smart fallback."""
    result = {}
    for index_name in config.INDEXES.keys():
        result[index_name] = get_live_ltp(index_name)
    return result


# ── WebSocket ────────────────────────────────────

def start_websocket():
    global _ws, _ws_thread, _ws_connected

    if _ws_connected:
        return

    try:
        auth_token = get_auth_token()
        feed_token = get_feed_token()
        client_id = config.CLIENT_ID

        _ws = SmartWebSocketV2(auth_token, config.API_KEY, client_id, feed_token)

        def on_data(ws, message):
            try:
                data = json.loads(message) if isinstance(message, str) else message
                token = str(data.get("token", ""))
                ltp = data.get("last_traded_price", 0)
                if ltp:
                    ltp = ltp / 100  # SmartAPI sends paise
                    
                    # Check regular indexes first
                    for name, info in config.INDEXES.items():
                        if info["token"] == token:
                            _live_prices[name] = ltp
                            _cached_close_prices[name] = ltp
                            break
                    else:
                        # Special handling for SENSEX - check NSE/BSE tokens
                        if token in ["99919000", "99919001"]:
                            _live_prices["SENSEX"] = ltp
                            _cached_close_prices["SENSEX"] = ltp
            except Exception as e:
                log_error("WS on_data", e)

        def on_open(ws):
            global _ws_connected
            _ws_connected = True
            logger.info("[WS] Connected")
            tokens = []
            for name, info in config.INDEXES.items():
                exchange = 1 if info["exchange"] == "NSE" else 2
                tokens.append({"exchangeType": exchange, "tokens": [info["token"]]})
            
            # Special handling for SENSEX - try NSE token on WebSocket
            # BSE might not work, but NSE token might
            sensex_tokens = [
                {"exchangeType": 1, "tokens": ["99919000"]},  # NSE
                {"exchangeType": 2, "tokens": ["99919000"]},  # BSE
            ]
            for st in sensex_tokens:
                tokens.append(st)
            
            ws.subscribe("abc123", 1, tokens)  # mode 1 = LTP

        def on_error(ws, error):
            global _ws_connected
            _ws_connected = False
            log_error("WS", Exception(str(error)))

        def on_close(ws):
            global _ws_connected
            _ws_connected = False
            logger.info("[WS] Disconnected — reconnecting in 5s...")
            time_mod.sleep(5)
            start_websocket()

        _ws.on_data = on_data
        _ws.on_open = on_open
        _ws.on_error = on_error
        _ws.on_close = on_close

        _ws_thread = threading.Thread(target=_ws.connect, daemon=True)
        _ws_thread.start()

    except Exception as e:
        log_error("WS Start", e)
        _ws_connected = False


def stop_websocket():
    global _ws, _ws_connected
    if _ws:
        try:
            _ws.close_connection()
        except:
            pass
    _ws_connected = False


def is_ws_connected() -> bool:
    return _ws_connected


# ── Historical Data ──────────────────────────────

def fetch_candles(symbol_token: str, exchange: str, interval: str, days: int = 5) -> pd.DataFrame:
    """Fetch historical candles. interval: ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, etc."""
    try:
        api = get_session()
        from datetime import datetime, timedelta

        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)

        params = {
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }

        data = api.getCandleData(params)
        if data and data.get("data"):
            df = pd.DataFrame(
                data["data"],
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df

        return pd.DataFrame()

    except Exception as e:
        log_error("Fetch Candles", e)
        return pd.DataFrame()


def get_index_candles_5m(index_name: str) -> pd.DataFrame:
    info = config.INDEXES.get(index_name, {})
    if not info:
        return pd.DataFrame()
    return fetch_candles(info["token"], info["exchange"], "FIVE_MINUTE", days=3)


def get_index_candles_15m(index_name: str) -> pd.DataFrame:
    info = config.INDEXES.get(index_name, {})
    if not info:
        return pd.DataFrame()
    return fetch_candles(info["token"], info["exchange"], "FIFTEEN_MINUTE", days=3)


def _fetch_sensex_from_yahoo() -> float:
    """Fetch SENSEX price from Yahoo Finance as last resort."""
    try:
        import requests
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EBSESN"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                meta = result[0].get("meta", {})
                price = meta.get("previousClose") or meta.get("regularMarketPrice")
                if price:
                    return float(price)
    except Exception as e:
        log_error("Fetch SENSEX from Yahoo", e)
    return 0.0
