import unittest
from src.paper_engine import PaperTradingEngine

class PaperFeaturesTest(unittest.TestCase):
    def setUp(self):
        # In-memory storage file
        self.engine = PaperTradingEngine(storage_file="tests/test_trades.json")
        self.engine.capital = 100000.0
        self.engine.orders = []
        self.engine.positions = {}

    def tearDown(self):
        import os
        if os.path.exists("tests/test_trades.json"):
            os.remove("tests/test_trades.json")

    def test_target_and_stop_loss_order_and_triggers(self):
        # 1. Place order with target 200 and stop loss 90
        order = self.engine.place_order(
            symbol="NIFTY26OCT22500CE",
            side="BUY",
            quantity=50,
            price=100.0,
            token="12345",
            target=120.0,
            stop_loss=80.0
        )
        self.assertEqual(order["status"], "COMPLETE")
        self.assertEqual(order["target"], 120.0)
        self.assertEqual(order["stop_loss"], 80.0)

        pos = self.engine.positions.get("NIFTY26OCT22500CE")
        self.assertIsNotNone(pos)
        self.assertEqual(pos["target"], 120.0)
        self.assertEqual(pos["stop_loss"], 80.0)

        # 2. Check no trigger when price is 110 (between SL and Target)
        triggers = self.engine.check_sl_and_target({"12345": 110.0})
        self.assertEqual(len(triggers), 0)
        self.assertIn("NIFTY26OCT22500CE", self.engine.positions)

        # 3. Check trigger when price hits target (120+)
        triggers = self.engine.check_sl_and_target({"12345": 125.0})
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["type"], "TARGET_HIT")
        self.assertNotIn("NIFTY26OCT22500CE", self.engine.positions)

    def test_clear_orders(self):
        self.engine.place_order(symbol="NIFTY26OCT22500CE", side="BUY", quantity=50, price=100.0, token="12345")
        self.assertEqual(len(self.engine.orders), 1)
        cleared = self.engine.clear_orders()
        self.assertEqual(cleared, 1)
        self.assertEqual(len(self.engine.orders), 0)

if __name__ == "__main__":
    unittest.main()