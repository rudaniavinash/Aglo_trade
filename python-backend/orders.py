"""
Order execution via Angel One SmartAPI.
Market orders, margin check, duplicate prevention.
"""

from login import get_session, get_auth_token
from utils import log_trade, log_error
import config
import risk


def place_order(
    symbol: str,
    token: str,
    exchange: str,
    transaction_type: str,  # "BUY" or "SELL"
    quantity: int,
    order_type: str = "MARKET",
    price: float = 0,
    trigger_price: float = 0,
) -> dict:
    """Place order via SmartAPI. Returns order response dict."""
    try:
        api = get_session()

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": order_type,
            "producttype": config.PRODUCT_TYPE,
            "duration": "DAY",
            "price": str(price) if price else "0",
            "triggerprice": str(trigger_price) if trigger_price else "0",
            "quantity": str(quantity),
        }

        response = api.placeOrder(order_params)
        log_trade("ORDER_PLACED", {"symbol": symbol, "type": transaction_type, "qty": quantity, "response": response})
        return {"status": "success", "order_id": response, "params": order_params}

    except Exception as e:
        log_error("Place Order", e)
        return {"status": "error", "message": str(e)}


def execute_entry(signal: dict, capital: float = 100000) -> dict:
    """Execute trade entry based on signal."""
    can, reason = risk.can_trade()
    if not can:
        return {"status": "blocked", "reason": reason}

    index_name = signal["symbol"]
    lot_size = config.LOT_SIZE.get(index_name, 25)
    lots = risk.compute_lot_size(capital, signal["ltp"])
    quantity = lots * lot_size

    # Build option trading symbol (simplified — in production, lookup from master contract)
    trading_symbol = signal["strike_label"].replace(" ", "")
    token = "0"  # Would be looked up from instrument master

    result = place_order(
        symbol=trading_symbol,
        token=token,
        exchange="NFO",
        transaction_type="BUY",
        quantity=quantity,
    )

    if result["status"] == "success":
        trade = {
            "order_id": result["order_id"],
            "symbol": trading_symbol,
            "index": index_name,
            "entry_price": signal["ltp"],
            "quantity": quantity,
            "target": signal["target"],
            "stoploss": signal["stoploss"],
            "current_sl": signal["stoploss"],
            "signal_type": signal["type"],
        }
        risk.record_entry(trade)
        return {"status": "success", "trade": trade}

    return result


def execute_exit(reason: str = "Manual") -> dict:
    """Exit active trade."""
    state = risk.get_state()
    trade = state.get("active_trade")
    if not trade:
        return {"status": "no_trade", "reason": "No active trade"}

    result = place_order(
        symbol=trade["symbol"],
        token="0",
        exchange="NFO",
        transaction_type="SELL",
        quantity=trade["quantity"],
    )

    if result["status"] == "success":
        # Estimate P&L (in production, get fill price from order book)
        pnl = 0  # Would be calculated from actual fill
        risk.record_exit(pnl, {**trade, "exit_reason": reason})
        return {"status": "success", "reason": reason}

    return result


def kill_switch() -> dict:
    """Close all positions immediately."""
    result = execute_exit(reason="Kill Switch")
    risk.set_emergency_stop(True)
    return result


def get_order_book() -> list:
    try:
        api = get_session()
        book = api.orderBook()
        return book.get("data", []) if book else []
    except Exception as e:
        log_error("Order Book", e)
        return []


def get_positions() -> list:
    try:
        api = get_session()
        pos = api.position()
        return pos.get("data", []) if pos else []
    except Exception as e:
        log_error("Positions", e)
        return []
