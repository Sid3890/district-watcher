import asyncio
import random
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from app.config import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    MIN_POLL_INTERVAL_SECONDS,
    POLL_JITTER_SECONDS,
    BACKOFF_DELAY_SECONDS,
)
from app.database import (
    get_settings,
    get_watch_jobs,
    update_watch_check_result,
    update_watch_status,
)
from app.notifications.notifier import trigger_alert
from app.scraper.district_client import district_client
from app.scraper.parsers import matches_theatre, clean_theatre_name

logger = logging.getLogger("district_watcher.worker")

class BackgroundMonitor:
    """
    Continuous background monitor loop.
    Checks all ACTIVE watch jobs (Mode 1 and Mode 2) with randomized 35-55s jitter,
    handles rate-limiting backoffs, and dispatches native OS & browser alerts.
    """
    def __init__(self):
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Background watcher loop started.")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Background watcher loop stopped.")

    async def _run_loop(self) -> None:
        logger.info("Background monitor loop entering active polling cycle.")
        await asyncio.sleep(2)

        while self._running:
            try:
                settings = await get_settings()
                base_interval = settings.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
                jitter = random.uniform(-POLL_JITTER_SECONDS, POLL_JITTER_SECONDS)
                sleep_duration = max(MIN_POLL_INTERVAL_SECONDS, base_interval + jitter)

                active_jobs = await get_watch_jobs(status="ACTIVE")
                if not active_jobs:
                    logger.debug("No active watch jobs currently. Waiting for next interval...")
                    await asyncio.sleep(sleep_duration)
                    continue

                logger.info(f"Checking {len(active_jobs)} active watch job(s)...")

                for job in active_jobs:
                    if not self._running:
                        break
                    try:
                        await self._process_job(job)
                    except Exception as e:
                        err_str = str(e)
                        logger.error(f"Error checking job #{job['id']}: {err_str}")
                        if "429" in err_str or "Rate limited" in err_str or "403" in err_str:
                            logger.warning(
                                f"Rate limit encountered. Backing off for {BACKOFF_DELAY_SECONDS}s..."
                            )
                            await update_watch_check_result(
                                job["id"],
                                summary=f"Rate limited by District at {datetime.now().strftime('%H:%M:%S')}. Pausing temporarily."
                            )
                            await asyncio.sleep(BACKOFF_DELAY_SECONDS)
                        else:
                            await update_watch_check_result(
                                job["id"],
                                summary=f"Check failed at {datetime.now().strftime('%H:%M:%S')}: {err_str[:60]}"
                            )
                    await asyncio.sleep(random.uniform(2.0, 4.0))

                logger.info(f"Poll round complete. Next check in {sleep_duration:.1f}s.")
                await asyncio.sleep(sleep_duration)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in background monitor loop: {e}")
                await asyncio.sleep(30)

    async def _process_job(self, job: Dict[str, Any]) -> None:
        job_id = job["id"]
        mode = job["mode"]
        city = job.get("city", "Chennai")
        movie_title = job["movie_title"]
        movie_url = job["movie_url"]
        target_date = job["target_date"]
        theatre_name = job["theatre_name"]
        now_str = datetime.now().strftime("%H:%M:%S")

        logger.info(f"Processing Job #{job_id} [{mode}]: {movie_title} @ {theatre_name} ({target_date})")

        if mode == "SHOW_OPENING":
            theatres, _ = await district_client.get_theatres_and_shows(
                movie_url=movie_url,
                target_date=target_date,
                city=city,
            )

            matched_theatre = None
            for t in theatres:
                if matches_theatre(t.theatre_name, theatre_name):
                    matched_theatre = t
                    break

            if matched_theatre and matched_theatre.showtimes:
                pref_time = job.get("showtime_str")
                matching_shows = []
                if pref_time and pref_time.strip():
                    matching_shows = [
                        s for s in matched_theatre.showtimes 
                        if pref_time.lower() in s.time_str.lower()
                    ]
                else:
                    matching_shows = matched_theatre.showtimes

                if matching_shows:
                    show_times_list = ", ".join([s.time_str for s in matching_shows])
                    summary = f"OPEN! Shows found: {show_times_list} at {now_str}"
                    details = {
                        "theatre_name": matched_theatre.theatre_name,
                        "showtimes": [s.dict() for s in matching_shows],
                        "triggered_at": datetime.now().isoformat(),
                    }
                    await update_watch_check_result(
                        job_id,
                        summary=summary,
                        triggered=True,
                        triggered_details=details,
                    )
                    await trigger_alert(
                        watch_job_id=job_id,
                        event_type="SHOW_OPENED",
                        title=f"🎉 SHOW OPENED: {movie_title}!",
                        message=f"Bookings are now OPEN at {matched_theatre.theatre_name} for {target_date} ({show_times_list})!"
                    )
                    return
                else:
                    summary = f"Theatre listed at {now_str}, but specific time '{pref_time}' not open yet."
                    await update_watch_check_result(job_id, summary=summary)
            else:
                summary = f"Checked at {now_str} — Bookings not opened yet for {theatre_name}."
                await update_watch_check_result(job_id, summary=summary)

        elif mode == "SEAT_AVAILABILITY":
            showtime_str = job.get("showtime_str") or ""
            watched_seats = job.get("watched_seats") or []
            match_rule = job.get("match_rule") or "ANY"

            if not watched_seats:
                summary = f"No seats selected to watch. Job paused."
                await update_watch_check_result(job_id, summary=summary)
                await update_watch_status(job_id, "PAUSED")
                return

            seat_map = await district_client.get_seat_map(
                movie_url=movie_url,
                target_date=target_date,
                theatre_name=theatre_name,
                showtime_str=showtime_str,
                city=city,
            )

            seat_lookup = {s.seat_id.upper(): s for s in seat_map.seats}
            available_watched = []
            unavailable_watched = []

            for seat_id in watched_seats:
                s_id = seat_id.upper()
                seat_item = seat_lookup.get(s_id)
                if seat_item and seat_item.status == "available":
                    available_watched.append(s_id)
                else:
                    unavailable_watched.append(s_id)

            is_triggered = False
            if match_rule == "ANY" and len(available_watched) >= 1:
                is_triggered = True
            elif match_rule == "ALL" and len(available_watched) == len(watched_seats):
                is_triggered = True

            if is_triggered:
                open_str = ", ".join(available_watched)
                summary = f"AVAILABLE! Seats {open_str} are open at {now_str}!"
                details = {
                    "available_seats": available_watched,
                    "all_watched_seats": watched_seats,
                    "theatre_name": theatre_name,
                    "showtime_str": showtime_str,
                    "triggered_at": datetime.now().isoformat(),
                }
                await update_watch_check_result(
                    job_id,
                    summary=summary,
                    triggered=True,
                    triggered_details=details,
                )
                await trigger_alert(
                    watch_job_id=job_id,
                    event_type="SEATS_AVAILABLE",
                    title=f"🎟️ SEATS OPEN: {movie_title}!",
                    message=f"Seats {open_str} are now AVAILABLE at {theatre_name} ({showtime_str})! Book now!"
                )
            else:
                summary = f"Checked at {now_str} — {', '.join(watched_seats)} still booked/held."
                await update_watch_check_result(job_id, summary=summary)


# Global monitor instance
background_monitor = BackgroundMonitor()
