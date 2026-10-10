import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import uvicorn

import config
from megabull_client import MegaBullClient
from cloud_worker import start_cloud_worker_thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("TradingBridge")

app = FastAPI(
    title="TradingView & Autonomous MegaBull Cloud System",
    description="24/7 Cloud Automated Trading System for Indian Markets",
    version="3.0.0",
)

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
        logger.info("MegaBull Paper Trading Bridge running in SIMULATION/DEV mode.")

# Start the 24/7 Autonomous Cloud Trader Thread on Render
@app.on_event("startup")
def on_startup():
    logger.info("App starting up. Launching 24/7 autonomous cloud trader...")
    start_cloud_worker_thread()


class WebhookPayload(BaseModel):
    secret: str = Field(..., description="Authentication passphrase")
    action: str = Field(..., description="'buy', 'sell', or 'close'")
    symbol: str = Field(..., description="Ticker symbol (e.g. HDFCBANK, RELIANCE, NIFTY)")
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
        "autonomous_worker": "running_24_7",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/webhook")
@app.post("/tradingview-webhook")
async def handle_tradingview_alert(payload: WebhookPayload):
    if payload.secret != config.WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication secret token",
        )

    action = payload.action.lower()
    symbol = payload.symbol.upper().replace(".NS", "").replace(".BO", "")
    qty = int(payload.qty)
    duration = (payload.duration or "MIS").upper()

    logger.info(f"[ALERT] Action: {action.upper()} | Symbol: {symbol} | Qty: {qty} | Duration: {duration}")

    if config.SIMULATION_MODE or megabull_client is None:
        sim_order_id = f"sim-{uuid.uuid4().hex[:8]}"
        return {
            "status": "success",
            "mode": "simulation",
            "order_id": sim_order_id,
            "action": action,
            "symbol": symbol,
            "qty": qty,
        }

    try:
        if action == "close":
            close_resp = megabull_client.close_position(symbol)
            return {"status": "success", "response": close_resp}

        order_side = "BUY" if action == "buy" else "SELL"
        order_resp = megabull_client.place_order(
            symbol=symbol,
            action=order_side,
            qty=qty,
            duration=duration,
            order_type="MKT",
        )

        return {
            "status": "success",
            "order_id": order_resp.get("id"),
            "symbol": symbol,
            "action": order_side,
            "qty": qty,
            "response": order_resp,
        }

    except Exception as exc:
        logger.error(f"Error executing order on MegaBull: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MegaBull execution error: {str(exc)}")


if __name__ == "__main__":
    uvicorn.run("webhook_bridge:app", host=config.HOST, port=config.PORT, reload=False)
