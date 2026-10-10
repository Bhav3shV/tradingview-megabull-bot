import logging
import time
from typing import Dict, Optional, Any
import requests

logger = logging.getLogger("MegaBullClient")

# Well-known standard NSE Instrument Tokens (Zero-failure fallback for top stocks)
STANDARD_NSE_TOKENS: Dict[str, str] = {
    "NIFTY": "256265",
    "NIFTY 50": "256265",
    "BANKNIFTY": "260105",
    "RELIANCE": "738561",
    "HDFCBANK": "341249",
    "ICICIBANK": "1270529",
    "SBIN": "779521",
    "TCS": "2953217",
    "INFY": "408065",
    "BHARTIARTL": "2714625",
    "KOTAKBANK": "492033",
    "ITC": "424961",
    "LT": "2939649",
    "AXISBANK": "1510401",
    "TATASTEEL": "895745",
    "BAJFINANCE": "81153",
    "MARUTI": "2815745",
    "TITAN": "897537",
    "ADANIENT": "6401",
    "M&M": "519937",
    "WIPRO": "969473",
}

class MegaBullClient:
    BASE_URL = "https://api.megabull.in"

    def __init__(self, api_key: str):
        self.api_key = str(api_key).strip().strip('"').strip("'")
        self.headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "MegaBullAlgoBridge/2.0",
        }
        self._instruments_cache: Dict[str, str] = dict(STANDARD_NSE_TOKENS)
        self._cache_timestamp: float = 0
        self.last_api_error: Optional[str] = None

    def refresh_instruments(self) -> Dict[str, str]:
        """Fetch all tradable instruments from MegaBull API."""
        try:
            url = f"{self.BASE_URL}/api/marketwatch/instruments"
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for item in data:
                        sym = str(item.get("tradingSymbol") or item.get("instrumentName") or "").upper().strip()
                        token = item.get("instrumentToken")
                        if sym and token:
                            self._instruments_cache[sym] = str(token)
                    self._cache_timestamp = time.time()
                    logger.info(f"Loaded {len(self._instruments_cache)} instruments from MegaBull API.")
                    return self._instruments_cache

            # Try fallback endpoint /api/marketwatch/my
            my_url = f"{self.BASE_URL}/api/marketwatch/my"
            resp_my = requests.get(my_url, headers=self.headers, timeout=10)
            if resp_my.status_code == 200:
                data = resp_my.json()
                if isinstance(data, list):
                    for item in data:
                        sym = str(item.get("tradingSymbol") or item.get("displayName") or "").upper().strip()
                        token = item.get("instrumentToken")
                        if sym and token:
                            self._instruments_cache[sym] = str(token)
                    return self._instruments_cache

            self.last_api_error = f"Instruments API error: Status {resp.status_code} - {resp.text}"
            logger.warning(f"MegaBull instrument API responded with {resp.status_code}: {resp.text}")
            return self._instruments_cache

        except Exception as e:
            self.last_api_error = f"Exception fetching instruments: {str(e)}"
            logger.error(f"Error fetching MegaBull instruments: {e}")
            return self._instruments_cache

    def get_token_for_symbol(self, symbol: str) -> Optional[str]:
        """Resolve instrumentToken for a symbol with fallback support."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        
        # Check cache / standard tokens first
        token = self._instruments_cache.get(clean_sym)
        if token:
            return token

        # Refresh cache if not found
        if time.time() - self._cache_timestamp > 300:
            self.refresh_instruments()
            token = self._instruments_cache.get(clean_sym)
            if token:
                return token

        # Fuzzy match
        for k, v in self._instruments_cache.items():
            if k.startswith(clean_sym) or clean_sym in k:
                return v

        return None

    def place_order(
        self,
        symbol: str,
        action: str,  # "BUY" or "SELL"
        qty: int,
        duration: str = "CNC",  # "CNC" (delivery/holding) or "MIS" (intraday)
        order_type: str = "MKT",  # "MKT", "LIMIT", "SL"
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Place an order in MegaBull Paper Trading."""
        token = self.get_token_for_symbol(symbol)
        if not token:
            raise ValueError(f"Could not find MegaBull instrumentToken for '{symbol}'.")

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
        logger.info(f"Submitting MegaBull Order to {url}: {payload}")
        resp = requests.post(url, headers=self.headers, json=payload, timeout=12)

        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"MegaBull Order Placed Successfully: {data}")
            return data
        else:
            err_msg = f"MegaBull API Error ({resp.status_code}): {resp.text}"
            logger.error(err_msg)
            raise RuntimeError(err_msg)

    def get_positions(self) -> list:
        url = f"{self.BASE_URL}/api/position/my"
        resp = requests.get(url, headers=self.headers, timeout=10)
        return resp.json() if resp.status_code == 200 else []

    def close_position(self, symbol: str) -> Dict[str, Any]:
        positions = self.get_positions()
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()

        for pos in positions:
            pos_name = pos.get("instrumentName", "").upper()
            if clean_sym in pos_name or clean_sym == pos.get("tradingSymbol", "").upper():
                qty = pos.get("qty", 0)
                pos_type = pos.get("type", "BUY").upper()
                if qty > 0:
                    close_action = "SELL" if pos_type == "BUY" else "BUY"
                    token = pos.get("instrumentToken")
                    payload = {
                        "instrumentToken": str(token),
                        "qty": int(qty),
                        "type": close_action,
                        "duration": pos.get("duration", "CNC"),
                        "orderType": "MKT",
                    }
                    url = f"{self.BASE_URL}/api/order/buysell"
                    resp = requests.post(url, headers=self.headers, json=payload, timeout=10)
                    return resp.json() if resp.status_code == 200 else {"error": resp.text}

        return {"message": f"No open position found in MegaBull for {symbol}"}
