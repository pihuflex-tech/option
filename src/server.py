import asyncio
import csv
from datetime import datetime
import io
import logging
from pathlib import Path
import threading
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from config.settings import (
    CLIENT_CODE,
    INITIAL_VIRTUAL_BALANCE,
    MPIN,
    NIFTY_SPOT_TOKEN,
    SMARTAPI_KEY,
    TOTP_SECRET,
)
from src.master_data import load_and_index_master, search_scrip
from src import stream_engine
from src.stream_engine import (
    price_cache,
    start_streaming,
    stop_streaming,
    subscribe_tokens,
    unsubscribe_tokens,
)
from src.paper_engine import paper_engine

logger = logging.getLogger(__name__)

app = FastAPI(title="Option Scalper - Paper Trading Engine")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Mount static and templates
app.mount(
    "/static",
    StaticFiles(directory=str(PROJECT_ROOT / "static")),
    name="static",
)
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))

# Lock to ensure stream engine starts only once
stream_lock = asyncio.Lock()
stream_task = None
_master_index_lock = threading.Lock()
_expiry_index = None
_last_spot_fetch = 0.0


class OrderRequest(BaseModel):
    token: str
    symbol: str
    action: str  # BUY or SELL
    quantity: int | None = None
    lots: int | None = None
    lotsize: int | None = None
    price: float = 0.0
    target: float | None = None
    stop_loss: float | None = None


class SLTargetRequest(BaseModel):
    symbol: str
    target: float | None = None
    stop_loss: float | None = None


class TokenSubscription(BaseModel):
    tokens: list[str]


@app.on_event("startup")
async def startup_event():
    """Start broker authentication in the background without blocking app startup."""
    global stream_task
    async with stream_lock:
        if stream_task is None:
            if not all(
                (NIFTY_SPOT_TOKEN, SMARTAPI_KEY, CLIENT_CODE, MPIN, TOTP_SECRET)
            ):
                logger.warning(
                    "SmartAPI credentials are not configured. Starting in paper-trading mode without live market streaming."
                )
                return
            stream_task = asyncio.create_task(start_streaming())
            logger.info("Broker session initialization started.")


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown of streams."""
    await asyncio.to_thread(stop_streaming)


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """Render main trading dashboard."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/search")
def api_search(q: str):
    """Search scrips from master data."""
    if not q or len(q) < 2:
        return {"results": []}
    results = search_scrip(q)
    return {"results": results[:20]}


# ===== FIXED & UPDATED: Paper Order Execution =====
@app.post("/api/order")
def handle_order(order: OrderRequest):
    """Execute a paper order using the current cached quote when available."""
    try:
        quantity = order.quantity
        if quantity is None and order.lots is not None and order.lotsize is not None:
            quantity = order.lots * order.lotsize
        if quantity is None:
            return {"status": "error", "message": "Provide quantity or both lots and lotsize."}

        token = str(order.token).strip()
        market_price = price_cache.get(token, 0.0)
        execution_price = market_price if market_price > 0 else order.price
        if execution_price <= 0:
            return {
                "status": "error",
                "message": f"No live price is available for {order.symbol}.",
            }

        side = order.action.upper().strip()
        result = paper_engine.place_order(
            symbol=order.symbol,
            side=side,
            quantity=quantity,
            price=execution_price,
            order_type="MARKET",
            exchange="NFO",
            token=token,
            lotsize=order.lotsize or 50,
            target=order.target,
            stop_loss=order.stop_loss,
        )
        return {
            "status": "success",
            "message": f"Paper order placed: {side} {quantity} {order.symbol} @ Rs {execution_price}",
            "order": result
        }
    except ValueError as val_err:
        logger.warning(f"Validation error placing paper order: {val_err}")
        return {"status": "error", "message": str(val_err)}
    except Exception as e:
        logger.error(f"Error placing paper order: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.post("/api/position/sl-target")
def api_update_sl_target(req: SLTargetRequest):
    """Update Target and Stop-Loss for an existing open position."""
    try:
        pos = paper_engine.update_sl_target(req.symbol, req.target, req.stop_loss)
        # Immediately check against current cached price
        paper_engine.check_sl_and_target(price_cache)
        return {
            "status": "success",
            "message": f"Updated SL & Target for {req.symbol}",
            "position": pos
        }
    except ValueError as val_err:
        return {"status": "error", "message": str(val_err)}
    except Exception as e:
        logger.error(f"Error updating SL/Target: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.post("/api/positions/square-off-all")
def api_square_off_all():
    """Square off all active open positions at current market price."""
    try:
        closed_orders = paper_engine.square_off_all(price_cache)
        return {
            "status": "success",
            "message": f"Squared off {len(closed_orders)} active positions.",
            "closed_orders": closed_orders
        }
    except Exception as e:
        logger.error(f"Error squaring off all positions: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.post("/api/portfolio/reset")
def api_reset_portfolio():
    """Reset virtual cash balance to default Rs 10,00,000 and clear all positions & orders."""
    try:
        res = paper_engine.reset_account()
        return {
            "status": "success",
            "message": f"Portfolio reset to initial virtual capital Rs {INITIAL_VIRTUAL_BALANCE:,.2f}.",
            "portfolio": res
        }
    except Exception as e:
        logger.error(f"Error resetting portfolio: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.post("/api/orders/clear")
def api_clear_orders():
    """Clear all past paper orders from history."""
    try:
        count = paper_engine.clear_orders()
        return {
            "status": "success",
            "message": f"Cleared {count} orders from history.",
            "cleared_count": count
        }
    except Exception as e:
        logger.error(f"Error clearing orders: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.get("/api/orders/export-csv")
def api_export_orders_csv():
    """Export complete simulated trade history as CSV."""
    try:
        orders = paper_engine.get_orders()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Order ID", "Timestamp", "Symbol", "Exchange", "Side",
            "Quantity", "Execution Price (INR)", "Order Type", "Status",
            "Target", "Stop Loss", "Remarks"
        ])
        for ord_item in orders:
            writer.writerow([
                ord_item.get("order_id", ""),
                ord_item.get("timestamp", ""),
                ord_item.get("symbol", ""),
                ord_item.get("exchange", "NFO"),
                ord_item.get("side", ""),
                ord_item.get("quantity", 0),
                f"{float(ord_item.get('price', 0.0)):.2f}",
                ord_item.get("order_type", "MARKET"),
                ord_item.get("status", "COMPLETE"),
                f"{float(ord_item['target']):.2f}" if ord_item.get("target") else "",
                f"{float(ord_item['stop_loss']):.2f}" if ord_item.get("stop_loss") else "",
                ord_item.get("remarks", "")
            ])
        filename = f"nifty_trade_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=output.getvalue().encode("utf-8"),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exporting orders CSV: {e}", exc_info=True)
        return Response(content=f"Error exporting CSV: {e}", status_code=500)


@app.post("/api/subscribe")
def api_subscribe(sub: TokenSubscription):
    """Subscribe new tokens for live streaming."""
    subscribe_tokens(sub.tokens)
    return {"status": "subscribed", "tokens": sub.tokens}


@app.post("/api/unsubscribe")
def api_unsubscribe(sub: TokenSubscription):
    """Unsubscribe tokens."""
    unsubscribe_tokens(sub.tokens)
    return {"status": "unsubscribed", "tokens": sub.tokens}


# ===== Paper Trading Dashboard Endpoints =====
@app.get("/api/portfolio")
def api_portfolio():
    """Get virtual available balance, active positions, and stats."""
    return paper_engine.get_portfolio()


@app.get("/api/orders")
def api_orders():
    """Get all past simulated orders."""
    return {"orders": paper_engine.get_orders()}


@app.get("/api/positions")
def api_positions():
    """Get currently open simulated positions."""
    return {"positions": paper_engine.get_positions()}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Send option-chain and portfolio snapshots to the dashboard."""
    await websocket.accept()
    expiry_index = 0

    async def receive_selection():
        nonlocal expiry_index
        try:
            while True:
                message = await websocket.receive_json()
                if "exp_idx" in message:
                    expiry_index = int(message["exp_idx"])
        except WebSocketDisconnect:
            return
        except (TypeError, ValueError):
            logger.warning("Ignoring an invalid option-expiry selection from a WebSocket client.")

    receiver = asyncio.create_task(receive_selection())
    try:
        while True:
            try:
                payload = await asyncio.to_thread(build_chain_snapshot, expiry_index)
            except Exception:
                logger.exception("Failed to build option-chain snapshot.")
                payload = {"error": "Unable to build the option chain. Check the application logs."}
            await websocket.send_json(payload)
            await asyncio.sleep(2 if "error" in payload else 0.5)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


def _get_expiry_index():
    global _expiry_index
    if _expiry_index is not None:
        return _expiry_index
    with _master_index_lock:
        if _expiry_index is None:
            _expiry_index = load_and_index_master()
    return _expiry_index


def build_chain_snapshot(expiry_idx: int = 0, radius: int = 6):
    """Build the payload shape consumed by the option-chain dashboard."""
    global _last_spot_fetch

    expiries_indexed = _get_expiry_index()
    expiries = list(expiries_indexed)
    if not expiries:
        return {"error": "No active NIFTY option expiries are available."}

    expiry_idx = max(0, min(int(expiry_idx), len(expiries) - 1))
    expiry = expiries[expiry_idx]
    entry = expiries_indexed[expiry]
    strikes = entry["sorted_strikes"]
    if not strikes:
        return {"error": f"No option strikes are available for expiry {expiry}."}

    spot = price_cache.get(NIFTY_SPOT_TOKEN)
    if not spot and stream_engine.smart_api_client is not None:
        now = time.monotonic()
        if now - _last_spot_fetch >= 2:
            _last_spot_fetch = now
            try:
                response = stream_engine.smart_api_client.ltpData(
                    "NSE", "Nifty 50", NIFTY_SPOT_TOKEN
                )
                if response.get("status") and response.get("data"):
                    spot = float(response["data"]["ltp"])
                    price_cache[NIFTY_SPOT_TOKEN] = spot
            except Exception:
                logger.exception("Failed to fetch NIFTY spot price.")
    if not spot:
        return {"error": "Waiting for a live NIFTY spot price from SmartAPI."}

    spot = float(spot)
    atm_strike = int(round(spot / 50.0) * 50)
    closest_index = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm_strike))
    selected_strikes = strikes[
        max(0, closest_index - radius):min(len(strikes), closest_index + radius + 1)
    ]

    matrix = []
    tokens = []
    for strike in selected_strikes:
        pair = entry["strikes_map"][strike]
        call = pair.get("CE")
        put = pair.get("PE")
        call_token = call["token"] if call else ""
        put_token = put["token"] if put else ""
        if call_token:
            tokens.append(call_token)
        if put_token:
            tokens.append(put_token)

        matrix.append({
            "strike": strike,
            "is_atm": strike == atm_strike,
            "ce_sym": call["symbol"] if call else "--",
            "ce_token": call_token,
            "ce_lotsize": call["lotsize"] if call else 50,
            "ce_ltp": price_cache.get(call_token, 0.0),
            "pe_sym": put["symbol"] if put else "--",
            "pe_token": put_token,
            "pe_lotsize": put["lotsize"] if put else 50,
            "pe_ltp": price_cache.get(put_token, 0.0),
        })
    subscribe_tokens(tokens)

    # Check automated Target and Stop-Loss triggers
    sl_target_alerts = paper_engine.check_sl_and_target(price_cache)

    positions = []
    holdings_value = 0.0
    for symbol, position in paper_engine.positions.items():
        token = str(position.get("token", ""))
        quantity = position["net_qty"]
        average_price = position["avg_price"]
        current_price = price_cache.get(token, average_price)
        position_value = quantity * current_price
        cost = quantity * average_price
        pnl = position_value - cost
        holdings_value += position_value
        positions.append({
            "symbol": symbol,
            "token": token,
            "qty": quantity,
            "avg_price": round(average_price, 2),
            "ltp": round(current_price, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / cost * 100, 2) if cost else 0.0,
            "lotsize": position.get("lotsize", 50),
            "target": position.get("target"),
            "stop_loss": position.get("stop_loss"),
        })

    cash = paper_engine.capital
    net_worth = cash + holdings_value
    return {
        "spot": spot,
        "atm": atm_strike,
        "expiry": expiry,
        "expiries": expiries,
        "matrix": matrix,
        "alerts": sl_target_alerts,
        "wallet": {
            "cash": round(cash, 2),
            "net_worth": round(net_worth, 2),
            "total_pnl": round(net_worth - INITIAL_VIRTUAL_BALANCE, 2),
            "positions": positions,
        },
    }