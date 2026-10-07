import logging

import pyotp
from SmartApi import SmartConnect
from config.settings import SMARTAPI_KEY, CLIENT_CODE, MPIN, TOTP_SECRET

logger = logging.getLogger(__name__)


def create_smartapi_session():
    """Initializes and returns authenticated SmartConnect session and tokens."""
    if not all((SMARTAPI_KEY, CLIENT_CODE, MPIN, TOTP_SECRET)):
        logger.warning("SmartAPI credentials are incomplete; login was not attempted.")
        return None, None, None

    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        smart_api = SmartConnect(api_key=SMARTAPI_KEY)
        data = smart_api.generateSession(CLIENT_CODE, MPIN, totp)
        
        if not data.get("status"):
            logger.error("SmartAPI login failed: %s", data.get("message", "unknown broker error"))
            return None, None, None

        session_data = data.get("data") or {}
        jwt_token = session_data.get("jwtToken")
        feed_token = smart_api.getfeedToken()
        if not jwt_token or not feed_token:
            logger.error("SmartAPI login response did not include both websocket tokens.")
            return None, None, None

        logger.info("Angel One session initialized.")
        return smart_api, jwt_token, feed_token
    except Exception as e:
        logger.exception("Connection error during SmartAPI login: %s", e)
        return None, None, None