import os
from dotenv import load_dotenv

# Load from .env file
load_dotenv()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "my_secure_trading_secret_12345")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Broker selection: 'megabull' or 'alpaca'
TARGET_BROKER = os.getenv("TARGET_BROKER", "megabull").lower()

# MegaBull Configuration
MEGABULL_API_KEY = os.getenv("MEGABULL_API_KEY", "")

# Alpaca Configuration (Fallback)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")

# Determine if running in local simulation or live broker paper mode
_sim_env = os.getenv("SIMULATION_MODE", "false").lower() in ("true", "1", "yes")

if TARGET_BROKER == "megabull":
    has_valid_keys = bool(MEGABULL_API_KEY) and MEGABULL_API_KEY != "YOUR_MEGABULL_API_KEY"
else:
    has_valid_keys = (
        bool(ALPACA_API_KEY)
        and bool(ALPACA_SECRET_KEY)
        and ALPACA_API_KEY != "YOUR_ALPACA_PAPER_KEY"
    )

SIMULATION_MODE = _sim_env or not has_valid_keys
