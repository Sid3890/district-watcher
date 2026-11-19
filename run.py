import sys
from pathlib import Path

# Redirect to district-watcher/run.py
watcher_dir = Path(__file__).resolve().parent / "district-watcher"
if str(watcher_dir) not in sys.path:
    sys.path.insert(0, str(watcher_dir))

from run import main

if __name__ == "__main__":
    main()
