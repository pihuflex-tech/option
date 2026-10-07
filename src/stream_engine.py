import asyncio
import threading
import logging
from typing import Any, Callable

from config.settings import (
    CLIENT_CODE,
    MPIN,
    NIFTY_SPOT_TOKEN,
    SMARTAPI_KEY,
    TOTP_SECRET,
)
from src.auth import create_smartapi_session

try:
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
except Exception:  # pragma: no cover - optional dependency in local/offline tests
    SmartWebSocketV2 = None

logger = logging.getLogger(__name__)

price_cache = {}          # {token_str: float_price}
subscribed_tokens = set()
pending_tokens = set()
sws = None
ws_connected = False
smart_api_client = None
_subscription_lock = threading.Lock()


def start_websocket_listener(
    jwt_token: str,
    feed_token: str,
    broadcast_callback: Callable[[dict[str, Any]], Any] | None = None,
    event_loop: asyncio.AbstractEventLoop | None = None,
):
    global sws

    if SmartWebSocketV2 is None:
        logger.error("SmartAPI websocket package is unavailable; live streaming is disabled.")
        return False

    credentials = (jwt_token, feed_token, SMARTAPI_KEY, CLIENT_CODE)
    if any(not value or not value.strip() for value in credentials):
        logger.error("SmartAPI returned incomplete websocket credentials; live streaming is disabled.")
        return False

    if broadcast_callback is not None and event_loop is None:
        raise ValueError("event_loop is required when a broadcast callback is provided.")

    def on_data(wsapp, data):
        try:
            raw_price = data.get("last_traded_price")
            raw_token = data.get("token")
            if raw_price is None or raw_token is None:
                return

            token = str(raw_token).strip()
            tick = dict(data)
            tick["token"] = token
            tick["last_traded_price"] = float(raw_price) / 100.0
            price_cache[token] = tick["last_traded_price"]

            if broadcast_callback is not None and event_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    broadcast_callback(tick), event_loop
                )
        except Exception:
            logger.exception("Failed to process SmartAPI market tick.")

    def on_open(wsapp):
        global ws_connected, subscribed_tokens
        ws_connected = True
        logger.info("SmartAPI websocket connected.")
        if sws is None:
            return

        try:
            sws.subscribe(
                "spot_idx01",
                3,
                [{"exchangeType": 1, "tokens": [NIFTY_SPOT_TOKEN]}],
            )
            with _subscription_lock:
                queued = sorted(pending_tokens)
            if queued:
                sws.subscribe(
                    "chain_sub1",
                    3,
                    [{"exchangeType": 2, "tokens": queued}],
                )
                with _subscription_lock:
                    subscribed_tokens.update(queued)
                    pending_tokens.difference_update(queued)
        except Exception:
            logger.exception("Failed to subscribe to SmartAPI market tokens.")

    def on_error(wsapp, err):
        logger.error("SmartAPI websocket error: %s", err)

    def on_close(wsapp):
        global ws_connected
        ws_connected = False
        with _subscription_lock:
            pending_tokens.update(subscribed_tokens)
            subscribed_tokens.clear()
        logger.warning("SmartAPI websocket disconnected.")

    try:
        sws = SmartWebSocketV2(jwt_token, SMARTAPI_KEY, CLIENT_CODE, feed_token)
        sws.on_data = on_data
        sws.on_open = on_open
        sws.on_error = on_error
        sws.on_close = on_close
    except Exception:
        logger.exception("Could not initialize SmartAPI websocket; live streaming is disabled.")
        sws = None
        return False

    def connect():
        global ws_connected
        try:
            sws.connect()
        except Exception:
            ws_connected = False
            logger.exception("SmartAPI websocket connection failed.")

    ws_thread = threading.Thread(target=connect, daemon=True, name="smartapi-websocket")
    ws_thread.start()
    return True


async def start_streaming(broadcast_callback=None):
    """Authenticate and start the broker stream; keep paper trading available on failure."""
    global smart_api_client

    if not all((SMARTAPI_KEY, CLIENT_CODE, MPIN, TOTP_SECRET)):
        logger.warning(
            "SmartAPI credentials are incomplete. Starting in paper-trading mode without live prices."
        )
        return False

    try:
        smart_api, jwt_token, feed_token = await asyncio.to_thread(
            create_smartapi_session
        )
    except Exception:
        logger.exception("SmartAPI login failed; starting without live market streaming.")
        return False

    if smart_api is None or not jwt_token or not feed_token:
        logger.error("SmartAPI login did not return a valid session; live streaming is disabled.")
        return False

    smart_api_client = smart_api
    return start_websocket_listener(
        jwt_token,
        feed_token,
        broadcast_callback,
        asyncio.get_running_loop(),
    )


def stop_streaming():
    global sws, ws_connected, smart_api_client
    if sws is not None:
        try:
            sws.close_connection()
        except Exception:
            logger.exception("Failed to close SmartAPI websocket cleanly.")
    sws = None
    smart_api_client = None
    ws_connected = False
    with _subscription_lock:
        subscribed_tokens.clear()
        pending_tokens.clear()


def subscribe_tokens(tokens):
    normalized_tokens = {str(token).strip() for token in tokens if str(token).strip()}
    with _subscription_lock:
        new_sub = normalized_tokens - subscribed_tokens
        pending_tokens.update(new_sub)
        should_send = bool(new_sub) and ws_connected and sws is not None

    if should_send:
        try:
            sws.subscribe(
                "chain_sub1",
                3,
                [{"exchangeType": 2, "tokens": sorted(new_sub)}],
            )
            with _subscription_lock:
                subscribed_tokens.update(new_sub)
                pending_tokens.difference_update(new_sub)
        except Exception:
            logger.exception("Failed to subscribe to SmartAPI option tokens.")
    with _subscription_lock:
        return sorted(subscribed_tokens | pending_tokens)


def unsubscribe_tokens(tokens):
    normalized_tokens = {str(token).strip() for token in tokens if str(token).strip()}
    with _subscription_lock:
        to_unsubscribe = normalized_tokens & subscribed_tokens
        pending_tokens.difference_update(normalized_tokens)

    if to_unsubscribe and ws_connected and sws is not None:
        try:
            sws.unsubscribe(
                "chain_uns1",
                3,
                [{"exchangeType": 2, "tokens": sorted(to_unsubscribe)}],
            )
        except Exception:
            logger.exception("Failed to unsubscribe from SmartAPI option tokens.")
        else:
            with _subscription_lock:
                subscribed_tokens.difference_update(to_unsubscribe)
    elif to_unsubscribe:
        with _subscription_lock:
            subscribed_tokens.difference_update(to_unsubscribe)

    with _subscription_lock:
        return sorted(subscribed_tokens | pending_tokens)