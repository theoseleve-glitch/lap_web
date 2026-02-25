"""Launch the telemetry web dashboard directly from source."""
import sys
import os

# Add telemetry_tool to path so all imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "telemetry_tool"))

from web.app import create_app
from web.config import Config

import webbrowser

cfg = Config()
cfg.PORT = int(os.environ.get("PORT", 5000))
cfg.DEBUG = False

app = create_app(cfg)

print(f"\n  Telemetry Dashboard starting ...")
print(f"  URL:  http://127.0.0.1:{cfg.PORT}/")
print(f"  DB:   {cfg.DB_PATH}")
print(f"  Press Ctrl+C to stop.\n")

try:
    webbrowser.open(f"http://127.0.0.1:{cfg.PORT}/")
except Exception:
    pass

app.run(host=cfg.HOST, port=cfg.PORT, debug=cfg.DEBUG)
