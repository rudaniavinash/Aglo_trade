"""
Angel One SmartAPI login with TOTP auto-generation.
Handles session creation and auto-reconnect.
"""

import pyotp
from SmartApi import SmartConnect
from loguru import logger
import config
from utils import log_error

_smart_api: SmartConnect | None = None
_auth_token: str = ""
_feed_token: str = ""
_refresh_token: str = ""


def get_session() -> SmartConnect:
    global _smart_api
    if _smart_api is None:
        _smart_api = create_session()
    return _smart_api


def create_session() -> SmartConnect:
    global _smart_api, _auth_token, _feed_token, _refresh_token
    try:
        obj = SmartConnect(api_key=config.API_KEY)
        totp = pyotp.TOTP(config.TOTP_SECRET).now()
        data = obj.generateSession(config.CLIENT_ID, config.MPIN, totp)

        if not data or data.get("status") is False:
            raise ConnectionError(f"Login failed: {data}")

        _auth_token = data["data"]["jwtToken"]
        _refresh_token = data["data"]["refreshToken"]
        _feed_token = obj.getfeedToken()
        _smart_api = obj

        logger.info(f"[LOGIN] Session created for {config.CLIENT_ID}")
        return obj

    except Exception as e:
        log_error("Login", e)
        raise


def refresh_session():
    global _smart_api
    logger.info("[LOGIN] Refreshing session...")
    _smart_api = None
    return create_session()


def get_auth_token() -> str:
    return _auth_token


def get_feed_token() -> str:
    return _feed_token


def get_profile() -> dict:
    try:
        api = get_session()
        return api.getProfile(get_auth_token()) or {}
    except Exception as e:
        log_error("Get Profile", e)
        return {}


def get_margin() -> dict:
    try:
        api = get_session()
        rms = api.rmsLimit()
        if rms and rms.get("data"):
            return rms["data"]
        return {}
    except Exception as e:
        log_error("Get Margin", e)
        return {}
