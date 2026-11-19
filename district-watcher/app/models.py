from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

# App Settings Models
class AppSettings(BaseModel):
    id: int = 1
    sound_enabled: bool = True
    sound_tone: str = "chime"  # 'chime', 'bell', 'pulse'
    sound_volume: float = 0.8
    desktop_notifications_enabled: bool = True
    poll_interval_seconds: int = 45
    last_selected_city: str = "Chennai"

class SettingsUpdateRequest(BaseModel):
    sound_enabled: Optional[bool] = None
    sound_tone: Optional[str] = None
    sound_volume: Optional[float] = None
    desktop_notifications_enabled: Optional[bool] = None
    poll_interval_seconds: Optional[int] = Field(None, ge=25)
    last_selected_city: Optional[str] = None

# District Scraped Models
class MovieItem(BaseModel):
    title: str
    movie_url: str
    movie_id: Optional[str] = None
    poster_url: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    formats: List[str] = Field(default_factory=list)
    genre: Optional[str] = None
    is_upcoming: bool = False

class ShowtimeItem(BaseModel):
    showtime_id: str
    time_str: str
    format_tag: Optional[str] = None
    booking_url_or_selector: Optional[str] = None
    session_id: Optional[str] = None

class TheatreItem(BaseModel):
    theatre_id: str
    theatre_name: str
    address: Optional[str] = None
    showtimes: List[ShowtimeItem] = Field(default_factory=list)

class ShowsResponse(BaseModel):
    movie_url: str
    date: str
    theatres: List[TheatreItem] = Field(default_factory=list)
    available_dates: List[str] = Field(default_factory=list)

# Seat Map Models
class SeatItem(BaseModel):
    seat_id: str  # e.g., 'G12'
    row_label: str  # e.g., 'G'
    seat_num: str  # e.g., '12'
    col_idx: Optional[int] = None
    status: str = "available"  # 'available', 'sold', 'blocked'
    category: str = "STANDARD"  # 'RECLINER', 'PRIME', 'CLASSIC', etc.
    price: Optional[float] = None

class SeatCategory(BaseModel):
    name: str
    price: Optional[float] = None
    rows: List[str] = Field(default_factory=list)

class SeatMapRequest(BaseModel):
    movie_url: str
    date: str
    theatre_name: str
    showtime_str: str

class SeatMapResponse(BaseModel):
    movie_title: Optional[str] = None
    theatre_name: str
    showtime_str: str
    date: str
    screen_name: Optional[str] = None
    categories: List[SeatCategory] = Field(default_factory=list)
    seats: List[SeatItem] = Field(default_factory=list)
    total_available: int = 0
    total_sold: int = 0
    total_blocked: int = 0

# Watch Jobs Models
class WatchJobCreate(BaseModel):
    mode: str = Field(..., pattern="^(SHOW_OPENING|SEAT_AVAILABILITY)$")
    city: str
    movie_title: str
    movie_url: str
    target_date: str  # YYYY-MM-DD
    theatre_name: str
    showtime_str: Optional[str] = None
    watched_seats: Optional[List[str]] = None
    match_rule: Optional[str] = Field("ANY", pattern="^(ANY|ALL)$")

class WatchJobResponse(BaseModel):
    id: int
    mode: str
    status: str
    city: str
    movie_title: str
    movie_url: str
    target_date: str
    theatre_name: str
    showtime_str: Optional[str] = None
    watched_seats: Optional[List[str]] = None
    match_rule: str
    last_checked_at: Optional[str] = None
    last_check_summary: Optional[str] = None
    triggered_details: Optional[Dict[str, Any]] = None
    created_at: str

class WatchStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(ACTIVE|PAUSED|TRIGGERED)$")

# Alert Log Models
class AlertLogResponse(BaseModel):
    id: int
    watch_job_id: int
    event_type: str
    title: str
    message: str
    acknowledged: bool
    created_at: str

class TestAlertRequest(BaseModel):
    title: Optional[str] = "District Watcher Test"
    message: Optional[str] = "Testing desktop alert and audio chime!"
