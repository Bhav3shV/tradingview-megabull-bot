import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import uvicorn

import config
from megabull_client import MegaBullClient

# Setup structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("TradingBridge")

app = FastAPI(
    title="TradingView to MegaBull Execution Bridge",
    description="Automated Webhook Bridge routing TradingView alerts to MegaBull Paper Trading",
    version="2.0.0",
)

# Initialize MegaBull client if API key is provided
megabull_client = None
if config.TARGET_BROKER == "megabull":
    if not config.SIMULATION_MODE:
        try:
            megabull_client = MegaBullClient(config.MEGABULL_API_KEY)
            logger.info("MegaBull Paper Trading Client initialized with live API key!")
        except Exception as e:
            logger.error(f"Error initializing MegaBull Client: {e}. Falling back to simulation.")
            config.SIMULATION_MODE = True
    else:
        logger.info("MegaBull Paper Trading Bridge running in SIMULATION/DEV mode (waiting for MEGABULL_API_KEY).")


class WebhookPayload(BaseModel):
    secret: str = Field(..., description="Authentication passphrase")
    action: str = Field(..., description="'buy', 'sell', or 'close'")
    symbol: str = Field(..., description="Ticker symbol (e.g. ETERNAL, RELIANCE, TATAMOTORS, NIFTY)")
    qty: float = Field(default=1.0, gt=0, description="Order quantity")
    sl: Optional[float] = Field(default=None, description="Stop Loss trigger price")
    tp: Optional[float] = Field(default=None, description="Take Profit target price")
    duration: Optional[str] = Field(default="MIS", description="Order duration: 'MIS' (intraday) or 'CNC' (delivery)")


@app.get("/health")
def health_check():
    return {
        "status": "online",
        "broker": config.TARGET_BROKER,
        "mode": "simulation" if config.SIMULATION_MODE else "live_megabull_paper",
        "megabull_connected": megabull_client is not None and not config.SIMULATION_MODE,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/webhook")
@app.post("/tradingview-webhook")
async def handle_tradingview_alert(payload: WebhookPayload):
    # 1. Security Check
    if payload.secret != config.WEBHOOK_SECRET:
        logger.warning(f"Unauthorized alert attempt with invalid secret: {payload.secret}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication secret token",
        )

    action = payload.action.lower()
    symbol = payload.symbol.upper()
    qty = int(payload.qty)
    duration = (payload.duration or "MIS").upper()

    logger.info(
        f"[TRADINGVIEW ALERT] Action: {action.upper()} | Symbol: {symbol} | Qty: {qty} | Duration: {duration} | SL: {payload.sl} | TP: {payload.tp}"
    )

    # 2. Local Simulation Mode (Used if user hasn't added MegaBull API Key yet)
    if config.SIMULATION_MODE or megabull_client is None:
        sim_order_id = f"mb-sim-{uuid.uuid4().hex[:8]}"
        logger.info(
            f"[MEGABULL SIMULATION FILLED] {action.upper()} {qty} of {symbol} (Sim-ID: {sim_order_id}) at market"
        )
        if payload.sl:
            logger.info(f"   └── Attached Stop-Loss: ₹{payload.sl:.2f}")
        if payload.tp:
            logger.info(f"   └── Attached Target: ₹{payload.tp:.2f}")

        return {
            "status": "success",
            "target": "megabull_simulation",
            "order_id": sim_order_id,
            "action": action,
            "symbol": symbol,
            "qty": qty,
            "duration": duration,
            "sl": payload.sl,
            "tp": payload.tp,
            "note": "Executed in local MegaBull simulator. Add your MEGABULL_API_KEY in .env to place live orders on MegaBull app.",
        }

    # 3. Live Execution on MegaBull Paper Trading API
    try:
        if action == "close":
            logger.info(f"Squaring off position in {symbol} on MegaBull...")
            close_resp = megabull_client.close_position(symbol)
            return {"status": "success", "target": "megabull", "response": close_resp}

        order_side = "BUY" if action == "buy" else "SELL"
        order_resp = megabull_client.place_order(
            symbol=symbol,
            action=order_side,
            qty=qty,
            duration=duration,
            order_type="MKT",
        )

        logger.info(f"[MEGABULL API SUCCESS] Order ID: {order_resp.get('id')}")
        return {
            "status": "success",
            "target": "megabull",
            "order_id": order_resp.get("id"),
            "symbol": symbol,
            "action": order_side,
            "qty": qty,
            "response": order_resp,
        }

    except Exception as exc:
        logger.error(f"Error executing on MegaBull API: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MegaBull execution error: {str(exc)}")


if __name__ == "__main__":
    logger.info(f"Starting MegaBull Webhook Bridge on http://{config.HOST}:{config.PORT}")
    uvicorn.run("webhook_bridge:app", host=config.HOST, port=config.PORT, reload=False)
