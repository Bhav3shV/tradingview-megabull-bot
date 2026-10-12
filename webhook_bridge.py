import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import uvicorn

import config
from megabull_client import MegaBullClient
from cloud_daemon import start_daemon_background, get_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("AutonomousCloudStation")

app = FastAPI(
    title="Autonomous Institutional Quantitative Trading Engine",
    description="100% Zero-Touch Autonomous Trading System for Indian Markets",
    version="4.0.0",
)

megabull_client = None
if config.TARGET_BROKER == "megabull":
    if not config.SIMULATION_MODE:
        try:
            megabull_client = MegaBullClient(config.MEGABULL_API_KEY)
            logger.info("MegaBull Live Client successfully initialized!")
        except Exception as e:
            logger.error(f"Error initializing MegaBull Client: {e}")
            config.SIMULATION_MODE = True
    else:
        logger.info("MegaBull running in Simulation Mode.")


# Launch the 100% Autonomous Daemon when Render boots
@app.on_event("startup")
def on_startup():
    logger.info("Booting Autonomous Daemon thread on Cloud...")
    start_daemon_background()


@app.get("/health")
def health_check():
    engine = get_engine()
    now_ist = engine.get_ist()
    return {
        "status": "online",
        "broker": config.TARGET_BROKER,
        "mode": "simulation" if config.SIMULATION_MODE else "live_megabull_paper",
        "megabull_connected": megabull_client is not None and not config.SIMULATION_MODE,
        "autonomous_daemon": "active_24_7",
        "market_active_now": engine.is_market_active(),
        "ist_time": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
    }


@app.get("/telemetry")
def get_telemetry():
    """Returns real-time telemetry, active positions, and audit trade history."""
    engine = get_engine()
    
    # Query audit history from SQLite
    history = []
    try:
        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()
        cur.execute("SELECT timestamp, symbol, action, strategy, regime, entry_price, exit_price, exit_reason, pnl_amount FROM audit_trades ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
        for r in rows:
            history.append({
                "time": r[0], "symbol": r[1], "action": r[2], "strategy": r[3],
                "regime": r[4], "entry": r[5], "exit": r[6], "reason": r[7], "pnl": r[8]
            })
        conn.close()
    except Exception as e:
        logger.error(f"Telemetry DB error: {e}")

    return {
        "ist_time": engine.get_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
        "market_active": engine.is_market_active(),
        "active_positions_count": len(engine.positions),
        "active_positions": engine.positions,
        "closed_trades_history": history,
    }


class WebhookPayload(BaseModel):
    secret: str
    action: str
    symbol: str
    qty: float = 1.0
    sl: Optional[float] = None
    tp: Optional[float] = None
    duration: Optional[str] = "MIS"


@app.post("/webhook")
@app.post("/tradingview-webhook")
async def handle_manual_webhook(payload: WebhookPayload):
    if payload.secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    action = payload.action.lower()
    symbol = payload.symbol.upper().replace(".NS", "").replace(".BO", "")
    qty = int(payload.qty)
    duration = (payload.duration or "MIS").upper()

    if config.SIMULATION_MODE or megabull_client is None:
        return {"status": "success", "mode": "simulation", "action": action, "symbol": symbol, "qty": qty}

    try:
        if action == "close":
            return {"status": "success", "response": megabull_client.close_position(symbol)}
        resp = megabull_client.place_order(symbol=symbol, action=action.upper(), qty=qty, duration=duration, order_type="MKT")
        return {"status": "success", "order_id": resp.get("id"), "response": resp}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("webhook_bridge:app", host=config.HOST, port=config.PORT, reload=False)
