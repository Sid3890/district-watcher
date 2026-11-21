import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Path
from fastapi.responses import JSONResponse

from app.models import (
    AppSettings,
    SettingsUpdateRequest,
    MovieItem,
    TheatreItem,
    ShowsResponse,
    SeatMapRequest,
    SeatMapResponse,
    WatchJobCreate,
    WatchJobResponse,
    WatchStatusUpdate,
    AlertLogResponse,
    TestAlertRequest,
)
from app.database import (
    get_settings,
    update_settings,
    create_watch_job,
    get_watch_jobs,
    get_watch_job,
    update_watch_status,
    delete_watch_job,
    get_unacknowledged_alerts,
    acknowledge_alert,
    get_recent_alerts,
)
from app.notifications.notifier import trigger_alert, send_os_desktop_notification
from app.notifications.sound_alarm import local_alarm
from app.scraper.browser_manager import browser_manager
from app.scraper.district_client import district_client

logger = logging.getLogger("district_watcher.api")
router = APIRouter(prefix="/api")

# In-memory cache for movies
_movie_cache: Dict[str, Dict[str, Any]] = {}

@router.get("/health")
async def get_health():
    """Returns backend status, Playwright readiness, and active watch count."""
    active_jobs = await get_watch_jobs(status="ACTIVE")
    return {
        "status": "ok",
        "playwright_ready": browser_manager.is_ready,
        "active_watch_count": len(active_jobs),
    }

@router.get("/settings", response_model=AppSettings)
async def fetch_settings():
    """Fetches global app settings."""
    return await get_settings()

@router.put("/settings", response_model=AppSettings)
async def modify_settings(req: SettingsUpdateRequest):
    """Updates global app settings (sound, tone, volume, poll interval, last city)."""
    updates = req.dict(exclude_unset=True)
    if updates.get("sound_enabled") is False:
        local_alarm.stop_alarm()
    return await update_settings(updates)

@router.get("/movies", response_model=List[MovieItem])
async def list_movies(city: str = Query("Chennai", description="City name on District")):
    """Scrapes & caches current movies on District for the specified city."""
    city_key = city.lower().strip()
    try:
        movies = await district_client.get_movies(city=city)
        if movies:
            _movie_cache[city_key] = {
                "city": city,
                "movies": movies,
            }
        return movies
    except Exception as e:
        logger.error(f"Failed to fetch movies for {city}: {e}")
        if city_key in _movie_cache:
            return _movie_cache[city_key]["movies"]
        raise HTTPException(status_code=502, detail=f"Failed to fetch movies from district.in: {str(e)}")

@router.get("/shows", response_model=ShowsResponse)
async def list_shows(
    movie_url: str = Query(..., description="District movie ticket URL"),
    date: str = Query(..., description="Target date in YYYY-MM-DD format"),
    city: str = Query("Chennai", description="City name on District"),
):
    """Fetches theatres and open showtimes for a movie on a given date."""
    try:
        theatres, available_dates = await district_client.get_theatres_and_shows(
            movie_url=movie_url,
            target_date=date,
            city=city,
        )
        return ShowsResponse(
            movie_url=movie_url,
            date=date,
            theatres=theatres,
            available_dates=available_dates,
        )
    except Exception as e:
        logger.error(f"Failed to fetch shows for {movie_url} on {date}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch showtimes: {str(e)}")

@router.post("/seat-map", response_model=SeatMapResponse)
async def fetch_seat_map(req: SeatMapRequest):
    """Fetches the interactive seating chart for an open movie showtime."""
    try:
        seat_map = await district_client.get_seat_map(
            movie_url=req.movie_url,
            target_date=req.date,
            theatre_name=req.theatre_name,
            showtime_str=req.showtime_str,
            city=req.city or "Chennai",
        )
        return seat_map
    except Exception as e:
        logger.error(f"Failed to fetch seat map: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to extract seat map: {str(e)}")

@router.get("/watches", response_model=List[WatchJobResponse])
async def list_watches(status: Optional[str] = Query(None, description="Optional filter: ACTIVE, PAUSED, TRIGGERED")):
    """Lists all active, paused, or triggered watch jobs."""
    jobs = await get_watch_jobs(status=status)
    return jobs

@router.post("/watches", response_model=WatchJobResponse)
async def add_watch(req: WatchJobCreate):
    """Creates a new Mode 1 (SHOW_OPENING) or Mode 2 (SEAT_AVAILABILITY) watch job."""
    job_id = await create_watch_job(
        mode=req.mode,
        city=req.city,
        movie_title=req.movie_title,
        movie_url=req.movie_url,
        target_date=req.target_date,
        theatre_name=req.theatre_name,
        showtime_str=req.showtime_str,
        watched_seats=req.watched_seats,
        match_rule=req.match_rule or "ANY",
    )
    job = await get_watch_job(job_id)
    if not job:
        raise HTTPException(status_code=500, detail="Failed to create watch job")
    return job

@router.patch("/watches/{id}/status", response_model=WatchJobResponse)
async def update_status(
    id: int = Path(..., description="Watch Job ID"),
    req: WatchStatusUpdate = ...,
):
    """Toggles job status (ACTIVE <-> PAUSED) or resets TRIGGERED job back to ACTIVE."""
    job = await get_watch_job(id)
    if not job:
        raise HTTPException(status_code=404, detail="Watch job not found")
    
    await update_watch_status(id, req.status)
    return await get_watch_job(id)

@router.delete("/watches/{id}")
async def remove_watch(id: int = Path(..., description="Watch Job ID")):
    """Deletes a watch job."""
    success = await delete_watch_job(id)
    if not success:
        raise HTTPException(status_code=404, detail="Watch job not found")
    return {"deleted": True, "id": id}

@router.get("/alerts/unacknowledged", response_model=List[AlertLogResponse])
async def list_unacknowledged_alerts():
    """
    Polled every 3s by the frontend to trigger browser sound cues and
    banner modals when a background worker fires an alert.
    """
    return await get_unacknowledged_alerts()

@router.post("/alerts/{id}/ack")
async def acknowledge_alert_route(id: int = Path(..., description="Alert ID")):
    """Marks an alert as acknowledged and silences local alarm audio."""
    local_alarm.stop_alarm()
    success = await acknowledge_alert(id)
    return {"acknowledged": success, "id": id}

@router.post("/alerts/silence-sound")
async def silence_sound():
    """Immediately silences any active local OS sound cue."""
    local_alarm.stop_alarm()
    return {"status": "silenced", "ringing": False}

@router.get("/alerts/sound-status")
async def sound_status():
    """Returns whether local alarm sound is currently ringing."""
    return {"ringing": local_alarm.is_ringing}

@router.get("/alerts/recent", response_model=List[AlertLogResponse])
async def list_recent_alerts():
    """Returns recent alert logs."""
    return await get_recent_alerts(limit=30)

@router.post("/test-alert")
async def test_alert(req: TestAlertRequest):
    """
    Fires a test OS desktop notification and creates an alert record in SQLite
    to verify both native banner and browser Web Audio chime.
    """
    jobs = await get_watch_jobs()
    sample_job_id = jobs[0]["id"] if jobs else None
    if sample_job_id is None:
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        sample_job_id = await create_watch_job(
            mode="SHOW_OPENING",
            city="Chennai",
            movie_title="District Cinema Watch",
            movie_url="https://www.district.in/movies/",
            target_date=today_str,
            theatre_name="Cinema",
        )

    title = req.title or "District Watcher Test"
    message = req.message or "Testing desktop notification and Web Audio chime!"

    alert_id = await trigger_alert(
        watch_job_id=sample_job_id,
        event_type="TEST",
        title=title,
        message=message,
        click_url="https://www.district.in",
    )

    return {
        "status": "alert_dispatched",
        "alert_id": alert_id,
        "title": title,
        "message": message,
    }
