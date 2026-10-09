import logging
import time
from typing import Dict, Optional, Any
import requests

logger = logging.getLogger("MegaBullClient")

class MegaBullClient:
    BASE_URL = "https://api.megabull.in"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "MegaBullAlgoBridge/1.0",
        }
        self._instruments_cache: Dict[str, str] = {}
        self._cache_timestamp: float = 0

    def refresh_instruments(self) -> Dict[str, str]:
        """Fetch all tradable instruments and build symbol -> instrumentToken map."""
        try:
            url = f"{self.BASE_URL}/api/marketwatch/instruments"
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                cache = {}
                for item in data:
                    sym = item.get("tradingSymbol", "").upper().strip()
                    token = item.get("instrumentToken")
                    if sym and token:
                        cache[sym] = str(token)
                self._instruments_cache = cache
                self._cache_timestamp = time.time()
                logger.info(f"Loaded {len(cache)} instruments from MegaBull.")
                return cache
            else:
                logger.error(f"Failed to fetch MegaBull instruments: {resp.status_code} - {resp.text}")
                return self._instruments_cache
        except Exception as e:
            logger.error(f"Error fetching MegaBull instruments: {e}")
            return self._instruments_cache

    def get_token_for_symbol(self, symbol: str) -> Optional[str]:
        """Get instrumentToken for a symbol (e.g. 'ETERNAL', 'RELIANCE')."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        # Refresh cache if empty or older than 1 hour
        if not self._instruments_cache or (time.time() - self._cache_timestamp > 3600):
            self.refresh_instruments()

        token = self._instruments_cache.get(clean_sym)
        if not token:
            # Try partial matching if exact match not found
            for k, v in self._instruments_cache.items():
                if k.startswith(clean_sym) or clean_sym in k:
                    logger.info(f"Fuzzy matched '{clean_sym}' to instrument '{k}' (Token: {v})")
                    return v
        return token

    def place_order(
        self,
        symbol: str,
        action: str,  # "BUY" or "SELL"
        qty: int,
        duration: str = "MIS",  # "MIS" (Intraday) or "CNC" (Delivery)
        order_type: str = "MKT",  # "MKT", "LIMIT", "SL"
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Place an order in MegaBull Paper Trading."""
        token = self.get_token_for_symbol(symbol)
        if not token:
            raise ValueError(f"Could not find MegaBull instrumentToken for symbol '{symbol}'.")

        payload = {
            "instrumentToken": str(token),
            "qty": int(qty),
            "type": action.upper(),
            "duration": duration.upper(),
            "orderType": order_type.upper(),
        }

        if order_type.upper() == "LIMIT" and price:
            payload["price"] = float(price)
        if order_type.upper() == "SL" and trigger_price:
            payload["triggerPrice"] = float(trigger_price)

        url = f"{self.BASE_URL}/api/order/buysell"
        logger.info(f"Submitting MegaBull Order: {payload}")
        resp = requests.post(url, headers=self.headers, json=payload, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"MegaBull Order Placed Successfully: ID {data.get('id')}")
            return data
        else:
            logger.error(f"MegaBull Order Failed: {resp.status_code} - {resp.text}")
            raise RuntimeError(f"MegaBull API Error ({resp.status_code}): {resp.text}")

    def get_positions(self) -> list:
        """Get open positions."""
        url = f"{self.BASE_URL}/api/position/my"
        resp = requests.get(url, headers=self.headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return []

    def close_position(self, symbol: str) -> Dict[str, Any]:
        """Close open position for a given symbol."""
        positions = self.get_positions()
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()

        for pos in positions:
            pos_name = pos.get("instrumentName", "").upper()
            if clean_sym in pos_name or clean_sym == pos.get("tradingSymbol", "").upper():
                qty = pos.get("qty", 0)
                pos_type = pos.get("type", "BUY").upper()
                if qty > 0:
                    # Reverse side to close
                    close_action = "SELL" if pos_type == "BUY" else "BUY"
                    token = pos.get("instrumentToken")
                    payload = {
                        "instrumentToken": str(token),
                        "qty": int(qty),
                        "type": close_action,
                        "duration": pos.get("duration", "MIS"),
                        "orderType": "MKT",
                    }
                    url = f"{self.BASE_URL}/api/order/buysell"
                    resp = requests.post(url, headers=self.headers, json=payload, timeout=10)
                    return resp.json() if resp.status_code == 200 else {"error": resp.text}

        return {"message": f"No open position found in MegaBull for {symbol}"}
