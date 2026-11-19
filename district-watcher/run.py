import sys
import os
from pathlib import Path

# Add project directory to sys.path
PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import uvicorn
from app.config import HOST, PORT

def main():
    print("=" * 65)
    print(" 🎬 DISTRICT TICKET & SEAT WATCHER (district.in)")
    print(f" 🌐 Dashboard URL: http://{HOST}:{PORT}")
    print(f" 🔔 OS Notifications: Enabled (Desktop Banners & Audio Chimes)")
    print("=" * 65)

    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )

if __name__ == "__main__":
    main()
