import json
import logging
import math
import os
import uuid
from datetime import datetime
from typing import Dict, List
from config.settings import INITIAL_VIRTUAL_BALANCE, PROJECT_ROOT

logger = logging.getLogger(__name__)

class PaperTradingEngine:
    def __init__(self, storage_file: str | None = None):
        self.storage_file = storage_file or str(PROJECT_ROOT / "paper_trades.json")
        self.capital = float(INITIAL_VIRTUAL_BALANCE)
        self.orders: List[Dict] = []
        self.positions: Dict[str, Dict] = {}  # key: symbol
        self._load_state()

    def _load_state(self):
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, "r") as f:
                    data = json.load(f)
                    self.capital = float(data.get("capital", INITIAL_VIRTUAL_BALANCE))
                    self.orders = data.get("orders", [])
                    self.positions = data.get("positions", {})
            except Exception as e:
                logger.error(f"Failed to load paper trade state: {e}")

    def _save_state(self):
        try:
            with open(self.storage_file, "w") as f:
                json.dump({
                    "capital": self.capital,
                    "orders": self.orders,
                    "positions": self.positions
                }, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save paper trade state: {e}")

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
        exchange: str = "NFO",
        token: str = "",
        lotsize: int = 50,
        target: float | None = None,
        stop_loss: float | None = None,
        remarks: str = "SIMULATED_PAPER_TRADE"
    ) -> Dict:
        side = side.upper().strip()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: '{side}'. Must be BUY or SELL.")
        if not symbol or not symbol.strip():
            raise ValueError("Symbol must not be empty.")
        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0.")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Execution price must be a finite number greater than 0.")
        if lotsize <= 0:
            raise ValueError("Lot size must be greater than 0.")

        total_value = float(price * quantity)
        symbol = symbol.strip()

        # Capital verification for BUY
        if side == "BUY" and self.capital < total_value:
            raise ValueError(f"Insufficient funds: Required Rs {total_value:.2f}, Available Rs {self.capital:.2f}")

        # Holding verification for SELL
        if side == "SELL":
            current_qty = self.positions.get(symbol, {}).get("net_qty", 0)
            if current_qty < quantity:
                raise ValueError(f"Insufficient quantity to sell: Holding {current_qty}, requested {quantity}")

        order_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        tgt_val = float(target) if (target is not None and float(target) > 0) else None
        sl_val = float(stop_loss) if (stop_loss is not None and float(stop_loss) > 0) else None

        order_record = {
            "order_id": order_id,
            "timestamp": timestamp,
            "symbol": symbol,
            "token": str(token),
            "exchange": exchange,
            "side": side,
            "quantity": quantity,
            "price": round(price, 2),
            "order_type": order_type,
            "status": "COMPLETE",
            "remarks": remarks,
            "target": tgt_val,
            "stop_loss": sl_val
        }
        self.orders.append(order_record)

        if side == "BUY":
            self.capital -= total_value
            if symbol not in self.positions:
                self.positions[symbol] = {
                    "symbol": symbol,
                    "token": str(token),
                    "exchange": exchange,
                    "net_qty": quantity,
                    "avg_price": round(price, 2),
                    "total_cost": total_value,
                    "lotsize": lotsize,
                    "target": tgt_val,
                    "stop_loss": sl_val,
                }
            else:
                pos = self.positions[symbol]
                new_qty = pos["net_qty"] + quantity
                new_cost = pos["total_cost"] + total_value
                pos["net_qty"] = new_qty
                pos["total_cost"] = new_cost
                pos["avg_price"] = round(new_cost / new_qty, 2)
                pos["token"] = str(token or pos.get("token", ""))
                pos["lotsize"] = lotsize
                if tgt_val is not None:
                    pos["target"] = tgt_val
                if sl_val is not None:
                    pos["stop_loss"] = sl_val
        else:  # SELL
            self.capital += total_value
            pos = self.positions[symbol]
            new_qty = pos["net_qty"] - quantity
            if new_qty <= 0:
                del self.positions[symbol]
            else:
                pos["net_qty"] = new_qty
                pos["total_cost"] = new_qty * pos["avg_price"]

        self._save_state()
        return order_record

    def update_sl_target(
        self,
        symbol: str,
        target: float | None = None,
        stop_loss: float | None = None,
    ) -> Dict:
        symbol = symbol.strip()
        if symbol not in self.positions:
            raise ValueError(f"No open position found for {symbol}.")
        pos = self.positions[symbol]
        pos["target"] = float(target) if (target is not None and float(target) > 0) else None
        pos["stop_loss"] = float(stop_loss) if (stop_loss is not None and float(stop_loss) > 0) else None
        self._save_state()
        return pos

    def check_sl_and_target(self, price_cache: Dict[str, float]) -> List[Dict]:
        triggered = []
        for symbol, pos in list(self.positions.items()):
            token = str(pos.get("token", ""))
            ltp = float(price_cache.get(token, 0.0))
            if ltp <= 0:
                continue

            net_qty = pos.get("net_qty", 0)
            if net_qty <= 0:
                continue

            target = pos.get("target")
            stop_loss = pos.get("stop_loss")

            # Check Target Hit (for long position: LTP >= target)
            if target is not None and float(target) > 0 and ltp >= float(target):
                try:
                    order = self.place_order(
                        symbol=symbol,
                        side="SELL",
                        quantity=net_qty,
                        price=ltp,
                        order_type="MARKET",
                        exchange=pos.get("exchange", "NFO"),
                        token=token,
                        lotsize=pos.get("lotsize", 50),
                        remarks=f"TARGET_HIT (Target: Rs {float(target):.2f})"
                    )
                    triggered.append({
                        "type": "TARGET_HIT",
                        "symbol": symbol,
                        "price": ltp,
                        "target": float(target),
                        "order": order
                    })
                    logger.info(f"Target Hit for {symbol} at {ltp} (Target: {target})")
                except Exception as e:
                    logger.error(f"Error executing auto target square-off for {symbol}: {e}")
                continue

            # Check Stop-Loss Hit (for long position: LTP <= stop_loss)
            if stop_loss is not None and float(stop_loss) > 0 and ltp <= float(stop_loss):
                try:
                    order = self.place_order(
                        symbol=symbol,
                        side="SELL",
                        quantity=net_qty,
                        price=ltp,
                        order_type="MARKET",
                        exchange=pos.get("exchange", "NFO"),
                        token=token,
                        lotsize=pos.get("lotsize", 50),
                        remarks=f"STOP_LOSS_HIT (SL: Rs {float(stop_loss):.2f})"
                    )
                    triggered.append({
                        "type": "STOP_LOSS_HIT",
                        "symbol": symbol,
                        "price": ltp,
                        "stop_loss": float(stop_loss),
                        "order": order
                    })
                    logger.info(f"Stop-Loss Hit for {symbol} at {ltp} (SL: {stop_loss})")
                except Exception as e:
                    logger.error(f"Error executing auto stop-loss square-off for {symbol}: {e}")
                continue

        return triggered

    def square_off_all(self, price_cache: Dict[str, float] | None = None) -> List[Dict]:
        price_cache = price_cache or {}
        closed = []
        for symbol, pos in list(self.positions.items()):
            token = str(pos.get("token", ""))
            current_price = price_cache.get(token, pos.get("avg_price", 0.0))
            if current_price <= 0:
                current_price = pos.get("avg_price", 0.0)
            order = self.place_order(
                symbol=symbol,
                side="SELL",
                quantity=pos.get("net_qty", 0),
                price=current_price,
                order_type="MARKET",
                exchange=pos.get("exchange", "NFO"),
                token=token,
                lotsize=pos.get("lotsize", 50),
                remarks="MANUAL_SQUARE_OFF_ALL"
            )
            closed.append(order)
        return closed

    def reset_account(self) -> Dict:
        self.capital = float(INITIAL_VIRTUAL_BALANCE)
        self.orders = []
        self.positions = {}
        self._save_state()
        return self.get_portfolio()

    def clear_orders(self) -> int:
        count = len(self.orders)
        self.orders = []
        self._save_state()
        return count

    def get_portfolio(self) -> Dict:
        return {
            "mode": "PAPER_TRADING",
            "available_capital": round(self.capital, 2),
            "open_positions": list(self.positions.values()),
            "total_orders": len(self.orders)
        }

    def get_orders(self) -> List[Dict]:
        return list(reversed(self.orders))

    def get_positions(self) -> List[Dict]:
        return list(self.positions.values())

paper_engine = PaperTradingEngine()