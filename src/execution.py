import logging
from typing import Dict, List, Optional
from src.paper_engine import paper_engine
from src.master_data import get_symbol_by_token

logger = logging.getLogger(__name__)

# ===== SIMULATED EXECUTION / PAPER TRADING ENGINE WRAPPER =====

def execute_order(
    token: Optional[str] = None,
    action: Optional[str] = None,
    quantity: Optional[int] = None,
    client_price: float = 0.0,
    symbol: Optional[str] = None,
    order_type: str = "MARKET",
    exchange: str = "NSE",
    lots: Optional[int] = None,
    lotsize: Optional[int] = None,
    price: Optional[float] = None,
    **kwargs
) -> Dict:
    """
    Executes a simulated paper order.
    Accepts token/symbol and supports both quantity and lot-based callers.
    """
    try:
        if quantity is None:
            if lots is not None and lotsize is not None:
                quantity = int(lots) * int(lotsize)
            elif lots is not None:
                quantity = int(lots)
            else:
                quantity = int(kwargs.get("qty", 0) or 0)

        if price is not None:
            client_price = float(price)

        if action is None:
            action = str(kwargs.get("side", "BUY"))

        if token is None:
            token = str(kwargs.get("token", ""))

        if quantity is None or int(quantity) <= 0:
            raise ValueError("Quantity must be greater than 0.")

        if client_price is None:
            client_price = float(kwargs.get("price", 0.0) or 0.0)

        resolved_symbol = symbol or get_symbol_by_token(token) or f"TOKEN_{token}"
        side = action.upper().strip()

        logger.info(
            f"[PAPER TRADE] Placing order: {side} {quantity} shares of {resolved_symbol} (Token: {token}) @ Rs {client_price}"
        )

        order_record = paper_engine.place_order(
            symbol=resolved_symbol,
            side=side,
            quantity=int(quantity),
            price=float(client_price),
            order_type=order_type,
            exchange=exchange
        )

        return {
            "status": "success",
            "message": f"Paper order executed: {side} {quantity} {resolved_symbol} @ Rs {client_price}",
            "order_id": order_record.get("order_id"),
            "data": order_record
        }
    except ValueError as val_err:
        logger.warning(f"[PAPER TRADE REJECTED] {val_err}")
        return {
            "status": "error",
            "message": str(val_err)
        }
    except Exception as e:
        logger.error(f"[PAPER TRADE ERROR] Unexpected error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }


def place_order(
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    order_type: str = "MARKET",
    exchange: str = "NSE",
    **kwargs
) -> Dict:
    """
    Direct alias for placing paper orders using symbol.
    """
    return execute_order(
        token=kwargs.get("token", ""),
        action=side,
        quantity=quantity,
        client_price=price,
        symbol=symbol,
        order_type=order_type,
        exchange=exchange,
        **kwargs
    )


def cancel_order(order_id: str) -> Dict:
    """
    Simulated order cancellation.
    """
    logger.info(f"[PAPER TRADE] Cancel request received for order: {order_id}")
    return {
        "status": "success",
        "message": f"Order {order_id} cancelled (Simulated).",
        "order_id": order_id
    }


def get_order_book() -> List[Dict]:
    """
    Retrieves the complete list of paper orders.
    """
    return paper_engine.get_orders()


def get_positions() -> List[Dict]:
    """
    Retrieves currently open paper positions.
    """
    return paper_engine.get_positions()


def get_portfolio() -> Dict:
    """
    Retrieves the current virtual capital balance, open positions, and counts.
    """
    return paper_engine.get_portfolio()