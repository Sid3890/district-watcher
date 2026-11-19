import os
import re
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from playwright.async_api import Page, Response, Error as PlaywrightError
from app.config import (
    DISTRICT_BASE_URL,
    DISTRICT_MOVIES_URL,
    DEBUG_SCREENSHOT_PATH,
)
from app.models import (
    MovieItem,
    TheatreItem,
    ShowtimeItem,
    SeatMapResponse,
)
from app.scraper.browser_manager import browser_manager
from app.scraper.parsers import (
    parse_movie_cards,
    parse_theatres_and_shows,
    parse_intercepted_seat_json,
    normalize_seat_map_dom,
    normalize_text,
    matches_theatre,
)

logger = logging.getLogger("district_watcher.client")

def normalize_movie_showtime_url(movie_url: str, city: str = "chennai", target_date: Optional[str] = None) -> str:
    """
    Ensures the movie URL points to the city-specific booking/showtimes route
    (e.g., https://www.district.in/movies/<slug>-movie-tickets-in-<city>-<id>?fromdate=YYYY-MM-DD)
    instead of the overview synopsis page.
    """
    clean_city = city.lower().strip().replace(" ", "-")
    url = movie_url.strip()
    if not url.startswith("http"):
        url = urljoin(DISTRICT_BASE_URL, url)

    # Parse components
    parsed = urlparse(url)
    path = parsed.path
    query_params = parse_qs(parsed.query)

    # Check if path is synopsis format e.g. /movies/slug-movie-tickets-MV12345
    # and transform to /movies/slug-movie-tickets-in-<city>-MV12345
    if "-movie-tickets-" in path:
        if not re.search(r"-movie-tickets-in-[a-z0-9\-]+-", path):
            path = re.sub(
                r"-movie-tickets-([A-Za-z0-9]+)$",
                rf"-movie-tickets-in-{clean_city}-\1",
                path
            )

    # Append target_date if provided
    if target_date:
        query_params["fromdate"] = [target_date]

    # Reconstruct query
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, new_query, parsed.fragment))


class DistrictClient:
    """
    Playwright-powered client for district.in.
    Handles city context, movie extraction, theatre/showtime discovery,
    and seat chart extraction via JSON-LD, Next.js state, and DOM.
    """

    async def _capture_debug_screenshot(self, page: Page, name: str = "debug") -> None:
        try:
            path = DEBUG_SCREENSHOT_PATH.parent / f"{name}_error.png"
            await page.screenshot(path=str(path), full_page=True)
            logger.info(f"Saved debug screenshot to {path}")
        except Exception as e:
            logger.debug(f"Failed to capture debug screenshot: {e}")

    async def set_city(self, page: Page, city: str) -> bool:
        """Sets the selected city context in District."""
        try:
            logger.info(f"Setting city context to '{city}' on District...")
            city_btn = page.locator("button:has-text('Select City'), [data-testid='city-selector'], [aria-label*='location' i], header div:has-text('Select Location')").first
            if await city_btn.is_visible(timeout=2000):
                await city_btn.click()
                await page.wait_for_timeout(500)

            city_input = page.locator("input[placeholder*='search city' i], input[placeholder*='city' i], input[placeholder*='search location' i]").first
            if await city_input.is_visible(timeout=2000):
                await city_input.fill(city)
                await page.wait_for_timeout(600)
                suggestion = page.locator(f"div:text-matches('^{city}', 'i'), li:text-matches('^{city}', 'i'), span:text-matches('^{city}', 'i')").first
                if await suggestion.is_visible(timeout=2000):
                    await suggestion.click()
                    await page.wait_for_timeout(1000)
                    logger.info(f"City '{city}' selected via search suggestion.")
                    await browser_manager.save_storage_state()
                    return True

            city_pill = page.locator(f"button:has-text('{city}'), div[role='button']:has-text('{city}'), span:has-text('{city}')").first
            if await city_pill.is_visible(timeout=1500):
                await city_pill.click()
                await page.wait_for_timeout(1000)
                logger.info(f"City '{city}' selected via direct button.")
                await browser_manager.save_storage_state()
                return True

        except Exception as e:
            logger.warning(f"Could not interact with city selector modal ({e}); proceeding with current page context.")
        return False

    async def get_movies(self, city: str = "Chennai") -> List[MovieItem]:
        """
        Navigates to district.in/movies and extracts Now Showing and Upcoming movies.
        """
        async with browser_manager.get_page() as page:
            url = f"{DISTRICT_MOVIES_URL}?city={city.lower()}"
            logger.info(f"Fetching movies from {url} (city: {city})...")
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if response and response.status in (403, 429):
                    raise RuntimeError(f"Rate limited (HTTP {response.status})")

                await self.set_city(page, city)

                try:
                    await page.wait_for_selector("a[href*='/movies/'], [data-testid*='movie']", timeout=7000)
                except Exception:
                    pass

                # Extract movies via Next.js hydration props or DOM
                extracted = await page.evaluate(r"""
                    () => {
                        const results = [];
                        const seenUrls = new Set();

                        // 1. Try __NEXT_DATA__
                        try {
                            if (window.__NEXT_DATA__ && window.__NEXT_DATA__.props) {
                                const pageProps = window.__NEXT_DATA__.props.pageProps || {};
                                const rawList = pageProps.movies || pageProps.movieList || pageProps.initialData?.movies || [];
                                if (Array.isArray(rawList) && rawList.length > 0) {
                                    for (const m of rawList) {
                                        const title = m.title || m.name || m.movie_name;
                                        const slug = m.slug || m.movie_slug || m.id;
                                        const url = m.url || (slug ? `/movies/${slug}` : '');
                                        if (title && url) {
                                            results.push({
                                                title: title,
                                                movie_url: url.startsWith('http') ? url : 'https://www.district.in' + url,
                                                movie_id: String(m.id || slug),
                                                poster_url: m.poster || m.poster_url || m.image,
                                                languages: Array.isArray(m.languages) ? m.languages : [m.language].filter(Boolean),
                                                formats: Array.isArray(m.formats) ? m.formats : [m.format].filter(Boolean),
                                                genre: m.genre || (Array.isArray(m.genres) ? m.genres.join(', ') : ''),
                                                is_upcoming: Boolean(m.is_upcoming || m.upcoming)
                                            });
                                            seenUrls.add(url);
                                        }
                                    }
                                }
                            }
                        } catch (e) {}

                        // 2. DOM inspection for movie cards
                        const links = document.querySelectorAll("a[href*='/movies/']");
                        for (const a of links) {
                            const href = a.getAttribute('href');
                            if (!href || href === '/movies' || href === '/movies/' || href.includes('city=') || seenUrls.has(href)) {
                                continue;
                            }
                            
                            const img = a.querySelector('img');
                            const posterUrl = img ? (img.getAttribute('src') || img.getAttribute('data-src')) : null;
                            
                            let title = '';
                            const heading = a.querySelector('h1, h2, h3, h4, [class*="title" i], [class*="name" i]');
                            if (heading) {
                                title = heading.innerText.trim();
                            } else if (img && img.getAttribute('alt')) {
                                title = img.getAttribute('alt').replace(/poster|movie/gi, '').trim();
                            } else {
                                title = a.innerText.split('\n')[0].trim();
                            }

                            if (title && title.length > 1 && !title.toLowerCase().includes('view all')) {
                                seenUrls.add(href);
                                const fullUrl = href.startsWith('http') ? href : 'https://www.district.in' + href;
                                const textContent = a.innerText;
                                const formats = [];
                                if (/2D/i.test(textContent)) formats.push('2D');
                                if (/3D/i.test(textContent)) formats.push('3D');
                                if (/IMAX/i.test(textContent)) formats.push('IMAX');
                                if (/4DX/i.test(textContent)) formats.push('4DX');

                                results.push({
                                    title: title,
                                    movie_url: fullUrl,
                                    movie_id: href.split('-').pop() || '',
                                    poster_url: posterUrl,
                                    languages: [],
                                    formats: formats,
                                    genre: '',
                                    is_upcoming: /upcoming|releases on/i.test(textContent)
                                });
                            }
                        }

                        return results;
                    }
                """)

                movies = parse_movie_cards(extracted)
                logger.info(f"Extracted {len(movies)} movies from district.in for {city}")
                return movies

            except Exception as e:
                logger.error(f"Error fetching movies for {city}: {e}")
                await self._capture_debug_screenshot(page, "movies")
                raise

    async def get_theatres_and_shows(
        self,
        movie_url: str,
        target_date: str,  # YYYY-MM-DD
        city: str = "Chennai"
    ) -> Tuple[List[TheatreItem], List[str]]:
        """
        Loads the movie's city ticket page with target date, extracts all listing
        theatres, open showtimes, and returns available dates for the movie.
        """
        async with browser_manager.get_page() as page:
            show_url = normalize_movie_showtime_url(movie_url, city=city, target_date=target_date)
            logger.info(f"Loading showtimes from {show_url} (target date: {target_date})...")

            try:
                response = await page.goto(show_url, wait_until="domcontentloaded", timeout=35000)
                if response and response.status in (403, 429):
                    raise RuntimeError(f"Rate limited by District (HTTP {response.status})")

                # If on synopsis overview page, check for 'Book Tickets' button and click it
                try:
                    book_btn = page.locator("button:has-text('Book Tickets'), a:has-text('Book Tickets')").first
                    if await book_btn.is_visible(timeout=1500):
                        logger.info("Found 'Book Tickets' button, clicking to enter showtimes view...")
                        await book_btn.click()
                        await page.wait_for_timeout(1500)
                except Exception:
                    pass

                await page.wait_for_timeout(1500)

                # Multi-layer extraction prioritizing District Next.js state
                payload = await page.evaluate(r"""
                    () => {
                        // 1. Extract Next.js initialState (Primary source of truth on District)
                        let nextStateSessions = null;
                        let nextShowDates = [];
                        let contentId = '';
                        try {
                            const pp = window.__NEXT_DATA__?.props?.pageProps?.initialState?.movies || {};
                            if (pp.movieSessions) {
                                const firstSess = Object.values(pp.movieSessions)[0] || {};
                                nextStateSessions = firstSess.arrangedSessions || null;
                                nextShowDates = firstSess.meta?.showDates || [];
                                contentId = firstSess.meta?.movie?.content_id || '';
                            }
                        } catch(e) {}

                        // 2. Extract JSON-LD ScreeningEvent items (Fallback)
                        const jsonLdEvents = [];
                        const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
                        for (const s of scripts) {
                            try {
                                const parsed = JSON.parse(s.innerText);
                                if (Array.isArray(parsed)) {
                                    for (const item of parsed) {
                                        if (item['@type'] === 'ScreeningEvent') jsonLdEvents.push(item);
                                    }
                                } else if (parsed['@type'] === 'ScreeningEvent') {
                                    jsonLdEvents.push(parsed);
                                } else if (parsed['@graph'] && Array.isArray(parsed['@graph'])) {
                                    for (const item of parsed['@graph']) {
                                        if (item['@type'] === 'ScreeningEvent') jsonLdEvents.push(item);
                                    }
                                }
                            } catch(e) {}
                        }

                        // 3. Extract dates from DOM date tabs (Fallback)
                        const domDatePills = [];
                        const dateNodes = Array.from(document.querySelectorAll("[class*='movieDateText'], [class*='cinemaDates']"));
                        for (const d of dateNodes) {
                            const txt = (d.innerText || '').replace(/\n+/g, ' ').trim();
                            if (txt) domDatePills.push(txt);
                        }

                        // 4. Extract DOM cinema blocks (Fallback)
                        const domCinemas = [];
                        const timeBtns = Array.from(document.querySelectorAll("button, [role='button'], a"))
                            .filter(b => /\b\d{1,2}:\d{2}\s*(?:AM|PM)\b/i.test(b.innerText || ''));

                        const seenMap = new Map();
                        for (const btn of timeBtns) {
                            let curr = btn.parentElement;
                            let cinemaName = '';
                            let address = '';
                            for (let i = 0; i < 8; i++) {
                                if (!curr) break;
                                const txt = curr.innerText || '';
                                if (txt.includes('km away') || txt.includes('Allows cancellation')) {
                                    const lines = txt.split('\n').map(l => l.trim()).filter(Boolean);
                                    cinemaName = lines[0];
                                    address = lines.find(l => l.includes('km away')) || '';
                                    break;
                                }
                                curr = curr.parentElement;
                            }
                            if (cinemaName) {
                                const timeMatch = (btn.innerText || '').match(/\b\d{1,2}:\d{2}\s*(?:AM|PM)\b/i);
                                if (timeMatch) {
                                    const tStr = timeMatch[0].trim();
                                    if (!seenMap.has(cinemaName)) {
                                        seenMap.set(cinemaName, { address: address, times: new Set() });
                                    }
                                    seenMap.get(cinemaName).times.add(tStr);
                                }
                            }
                        }

                        for (const [cName, val] of seenMap.entries()) {
                            domCinemas.push({
                                theatre_name: cName,
                                address: val.address,
                                showtimes: Array.from(val.times).map(t => ({ time_str: t, format_tag: '2D' }))
                            });
                        }

                        return {
                            nextStateSessions: nextStateSessions,
                            nextShowDates: nextShowDates,
                            contentId: contentId,
                            jsonLdEvents: jsonLdEvents,
                            domDatePills: domDatePills,
                            domCinemas: domCinemas
                        };
                    }
                """)

                theatres_dict: Dict[str, Dict[str, Any]] = {}
                available_dates: set = set()

                # Add dates from Next.js meta
                for d in payload.get("nextShowDates", []):
                    available_dates.add(str(d).strip())

                content_id = payload.get("contentId") or ""

                # 1. Primary: Extract from Next.js arranged sessions
                arranged = payload.get("nextStateSessions") or []
                if arranged:
                    for cinema in arranged:
                        c_data = cinema.get("data") or {}
                        t_name = (c_data.get("name") or cinema.get("entityName") or "").strip()
                        if not t_name:
                            continue
                        t_id = str(c_data.get("id") or cinema.get("entityCode") or re.sub(r"[^\w]+", "-", t_name.lower()))
                        t_addr = c_data.get("address")

                        for s in cinema.get("sessions") or []:
                            # Exact date and exact local time as displayed on District
                            s_date = (s.get("showDate") or "").strip()
                            s_time_text = (s.get("showTimeText") or "").strip()
                            
                            # Fallback to local time string if showTimeText is missing
                            if not s_time_text and s.get("showTimeLocal"):
                                try:
                                    t_part = s["showTimeLocal"].split("T")[1][:5]
                                    s_time_text = datetime.strptime(t_part, "%H:%M").strftime("%I:%M %p")
                                except Exception:
                                    pass

                            if s_date:
                                available_dates.add(s_date)

                            if s_date == target_date and s_time_text:
                                video_fmt = s.get("scrnFmt") or "2D"
                                enc_sess = s.get("encSessionId") or ""
                                mcd = s.get("mcd") or s.get("mid") or ""
                                cid = content_id or s.get("content_id") or ""
                                seat_url = (
                                    f"https://www.district.in/movies/seat-layout/{mcd}?encsessionid={enc_sess}&freeseating=false&fromsessions=true&type=MOVIES&contentid={cid}"
                                    if enc_sess and mcd else None
                                )

                                if t_name not in theatres_dict:
                                    theatres_dict[t_name] = {
                                        "theatre_id": t_id,
                                        "theatre_name": t_name,
                                        "address": t_addr,
                                        "showtimes": []
                                    }

                                if not any(x["time_str"] == s_time_text for x in theatres_dict[t_name]["showtimes"]):
                                    theatres_dict[t_name]["showtimes"].append({
                                        "showtime_id": f"{t_id}-{s_time_text}",
                                        "time_str": s_time_text,
                                        "format_tag": video_fmt,
                                        "booking_url_or_selector": seat_url,
                                        "session_id": enc_sess
                                    })

                # 2. Fallback: If no theatres found via Next.js for target_date, check JSON-LD
                if not theatres_dict:
                    from datetime import timezone, timedelta
                    ist_tz = timezone(timedelta(hours=5, minutes=30))

                    for ev in payload.get("jsonLdEvents", []):
                        start_str = ev.get("startDate", "")
                        if start_str:
                            try:
                                dt = datetime.fromisoformat(start_str)
                                # Convert to India Standard Time if timezone is present
                                if dt.tzinfo:
                                    dt = dt.astimezone(ist_tz)
                                d_key = dt.strftime("%Y-%m-%d")
                                available_dates.add(d_key)

                                if d_key == target_date:
                                    loc = ev.get("location", {})
                                    t_name = loc.get("name", "").strip()
                                    if t_name:
                                        t_id = loc.get("url", "").split("/")[-1] or re.sub(r"[^\w]+", "-", t_name.lower())
                                        time_str = dt.strftime("%I:%M %p")
                                        video_fmt = ev.get("videoFormat", "2D")
                                        offers = ev.get("offers", {})
                                        booking_url = offers.get("url")

                                        if t_name not in theatres_dict:
                                            theatres_dict[t_name] = {
                                                "theatre_id": t_id,
                                                "theatre_name": t_name,
                                                "address": loc.get("address", {}).get("streetAddress"),
                                                "showtimes": []
                                            }

                                        if not any(s["time_str"] == time_str for s in theatres_dict[t_name]["showtimes"]):
                                            theatres_dict[t_name]["showtimes"].append({
                                                "showtime_id": f"{t_id}-{time_str}",
                                                "time_str": time_str,
                                                "format_tag": video_fmt,
                                                "booking_url_or_selector": booking_url,
                                                "session_id": None
                                            })
                            except Exception:
                                pass

                # 3. Fallback: DOM
                if not theatres_dict:
                    for dc in payload.get("domCinemas", []):
                        t_name = dc.get("theatre_name", "").strip()
                        if t_name and dc.get("showtimes"):
                            t_id = re.sub(r"[^\w]+", "-", t_name.lower())
                            theatres_dict[t_name] = {
                                "theatre_id": t_id,
                                "theatre_name": t_name,
                                "address": dc.get("address"),
                                "showtimes": [
                                    {
                                        "showtime_id": f"{t_id}-{s['time_str']}",
                                        "time_str": s["time_str"],
                                        "format_tag": s.get("format_tag", "2D"),
                                        "booking_url_or_selector": None,
                                        "session_id": None
                                    }
                                    for s in dc["showtimes"]
                                ]
                            }

                final_theatres = parse_theatres_and_shows(list(theatres_dict.values()))
                sorted_dates = sorted(list(available_dates))

                logger.info(
                    f"Found {len(final_theatres)} theatres for {target_date}. Open dates: {sorted_dates}"
                )
                return final_theatres, sorted_dates

            except Exception as e:
                logger.error(f"Error fetching theatres and shows: {e}")
                await self._capture_debug_screenshot(page, "shows")
                raise

    async def get_seat_map(
        self,
        movie_url: str,
        target_date: str,
        theatre_name: str,
        showtime_str: str,
        city: str = "Chennai"
    ) -> SeatMapResponse:
        """
        Navigates to the show, extracts exact District seat layout JSON via
        direct seat-layout route or network response interception, and normalizes
        it into SeatMapResponse with authentic seat availability and pricing.
        """
        async with browser_manager.get_page() as page:
            show_url = normalize_movie_showtime_url(movie_url, city=city, target_date=target_date)
            logger.info(
                f"Fetching seat map for '{theatre_name}' at {showtime_str} ({target_date})..."
            )

            intercepted_json: Optional[Dict[str, Any]] = None

            async def handle_response(response: Response):
                nonlocal intercepted_json
                try:
                    url = response.url.lower()
                    if ("select-seat" in url or "seat-layout" in url or "layout" in url) and response.status == 200:
                        ct = response.headers.get("content-type", "")
                        if "application/json" in ct:
                            data = await response.json()
                            if isinstance(data, dict) and ("seatLayout" in data or "colAreas" in str(data) or "objArea" in str(data) or "areas" in data):
                                logger.info(f"Captured seat layout JSON from network: {response.url}")
                                intercepted_json = data
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                await page.goto(show_url, wait_until="domcontentloaded", timeout=35000)
                await page.wait_for_timeout(2000)

                # 1. Inspect Next.js state for the exact showtime's encSessionId, mcd & pricing
                session_meta = await page.evaluate(r"""
                    (args) => {
                        const nextData = window.__NEXT_DATA__?.props?.pageProps?.initialState?.movies;
                        const sessionsObj = nextData?.movieSessions ? Object.values(nextData.movieSessions)[0] : null;
                        if (!sessionsObj) return null;

                        const targetTheatre = (args.theatre_name || '').toLowerCase().trim();
                        const targetTime = (args.showtime_str || '').toLowerCase().trim();
                        const arranged = sessionsObj.arrangedSessions || [];
                        const contentId = sessionsObj.meta?.movie?.content_id || '';
                        const movieTitle = sessionsObj.meta?.movie?.name || '';

                        for (const c of arranged) {
                            const cName = (c.data?.name || c.entityName || '').toLowerCase().trim();
                            const matchTheatre = cName.includes(targetTheatre) || targetTheatre.includes(cName) || 
                                                 (targetTheatre.split(' ')[0].length > 3 && cName.includes(targetTheatre.split(' ')[0]));
                            if (matchTheatre) {
                                for (const s of c.sessions || []) {
                                    const sTime = (s.showTimeText || '').toLowerCase().trim();
                                    const matchTime = sTime === targetTime || 
                                                      sTime.replace(/^0/, '') === targetTime.replace(/^0/, '') || 
                                                      (targetTime && sTime.includes(targetTime));
                                    if (matchTime) {
                                        return {
                                            encSessionId: s.encSessionId,
                                            mcd: s.mcd || s.mid,
                                            contentId: contentId,
                                            audi: s.audi || 'Screen 1',
                                            areas: s.areas || [],
                                            movieTitle: movieTitle
                                        };
                                    }
                                }
                            }
                        }
                        return null;
                    }
                """, {"theatre_name": theatre_name, "showtime_str": showtime_str})

                price_map = {}
                movie_title = None
                if session_meta:
                    movie_title = session_meta.get("movieTitle")
                    for a in session_meta.get("areas") or []:
                        lbl = (a.get("label") or "").upper().strip()
                        if lbl:
                            price_map[lbl] = float(a.get("price") or 0.0)

                    enc = session_meta.get("encSessionId")
                    mcd = session_meta.get("mcd")
                    cid = session_meta.get("contentId")

                    if enc and mcd:
                        direct_seat_url = f"https://www.district.in/movies/seat-layout/{mcd}?encsessionid={enc}&freeseating=false&fromsessions=true&type=MOVIES&contentid={cid}"
                        logger.info(f"Navigating to District seat layout route: {direct_seat_url}")
                        try:
                            await page.goto(direct_seat_url, wait_until="domcontentloaded", timeout=25000)
                            # Wait for select-seat API response
                            for _ in range(20):
                                if intercepted_json:
                                    break
                                await page.wait_for_timeout(300)
                        except Exception as e:
                            logger.warning(f"Direct seat layout navigation failed: {e}")

                # 2. If direct navigation didn't capture JSON, try clicking showtime on page
                if not intercepted_json:
                    # Look for direct seat layout URL from JSON-LD if available
                    direct_seat_url = await page.evaluate(r"""
                        (args) => {
                            const targetTheatre = (args.theatre_name || '').toLowerCase();
                            const targetTime = (args.showtime_str || '').toLowerCase();
                            const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
                            for (const s of scripts) {
                                try {
                                    const parsed = JSON.parse(s.innerText);
                                    const list = Array.isArray(parsed) ? parsed : (parsed['@type'] === 'ScreeningEvent' ? [parsed] : []);
                                    for (const ev of list) {
                                        const tName = (ev.location?.name || '').toLowerCase();
                                        if (tName.includes(targetTheatre) || targetTheatre.includes(tName)) {
                                            if (ev.offers?.url) {
                                                return ev.offers.url;
                                            }
                                        }
                                    }
                                } catch(e) {}
                            }
                            return null;
                        }
                    """, {"theatre_name": theatre_name, "showtime_str": showtime_str})

                    if direct_seat_url and direct_seat_url.startswith("http"):
                        logger.info(f"Found direct seat layout URL from JSON-LD: {direct_seat_url}")
                        try:
                            await page.goto(direct_seat_url, wait_until="domcontentloaded", timeout=25000)
                            for _ in range(15):
                                if intercepted_json:
                                    break
                                await page.wait_for_timeout(300)
                        except Exception:
                            pass

                if not intercepted_json:
                    # Locate the theatre section
                    theatre_blocks = page.locator("[class*='theatre' i], [class*='cinema' i], [class*='venue' i]")
                    count = await theatre_blocks.count()
                    target_block = None

                    for i in range(count):
                        block = theatre_blocks.nth(i)
                        text = await block.inner_text()
                        if matches_theatre(text, theatre_name):
                            target_block = block
                            break

                    search_context = target_block if target_block else page

                    # Find matching showtime button
                    show_btn = search_context.locator(f"button:has-text('{showtime_str}'), a:has-text('{showtime_str}')").first
                    if not await show_btn.is_visible(timeout=2000):
                        clean_time = showtime_str.split()[0]
                        show_btn = search_context.locator(f"button:has-text('{clean_time}'), a:has-text('{clean_time}')").first

                    if await show_btn.is_visible(timeout=2000):
                        logger.info(f"Clicking showtime button '{showtime_str}'...")
                        await show_btn.click()

                    # Handle popups
                    try:
                        accept_btn = page.locator("button:has-text('Accept'), button:has-text('Continue'), button:has-text('I Agree')").first
                        if await accept_btn.is_visible(timeout=1500):
                            await accept_btn.click()
                            await page.wait_for_timeout(500)

                        seat_count_btn = page.locator("button:has-text('Select Seats'), button:has-text('Proceed')").first
                        if await seat_count_btn.is_visible(timeout=1500):
                            await seat_count_btn.click()
                            await page.wait_for_timeout(500)
                    except Exception:
                        pass

                    for _ in range(15):
                        if intercepted_json:
                            break
                        await page.wait_for_timeout(300)

                # 3. Parse Intercepted JSON
                if intercepted_json:
                    parsed = parse_intercepted_seat_json(
                        payload=intercepted_json,
                        movie_title=movie_title,
                        theatre_name=theatre_name,
                        showtime_str=showtime_str,
                        date=target_date,
                        price_map=price_map,
                    )
                    if parsed and parsed.seats:
                        logger.info(
                            f"Successfully parsed real seat map for {theatre_name} ({showtime_str}): "
                            f"{parsed.total_available} available, {parsed.total_sold} sold, {parsed.total_blocked} blocked (Total: {len(parsed.seats)})"
                        )
                        return parsed

                # Check if District page explicitly indicates booking is closed
                is_closed = await page.evaluate(r"""
                    () => {
                        const txt = document.body.innerText || '';
                        return /booking is (?:now )?closed|booking window (?:for this show )?has closed/i.test(txt);
                    }
                """)
                if is_closed:
                    raise RuntimeError(
                        f"Booking is currently closed or not yet open on District for '{theatre_name}' at {showtime_str} ({target_date}). "
                        f"Use Mode 1 (Show Opening Watcher) to get alerted the instant bookings go live!"
                    )

                # 4. Fallback: Parse Seat Map directly from DOM / SVG (Strict validation)
                dom_seat_data = await page.evaluate(r"""
                    () => {
                        const seats = [];
                        const seatNodes = document.querySelectorAll(
                            "[data-seat-id], [data-seat], button[class*='seat' i], div[class*='seat' i]"
                        );

                        // Only allow genuine seat identifiers e.g. A1, H12, or numbers with row
                        const seatPattern = /^([A-Z]{1,2})(\d{1,3})$/i;

                        for (const node of seatNodes) {
                            const rawId = (
                                node.getAttribute('data-seat-id') 
                                || node.getAttribute('data-seat') 
                                || node.innerText.trim()
                            ).toUpperCase();

                            if (!rawId || rawId.length > 6 || !seatPattern.test(rawId)) {
                                continue;
                            }

                            const match = seatPattern.exec(rawId);
                            const rowLabel = match ? match[1].toUpperCase() : '';
                            const seatNum = match ? match[2] : '';

                            const classList = (node.className || '').toLowerCase();
                            const isSold = classList.includes('sold') || classList.includes('booked') || classList.includes('occupied') || node.hasAttribute('disabled');
                            const isBlocked = classList.includes('blocked') || classList.includes('reserved') || classList.includes('locked');
                            let status = 'available';
                            if (isSold) status = 'sold';
                            else if (isBlocked) status = 'blocked';

                            const sectionNode = node.closest("[class*='area' i], [class*='tier' i], [class*='section' i], [class*='category' i]");
                            let category = 'STANDARD';
                            let price = 200;
                            if (sectionNode) {
                                const catText = sectionNode.innerText;
                                if (/recliner/i.test(catText)) { category = 'RECLINER'; price = 450; }
                                else if (/classic/i.test(catText)) { category = 'CLASSIC'; price = 180; }
                                else if (/prime|gold/i.test(catText)) { category = 'PRIME'; price = 250; }
                            }

                            seats.push({
                                seat_id: rawId,
                                row_label: rowLabel,
                                seat_num: seatNum,
                                status: status,
                                category: category,
                                price: price
                            });
                        }

                        const screenEl = document.querySelector("[class*='screen' i]");
                        const screenName = screenEl ? screenEl.innerText.trim() : 'Screen 1';

                        return {
                            screen_name: screenName,
                            seats: seats
                        };
                    }
                """)

                if dom_seat_data and dom_seat_data.get("seats"):
                    return normalize_seat_map_dom(
                        dom_result=dom_seat_data,
                        movie_title=movie_title,
                        theatre_name=theatre_name,
                        showtime_str=showtime_str,
                        date=target_date,
                    )

                raise RuntimeError(
                    f"Could not retrieve real seat map from District for '{theatre_name}' at {showtime_str}. "
                    f"Booking may not be open or seat layout is currently closed by the cinema."
                )

            except Exception as e:
                logger.error(f"Error extracting seat map: {e}")
                await self._capture_debug_screenshot(page, "seat_map")
                raise


# Global client instance
district_client = DistrictClient()
