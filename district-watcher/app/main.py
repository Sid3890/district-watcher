import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import STATIC_DIR
from app.database import init_db
from app.api.routes import router as api_router
from app.worker.monitor import background_monitor
from app.scraper.browser_manager import browser_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("district_watcher.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing District Ticket & Seat Watcher...")
    await init_db()
    background_monitor.start()
    yield
    # Shutdown
    logger.info("Shutting down District Ticket & Seat Watcher...")
    await background_monitor.stop()
    await browser_manager.close()

app = FastAPI(
    title="District Movie Show & Seat Watcher",
    description="Real-time live scraper & watcher for District (district.in) movie showtimes and seat maps",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for seamless local browser interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router)

# Mount Static Assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def serve_index():
    """Serves the main single-page cinema dashboard."""
    index_file = STATIC_DIR / "index.html"
    return FileResponse(str(index_file))
