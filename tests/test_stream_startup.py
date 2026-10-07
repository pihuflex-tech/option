import threading
import unittest
from unittest.mock import patch

import src.stream_engine as stream_engine


class FakeSmartWebSocket:
    def __init__(self, auth_token, api_key, client_code, feed_token):
        if not all((auth_token, api_key, client_code, feed_token)):
            raise ValueError("websocket credentials must not be empty")
        self.on_open = None
        self.subscriptions = []
        self.opened = threading.Event()

    def connect(self):
        self.on_open(self)
        self.opened.set()

    def subscribe(self, correlation_id, mode, token_list):
        self.subscriptions.append((correlation_id, mode, token_list))

    def close_connection(self):
        return None


class StreamingStartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        stream_engine.stop_streaming()

    async def test_stream_startup_authenticates_before_constructing_websocket(self):
        with (
            patch.object(stream_engine, "SMARTAPI_KEY", "test-api-key"),
            patch.object(stream_engine, "CLIENT_CODE", "test-client"),
            patch.object(stream_engine, "MPIN", "test-mpin"),
            patch.object(stream_engine, "TOTP_SECRET", "test-totp-secret"),
            patch.object(
                stream_engine,
                "create_smartapi_session",
                return_value=(object(), "test-jwt", "test-feed"),
            ),
            patch.object(stream_engine, "SmartWebSocketV2", FakeSmartWebSocket),
        ):
            started = await stream_engine.start_streaming()

        self.assertTrue(started)
        self.assertIsNotNone(stream_engine.sws)
        self.assertTrue(stream_engine.sws.opened.wait(timeout=2))
        self.assertEqual(stream_engine.sws.subscriptions[0][2][0]["tokens"], ["99926000"])

    async def test_missing_credentials_keeps_paper_mode_available(self):
        with (
            patch.object(stream_engine, "SMARTAPI_KEY", ""),
            patch.object(stream_engine, "CLIENT_CODE", ""),
            patch.object(stream_engine, "MPIN", ""),
            patch.object(stream_engine, "TOTP_SECRET", ""),
            patch.object(stream_engine, "create_smartapi_session") as login,
        ):
            started = await stream_engine.start_streaming()

        self.assertFalse(started)
        login.assert_not_called()
