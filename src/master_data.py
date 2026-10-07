import os
import requests
import pandas as pd
from datetime import datetime
from config.settings import CACHE_FILE

TOKEN_TO_SYMBOL = {}


def _refresh_symbol_index():
    """Builds a lightweight token -> symbol lookup from the cached scrip master."""
    global TOKEN_TO_SYMBOL

    if not os.path.exists(CACHE_FILE):
        return TOKEN_TO_SYMBOL

    try:
        df = pd.read_json(CACHE_FILE)
        if df.empty:
            return TOKEN_TO_SYMBOL

        for _, row in df.iterrows():
            token = str(row.get("token", "")).strip()
            symbol = str(row.get("symbol", "")).strip()
            if token and symbol:
                TOKEN_TO_SYMBOL[token] = symbol
    except Exception:
        return TOKEN_TO_SYMBOL

    return TOKEN_TO_SYMBOL


def get_symbol_by_token(token):
    """Resolves a contract's symbol from the cached Angel One scrip master."""
    if token is None:
        return None

    token_str = str(token).strip()
    if not token_str:
        return None

    if token_str in TOKEN_TO_SYMBOL:
        return TOKEN_TO_SYMBOL[token_str]

    return _refresh_symbol_index().get(token_str)


def search_scrip(query: str, limit: int = 20):
    """Searches scrip master entries by symbol or name."""
    if not query:
        return []

    q = str(query).strip().upper()
    if len(q) < 2:
        return []

    if not os.path.exists(CACHE_FILE):
        return []

    try:
        df = pd.read_json(CACHE_FILE)
        if df.empty:
            return []

        search_cols = df.astype({"symbol": "string", "name": "string"}).fillna("")
        mask = search_cols["symbol"].str.contains(q, case=False, na=False) | search_cols["name"].str.contains(q, case=False, na=False)
        matches = df.loc[mask].head(limit)

        results = []
        for _, row in matches.iterrows():
            results.append({
                "symbol": str(row.get("symbol", "")),
                "token": str(row.get("token", "")),
                "name": str(row.get("name", "")),
                "expiry": row.get("expiry"),
                "strike": row.get("strike"),
                "instrumenttype": row.get("instrumenttype"),
            })
        return results
    except Exception:
        return []


def load_and_index_master():
    """Downloads Scrip Master and indexes active Nifty options into O(1) nested dicts."""
    need_download = True
    if os.path.exists(CACHE_FILE):
        file_mtime = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE)).date()
        if file_mtime == datetime.now().date():
            need_download = False

    if need_download:
        print("Caching today's Scrip Master from Angel One...")
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        res = requests.get(url, timeout=30)
        with open(CACHE_FILE, "wb") as f:
            f.write(res.content)
        print("Scrip Master cached locally.")

    df = pd.read_json(CACHE_FILE)
    opts = df[(df["name"] == "NIFTY") & (df["instrumenttype"] == "OPTIDX")].copy()
    opts["strike_clean"] = pd.to_numeric(opts["strike"], errors="coerce") / 100.0
    opts["expiry_dt"] = pd.to_datetime(opts["expiry"], format="%d%b%Y", errors="coerce")

    today_ts = pd.to_datetime(datetime.now().date())
    opts = opts[opts["expiry_dt"] >= today_ts].sort_values("expiry_dt")

    expiries_indexed = {}
    for exp_str, grp in opts.groupby("expiry", sort=False):
        strikes_map = {}
        for _, row in grp.iterrows():
            token = str(row["token"])
            symbol = str(row["symbol"])
            TOKEN_TO_SYMBOL[token] = symbol

            stk = int(row["strike_clean"])
            if stk not in strikes_map:
                strikes_map[stk] = {"CE": None, "PE": None}
            opt_type = "CE" if str(row["symbol"]).endswith("CE") else "PE"
            strikes_map[stk][opt_type] = {
                "token": token,
                "symbol": symbol,
                "lotsize": int(row.get("lotsize", 50))
            }

        sorted_stks = sorted(strikes_map.keys())
        expiries_indexed[exp_str] = {
            "sorted_strikes": sorted_stks,
            "strikes_map": strikes_map
        }

    return expiries_indexed