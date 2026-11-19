import re
import logging
from typing import List, Dict, Any, Optional
from app.models import (
    MovieItem,
    TheatreItem,
    ShowtimeItem,
    SeatItem,
    SeatCategory,
    SeatMapResponse,
)

logger = logging.getLogger("district_watcher.parsers")

def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

def clean_theatre_name(name: str) -> str:
    return normalize_text(name).lower()

def matches_theatre(theatre_candidate: str, target_theatre: str) -> bool:
    """Fuzzy/substring check for matching theatre names."""
    cand = clean_theatre_name(theatre_candidate)
    target = clean_theatre_name(target_theatre)
    if not target or not cand:
        return False
    if target in cand or cand in target:
        return True
    
    # Token-level intersection check
    target_words = [w for w in re.split(r"[^\w]+", target) if len(w) > 2]
    cand_words = set(re.split(r"[^\w]+", cand))
    if target_words:
        matched = sum(1 for w in target_words if w in cand_words)
        return (matched / len(target_words)) >= 0.6
    return False

def parse_movie_cards(raw_movies: List[Dict[str, Any]]) -> List[MovieItem]:
    movies: List[MovieItem] = []
    seen_urls = set()
    for item in raw_movies:
        title = normalize_text(item.get("title", ""))
        url = item.get("movie_url", "")
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        
        movies.append(MovieItem(
            title=title,
            movie_url=url,
            movie_id=item.get("movie_id"),
            poster_url=item.get("poster_url"),
            languages=item.get("languages", []),
            formats=item.get("formats", []),
            genre=item.get("genre"),
            is_upcoming=item.get("is_upcoming", False),
        ))
    return movies

def parse_theatres_and_shows(theatre_data: List[Dict[str, Any]]) -> List[TheatreItem]:
    theatres: List[TheatreItem] = []
    seen_theatre_ids = set()

    for item in theatre_data:
        theatre_name = normalize_text(item.get("theatre_name", ""))
        theatre_id = item.get("theatre_id") or re.sub(r"[^\w]+", "-", theatre_name.lower())
        
        if not theatre_name or theatre_id in seen_theatre_ids:
            continue
        seen_theatre_ids.add(theatre_id)

        raw_shows = item.get("showtimes", [])
        showtimes: List[ShowtimeItem] = []
        for s in raw_shows:
            time_str = normalize_text(s.get("time_str", ""))
            show_id = s.get("showtime_id") or f"{theatre_id}-{time_str}"
            if time_str:
                showtimes.append(ShowtimeItem(
                    showtime_id=show_id,
                    time_str=time_str,
                    format_tag=s.get("format_tag"),
                    booking_url_or_selector=s.get("booking_url_or_selector"),
                    session_id=s.get("session_id"),
                ))

        theatres.append(TheatreItem(
            theatre_id=theatre_id,
            theatre_name=theatre_name,
            address=item.get("address"),
            showtimes=showtimes,
        ))
    return theatres

def parse_intercepted_seat_json(
    payload: Dict[str, Any],
    movie_title: Optional[str],
    theatre_name: str,
    showtime_str: str,
    date: str,
    price_map: Optional[Dict[str, float]] = None,
) -> Optional[SeatMapResponse]:
    """
    Parses intercepted seat layout JSON from District / ticketing API.
    Handles District Next.js / select-seat layout format as well as generic ticketing JSON.
    """
    try:
        data = payload.get("data") or payload.get("response") or payload
        categories_dict: Dict[str, Dict[str, Any]] = {}
        seats: List[SeatItem] = []
        screen_name = data.get("screen_name") or data.get("audi") or "Screen 1"

        # 1. District / Zomato select-seat format: seatLayout.colAreas.objArea
        col_areas = (
            data.get("seatLayout", {}).get("colAreas", {}).get("objArea")
            or payload.get("seatLayout", {}).get("colAreas", {}).get("objArea")
            or []
        )

        if col_areas:
            p_map = price_map or {}
            for area in col_areas:
                cat_name = (area.get("AreaDesc") or area.get("name") or "STANDARD").strip().upper()
                price = p_map.get(cat_name) or p_map.get(cat_name.replace(" ", "")) or float(area.get("Price") or area.get("price") or 0.0)
                if cat_name not in categories_dict:
                    categories_dict[cat_name] = {"name": cat_name, "price": price, "rows": set()}

                rows = area.get("objRow") or []
                for row in rows:
                    raw_phy_row = str(row.get("PhyRowId") or "").strip().upper()
                    phy_row = re.sub(r"[^A-Z0-9\-]", "", raw_phy_row)

                    raw_seats = row.get("objSeat") or []
                    for s in raw_seats:
                        disp_num = str(s.get("displaySeatNumber") or s.get("seatNumber") or "").strip()
                        if not disp_num:
                            continue

                        # Extract row label & seat number
                        if re.match(r"^[A-Z]+\d+$", disp_num):
                            m = re.match(r"^([A-Z]+)(\d+)$", disp_num)
                            row_label = m.group(1)
                            seat_num = m.group(2)
                            seat_id = disp_num
                        elif phy_row:
                            row_label = phy_row
                            seat_num = disp_num
                            seat_id = f"{row_label}{seat_num}"
                        else:
                            row_label = ""
                            seat_num = disp_num
                            seat_id = disp_num

                        if row_label:
                            categories_dict[cat_name]["rows"].add(row_label)

                        # District SeatStatus: "0" = Available, "1" = Sold/Booked, "1000"/"1001" = Wheelchair Available, "1002" = Blocked
                        seat_status_code = str(s.get("SeatStatus", "1")).strip().lower()
                        if seat_status_code in ("0", "1000", "1001", "available", "open", "free", "vacant"):
                            status = "available"
                        elif seat_status_code in ("1", "sold", "booked", "occupied", "2"):
                            status = "sold"
                        else:
                            status = "blocked"

                        seats.append(SeatItem(
                            seat_id=seat_id,
                            row_label=row_label,
                            seat_num=seat_num,
                            col_idx=s.get("GridSeatNum") or s.get("col_index"),
                            status=status,
                            category=cat_name,
                            price=price or float(s.get("price") or 0.0),
                        ))

            if seats:
                cat_list = [
                    SeatCategory(
                        name=v["name"],
                        price=v["price"],
                        rows=sorted(list(v["rows"]))
                    )
                    for v in categories_dict.values()
                ]
                return SeatMapResponse(
                    movie_title=movie_title,
                    theatre_name=theatre_name,
                    showtime_str=showtime_str,
                    date=date,
                    screen_name=screen_name,
                    categories=cat_list,
                    seats=seats,
                    total_available=sum(1 for s in seats if s.status == "available"),
                    total_sold=sum(1 for s in seats if s.status == "sold"),
                    total_blocked=sum(1 for s in seats if s.status == "blocked"),
                )

        # 2. Generic ticketing areas format fallback
        areas = (
            data.get("areas")
            or data.get("sections")
            or data.get("categories")
            or data.get("seat_layout", {}).get("areas")
            or []
        )

        for area in areas:
            cat_name = area.get("area_name") or area.get("name") or area.get("category") or "STANDARD"
            price = float(area.get("price") or area.get("rate") or 0.0)
            if cat_name not in categories_dict:
                categories_dict[cat_name] = {"name": cat_name, "price": price, "rows": set()}

            rows = area.get("rows") or area.get("row_list") or []
            for row in rows:
                row_label = str(row.get("row_name") or row.get("label") or "").strip()
                if row_label:
                    categories_dict[cat_name]["rows"].add(row_label)

                raw_seats = row.get("seats") or row.get("seat_list") or []
                for s in raw_seats:
                    seat_num = str(s.get("seat_number") or s.get("label") or s.get("num") or "").strip()
                    if not seat_num:
                        continue
                    seat_id = f"{row_label}{seat_num}" if row_label else seat_num
                    raw_status = str(s.get("status") or s.get("state") or s.get("SeatStatus") or "").lower()
                    
                    # Note: On District/ticketing APIs: 0 is available, 1 is sold
                    if raw_status in ("available", "open", "free", "vacant", "0", "1000", "1001"):
                        status = "available"
                    elif raw_status in ("sold", "booked", "occupied", "1", "2"):
                        status = "sold"
                    else:
                        status = "blocked"

                    seats.append(SeatItem(
                        seat_id=seat_id,
                        row_label=row_label,
                        seat_num=seat_num,
                        col_idx=s.get("col_index") or s.get("x") or s.get("GridSeatNum"),
                        status=status,
                        category=cat_name,
                        price=price or float(s.get("price") or 0.0),
                    ))

        if seats:
            cat_list = [
                SeatCategory(
                    name=v["name"],
                    price=v["price"],
                    rows=sorted(list(v["rows"]))
                )
                for v in categories_dict.values()
            ]
            total_avail = sum(1 for s in seats if s.status == "available")
            total_sold = sum(1 for s in seats if s.status == "sold")
            total_blocked = sum(1 for s in seats if s.status == "blocked")

            return SeatMapResponse(
                movie_title=movie_title,
                theatre_name=theatre_name,
                showtime_str=showtime_str,
                date=date,
                screen_name=screen_name,
                categories=cat_list,
                seats=seats,
                total_available=total_avail,
                total_sold=total_sold,
                total_blocked=total_blocked,
            )
    except Exception as e:
        logger.warning(f"Error parsing seat json: {e}")
    return None

def normalize_seat_map_dom(
    dom_result: Dict[str, Any],
    movie_title: Optional[str],
    theatre_name: str,
    showtime_str: str,
    date: str
) -> SeatMapResponse:
    """Normalizes DOM / SVG parsed seat chart into SeatMapResponse."""
    raw_seats = dom_result.get("seats", [])
    screen_name = dom_result.get("screen_name") or "Main Screen"
    categories_dict: Dict[str, Dict[str, Any]] = {}
    seats: List[SeatItem] = []

    for s in raw_seats:
        seat_id = str(s.get("seat_id", "")).strip().upper()
        if not seat_id:
            continue
        row_label = str(s.get("row_label", "")).strip().upper()
        seat_num = str(s.get("seat_num", "")).strip()
        if not row_label and re.match(r"^([A-Z]+)(\d+)$", seat_id):
            m = re.match(r"^([A-Z]+)(\d+)$", seat_id)
            row_label = m.group(1)
            seat_num = m.group(2)
        elif not seat_num and row_label:
            seat_num = seat_id.replace(row_label, "")

        cat_name = str(s.get("category", "STANDARD")).strip().upper()
        price = float(s.get("price") or 0.0)

        if cat_name not in categories_dict:
            categories_dict[cat_name] = {"name": cat_name, "price": price, "rows": set()}
        if row_label:
            categories_dict[cat_name]["rows"].add(row_label)

        status = s.get("status", "available").lower()
        if status not in ("available", "sold", "blocked"):
            status = "available"

        seats.append(SeatItem(
            seat_id=seat_id,
            row_label=row_label,
            seat_num=seat_num,
            col_idx=s.get("col_idx"),
            status=status,
            category=cat_name,
            price=price,
        ))

    cat_list = [
        SeatCategory(
            name=v["name"],
            price=v["price"],
            rows=sorted(list(v["rows"]))
        )
        for v in categories_dict.values()
    ]
    total_avail = sum(1 for s in seats if s.status == "available")
    total_sold = sum(1 for s in seats if s.status == "sold")
    total_blocked = sum(1 for s in seats if s.status == "blocked")

    return SeatMapResponse(
        movie_title=movie_title,
        theatre_name=theatre_name,
        showtime_str=showtime_str,
        date=date,
        screen_name=screen_name,
        categories=cat_list,
        seats=seats,
        total_available=total_avail,
        total_sold=total_sold,
        total_blocked=total_blocked,
    )
