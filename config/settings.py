import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

SMARTAPI_KEY = os.getenv("SMARTAPI_KEY", "")
CLIENT_CODE = os.getenv("CLIENT_CODE", "")
MPIN = os.getenv("MPIN", "")
TOTP_SECRET = os.getenv("TOTP_SECRET", "")

SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))

CACHE_FILE = str(PROJECT_ROOT / "scrip_master.json")
NIFTY_SPOT_TOKEN = "99926000"
INITIAL_VIRTUAL_BALANCE = 1000000.0  # ₹10,00,000 Starting Virtual Capital