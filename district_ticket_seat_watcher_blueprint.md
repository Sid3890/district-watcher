# Project Blueprint: District (`district.in`) Movie Show & Seat Watcher

## 1. Executive Summary & Technical Feasibility

### 1.1 Is This Possible on District (`district.in`)?
**Yes.** District (by Zomato / Eternal Limited, accessible at `https://www.district.in/movies/`) is a Next.js-based web ticketing platform. Movie listings, theatre schedules, and interactive seat layouts are loaded via structured web routes (`https://www.district.in/movies/<movie-slug>-movie-tickets-in-<city>-<movie-id>`) and dynamic client-side requests.

Because District relies on location context (selected city), dynamic session tokens, and client-rendered seat maps, using **Playwright (headless Chromium automation)** paired with a **local FastAPI web dashboard** is the most resilient and reliable approach:
1. **Resilience:** Playwright executes real JavaScript, maintains valid city/session cookies, and extracts data via both network XHR interception and DOM inspection—avoiding fragile hardcoded API headers.
2. **Visual Seat Selection:** A local web UI (`http://localhost:8000`) allows the user to visually browse movies, pick theatres/showtimes, and click exact seats on a rendered seat map.
3. **Dual-Mode Monitoring:**
   * **Mode 1 (Show Opening Monitor):** Watches a movie + target theatre + target date when bookings are not yet open, firing an instant alert the moment showtimes go live.
   * **Mode 2 (Specific Seat Monitor):** Watches an already-open showtime for specific user-selected seats (e.g., `G12`, `G13`) and alerts the user when tickets are canceled or blocked seats are released.
4. **Laptop Alerts:** Combines native OS desktop notifications with an optional, toggleable Web Audio API sound cue directly on the user's laptop.

---

## 2. Technology Stack & Architecture

### 2.1 Core Stack (100% Local, Zero Cloud Cost)
* **Backend Framework:** Python 3.11+, **FastAPI**, **Uvicorn**
* **Browser Automation & Scraper:** **Playwright** (`playwright` Python package with Chromium)
* **Background Task Scheduler:** `asyncio` background worker loop with randomized jitter (35–55 seconds per poll cycle)
* **Database:** **SQLite** (`aiosqlite`) for persisting active watches, user preferences, and alert logs
* **OS Desktop Notifications:** `plyer` (with native fallbacks: macOS `osascript`, Windows PowerShell Toast / `winotify`, Linux `notify-send`) + Browser Web Notifications API
* **Frontend Dashboard:** Single-page responsive web UI (`templates/index.html`) styled with **Tailwind CSS** (CDN), powered by **Alpine.js** (CDN) or clean Vanilla ES6+, and **Web Audio API** for built-in sound alerts (no external `.mp3` dependencies required)

### 2.2 System Architecture Diagram

```text
+-------------------------------------------------------------------+
|                     USER'S LAPTOP (Localhost)                     |
|                                                                   |
|  +-----------------------------+    +--------------------------+  |
|  |   Web Dashboard (Browser)   |    |  OS Desktop Notification |  |
|  |   http://localhost:8000     |    |  + Optional Sound Chime  |  |
|  |  - City / Movie / Theatre   |    +------------^-------------+  |
|  |  - Interactive Seat Map     |                 |                |
|  |  - Sound ON/OFF Toggle      |                 | Trigger        |
|  +--------------+--------------+                 |                |
|                 | REST API / Polling             |                |
|  +--------------v--------------------------------+-------------+  |
|  |                    FastAPI Backend Server                   |  |
|  |  +-----------------------+   +---------------------------+  |  |
|  |  |   SQLite Database     |   |   Async Polling Worker    |  |  |
|  |  | - watch_jobs          |   | - Randomized 35-55s loop  |  |  |
|  |  | - app_settings        |   | - Mode 1: Show Opening    |  |  |
|  |  | - alert_logs          |   | - Mode 2: Seat Status     |  |  |
|  |  +-----------------------+   +-------------+-------------+  |  |
|  +--------------------------------------------|----------------+  |
|                                               |                   |
|  +--------------------------------------------v----------------+  |
|  |         Playwright Persistent Chromium Controller           |  |
|  |  - Maintains city cookie & session state                    |  |
|  |  - Intercepts XHR/JSON payloads + parses DOM/SVG seat maps  |  |
|  +--------------------------------------------+----------------+  |
+-----------------------------------------------|-------------------+
                                                | HTTPS
                                                v
                                   https://www.district.in/movies
```

### 2.3 Project Directory Structure

```text
district-watcher/
├── requirements.txt
├── run.py                      # Entrypoint: initializes DB, launches FastAPI & opens browser
├── app/
│   ├── __init__.py
│   ├── config.py               # App constants, default intervals, user-agent strings
│   ├── database.py             # SQLite connection, schema initialization, CRUD helpers
│   ├── models.py               # Pydantic schemas for API requests/responses
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── browser_manager.py  # Singleton Playwright Chromium context & lock management
│   │   ├── district_client.py  # City, Movie, Theatre, Showtime, and Seat Map extractors
│   │   └── parsers.py          # Normalizes District DOM/JSON payloads into clean models
│   ├── worker/
│   │   ├── __init__.py
│   │   └── monitor.py          # Continuous background watcher loop (Mode 1 & Mode 2)
│   ├── notifications/
│   │   ├── __init__.py
│   │   └── notifier.py         # Cross-platform OS desktop notifications + frontend event queue
│   └── api/
│       ├── __init__.py
│       └── routes.py           # FastAPI REST endpoints
└── static/
    ├── index.html              # Complete Cinema-themed Dashboard UI
    ├── app.js                  # UI state, interactive seat map renderer, Web Audio synthesizer
    └── styles.css              # Custom styling for seat grid, animations, and dark theme
```

---

## 3. Detailed Functional Specifications

### 3.1 Step-by-Step User Selection Workflow
1. **City Selection:**
   * User selects their city (e.g., *Chennai*, *Bengaluru*, *Mumbai*, *Delhi NCR*, *Hyderabad*, etc.) from a searchable dropdown or enters a custom city slug.
   * The backend sets the city context in Playwright and fetches available movies on `district.in`.
2. **Movie Selection:**
   * Displays active and upcoming movies with poster thumbnail, language, format (2D/3D/IMAX), and District Movie URL/ID.
   * Also supports pasting a direct `https://www.district.in/movies/...` URL as a quick-load shortcut.
3. **Target Date & Theatre Selection:**
   * User selects a **Target Date** (e.g., Friday, Nov 20).
   * The system loads all theatres currently listing the movie for that date, **PLUS** allows the user to enter a **Custom / Expected Theatre Name** (e.g., *"PVR Palazzo, Vadapalani"* or *"AGS Cinemas, Villivakkam"*) in case that theatre has not yet opened bookings for the selected movie/date.

### 3.2 Dual Monitoring Modes

#### Mode 1: Show / Booking Opening Watcher (When Show Hasn't Opened Yet)
* **Trigger Scenario:** The user selects a movie, a target date, and a theatre where bookings have **not** opened yet (either the theatre isn't listed on the movie's page yet, or the chosen date/time slot isn't available).
* **Monitoring Behavior:**
  * Every 35–55 seconds (randomized), the worker refreshes the movie's showtime listing for the target city and date.
  * It performs a fuzzy/case-insensitive match against the target theatre name (and optional preferred time window, e.g., *"Any Showtime"*, *"Evening (6 PM – 11 PM)"*, or specific time).
* **Alert Condition:**
  * The moment the target theatre appears with at least one bookable showtime (or matching time window), the job triggers an **Alert** (`SHOW_OPENED`), fires the desktop notification + optional sound cue, and provides a direct **"Open & Select Seats"** button in the UI so the user can either book immediately or switch the watch to **Mode 2 (Seat Watcher)**.

#### Mode 2: Specific Seat Availability Watcher (When Show Is Already Open)
* **Trigger Scenario:** The movie show is already open in the chosen theatre, and the user wants specific seats (which may currently be occupied, held in someone's 7-minute cart, or blocked by the cinema).
* **Interactive Seat Selection UI:**
  * Clicking **"Load Seat Map"** instructs Playwright to open that exact showtime on District and extract the complete seating chart (Sections/Categories like *Prime*, *Classic*, *Recliner*; Row Labels `A`–`Z`; Seat Numbers; Aisles/Gaps; and current status: `available`, `sold`, or `blocked`).
  * The dashboard renders a visual, clickable seat grid mirroring the theatre layout.
  * User clicks one or more seats (e.g., `H10`, `H11`, `H12`) to mark them as **Watched Seats**.
  * User selects a **Match Rule**:
    * `ANY`: Notify as soon as **any 1** of the selected seats becomes available.
    * `ALL`: Notify only when **all** selected seats are available simultaneously (ideal for groups/couples).
* **Monitoring Behavior:**
  * Every 35–55 seconds, the worker re-fetches the seat map state for that showtime and checks the status of each watched seat ID.
* **Alert Condition:**
  * As soon as the `ANY` or `ALL` condition is satisfied, the job triggers an **Alert** (`SEATS_AVAILABLE`), lists the exact newly available seat IDs (e.g., *"Seats H10, H11 are now OPEN at PVR VR Chennai (7:30 PM)!"*), fires the desktop notification + optional sound cue, and pauses the job to prevent alert spam (with a 1-click **Resume** button).

### 3.3 Notification & Sound Cue System
* **Global & Per-Watch Sound Control:**
  * Prominent **"Sound Alert: ON / OFF"** toggle switch in the top header of the dashboard (persisted in SQLite `app_settings`).
  * Sound synthesizer built using the browser's native **Web Audio API** (generates clean, unmistakable pleasant chimes without relying on external audio files that might fail to load).
  * Includes **3 selectable tones** (*Chime*, *Urgent Pulse*, *Cinema Bell*), **Volume Slider**, and a **"Test Notification & Sound"** button so the user can test both the laptop OS banner and audio cue immediately.
* **Native Laptop Desktop Notification:**
  * Fires at the operating system level (`plyer` / `osascript` / PowerShell Toast / `notify-send`) so the notification appears even if the browser window is minimized or in the background.
  * Also fires a Browser Web Notification (`Notification API`) that focuses the dashboard tab and displays a direct **"Book Now on District"** link when clicked.

---

## 4. District (`district.in`) Scraping & Parsing Implementation Guide

### 4.1 Browser Context & Concurrency Safety
* Use a **single persistent Playwright Chromium instance** managed by an `asyncio.Lock` in `app/scraper/browser_manager.py`.
* Why a lock is mandatory: Interactive UI requests (e.g., user clicking "Load Seat Map") and background worker polls must never collide on the same Playwright page simultaneously.
* Launch Chromium with realistic viewport (`1366x768`), standard desktop User-Agent, and timezone `Asia/Kolkata`.

### 4.2 Navigation & Data Extraction Flow
1. **Setting the City:**
   * Navigate to `https://www.district.in/movies/`.
   * If a city selector modal appears or the current city does not match the user's selected city, click the location selector in the header, type the city name, and select the matching city suggestion. Persist cookies/storage state to `data/browser_state.json`.
2. **Fetching Movies (`get_movies(city)`):**
   * On `https://www.district.in/movies/`, extract all movie cards under "Now Showing" and "Upcoming".
   * Parse the movie URL (`/movies/<slug>-movie-tickets-in-<city>-<id>`), title, poster image URL, and language/format tags.
3. **Fetching Theatres & Showtimes (`get_theatres_and_shows(movie_url, target_date)`):**
   * Navigate to `movie_url`.
   * Select the date tab corresponding to `target_date` (matching day/date label in the horizontal date picker).
   * Wait for cinema blocks to render. Extract:
     * `theatre_name` (e.g., `"PVR: Palazzo, The Nexus Vijaya Mall, Vadapalani, Chennai"`)
     * `theatre_id` (derived from DOM attributes or slug)
     * `showtimes`: list of `{ showtime_id, time_str, format_tag, booking_url_or_selector }`
4. **Fetching the Seat Map (`get_seat_map(movie_url, target_date, theatre_name, time_str)`):**
   * Attach a Playwright response listener (`page.on("response", handle_response)`) before clicking the showtime button to capture any JSON XHR response containing seat layout arrays/objects.
   * Click the specific showtime element.
   * Handle any intermediate popups (e.g., "How many seats?" modal—select default `2` or `1` to proceed to the seat chart, or age-rating disclaimer modal—"Accept / Continue").
   * **Primary Extraction (Network JSON):** Parse intercepted seat layout JSON (mapping section name, row label, column index, seat label like `G12`, and availability boolean/enum).
   * **Fallback Extraction (DOM / SVG Inspection):** If seat layout is rendered directly into HTML/SVG elements without a separate XHR JSON, evaluate a DOM script via `page.evaluate(...)` to inspect row containers and seat nodes (identifying seat labels, bounding-box coordinates for aisle gaps, and CSS classes/attributes indicating `available` vs `sold`/`occupied`/`blocked`).
   * Return a normalized `SeatMapResponse` object to the frontend and background worker.

### 4.3 Rate Limiting & Anti-Detection Guardrails
* **Polling Interval:** Default `45 seconds` with `±10 seconds` uniform random jitter (`35s` to `55s`). Enforce a minimum floor of `25 seconds`.
* **Exponential Backoff:** If District returns HTTP `429` (Too Many Requests), `403`, or a CAPTCHA/rate-limit screen, automatically pause polling for `5 minutes`, log a warning banner in the UI, and retry gracefully.
* **Resource Blocking (Speed Optimization):** Block heavy third-party analytics/ad scripts (`*.doubleclick.net`, `*.google-analytics.com`) while keeping District's core JS, CSS, and API calls intact so seat maps load in under 2–3 seconds.

---

## 5. Database Schema (SQLite)

Create `data/watcher.db` automatically on startup with the following tables:

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sound_enabled INTEGER NOT NULL DEFAULT 1,
    sound_tone TEXT NOT NULL DEFAULT 'chime',
    sound_volume REAL NOT NULL DEFAULT 0.8,
    desktop_notifications_enabled INTEGER NOT NULL DEFAULT 1,
    poll_interval_seconds INTEGER NOT NULL DEFAULT 45,
    last_selected_city TEXT DEFAULT 'Chennai'
);

INSERT OR IGNORE INTO app_settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS watch_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL CHECK (mode IN ('SHOW_OPENING', 'SEAT_AVAILABILITY')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PAUSED', 'TRIGGERED')),
    city TEXT NOT NULL,
    movie_title TEXT NOT NULL,
    movie_url TEXT NOT NULL,
    target_date TEXT NOT NULL,                 -- ISO format YYYY-MM-DD
    theatre_name TEXT NOT NULL,
    showtime_str TEXT,                         -- Required for SEAT_AVAILABILITY; optional filter for SHOW_OPENING
    watched_seats_json TEXT,                   -- JSON array e.g. ["G10", "G11"] (NULL for SHOW_OPENING)
    match_rule TEXT DEFAULT 'ANY' CHECK (match_rule IN ('ANY', 'ALL')),
    last_checked_at TEXT,
    last_check_summary TEXT,
    triggered_details_json TEXT,               -- Details of matched show or open seats when triggered
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alert_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_job_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,                  -- 'SHOW_OPENED' | 'SEATS_AVAILABLE'
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (watch_job_id) REFERENCES watch_jobs(id) ON DELETE CASCADE
);
```

---

## 6. REST API Specification (FastAPI)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Returns backend status, Playwright readiness, and active watch count. |
| `GET` | `/api/settings` | Fetches current global settings (sound ON/OFF, tone, volume, poll interval). |
| `PUT` | `/api/settings` | Updates global settings (e.g., toggling `sound_enabled` or changing `poll_interval_seconds`). |
| `GET` | `/api/movies?city={city}` | Scrapes & caches current movies on District for the specified city. |
| `GET` | `/api/shows?movie_url={url}&date={YYYY-MM-DD}` | Fetches theatres and open showtimes for a movie on a given date. |
| `POST` | `/api/seat-map` | Body: `{ movie_url, date, theatre_name, showtime_str }`. Returns normalized seating chart JSON. |
| `GET` | `/api/watches` | Lists all `ACTIVE`, `PAUSED`, and `TRIGGERED` watch jobs. |
| `POST` | `/api/watches` | Creates a new Mode 1 (`SHOW_OPENING`) or Mode 2 (`SEAT_AVAILABILITY`) watch job. |
| `PATCH` | `/api/watches/{id}/status` | Toggles job status (`ACTIVE` <-> `PAUSED`) or resets a `TRIGGERED` job back to `ACTIVE`. |
| `DELETE` | `/api/watches/{id}` | Deletes a watch job. |
| `GET` | `/api/alerts/unacknowledged` | Polled every 3s by the frontend to trigger browser sound cues and banner modals when a background worker fires an alert. |
| `POST` | `/api/alerts/{id}/ack` | Marks an alert as acknowledged (stops repeating sound if looping). |
| `POST` | `/api/test-alert` | Fires a test OS desktop notification and signals the frontend to play the configured sound cue. |

---

## 7. Frontend Dashboard & Audio UX Specification

### 7.1 Visual Layout (`static/index.html`)
* **Theme:** Sleek dark cinema aesthetic (`#0B0F19` background, `#111827` cards, `#10B981` emerald accents for available seats, `#06B6D4` cyan highlights for user-selected seats).
* **Top Navigation Bar:**
  * App Title: **District Watch** with live pulsing status indicator (*Worker Running* / *Checking Now...*).
  * **Sound Cue Switch:** Prominent toggle button (`🔊 Sound Alert: ON` / `🔇 Sound Alert: OFF`) with tone selector dropdown and **"Test Alert"** button.
* **Left Panel — Create New Watch Wizard:**
  1. **Step 1:** Select City + Select Movie (or paste District Movie URL).
  2. **Step 2:** Select Target Date + Choose Theatre from list **OR** type a Theatre Name manually (if bookings haven't opened yet).
  3. **Step 3 (Automatic Mode Switch):**
     * **If Theatre / Showtime is NOT open yet:** Automatically highlights **Mode 1: Notify Me When Bookings Open** with an optional preferred time-of-day filter and a **"Start Show Opening Watch"** button.
     * **If Theatre & Showtime ARE open:** Displays available showtime pills (e.g., `10:30 AM`, `2:15 PM`, `6:45 PM`, `10:15 PM`). Clicking a showtime opens the **Interactive Seat Map Grid**.
  4. **Interactive Seat Map Component:**
     * Displays curved **"SCREEN THIS WAY"** indicator at the top.
     * Groups rows by ticket tier/price (e.g., *RECLINER - ₹450*, *PRIME - ₹220*).
     * Renders every seat as an interactive button labeled with its seat number:
       * **Available:** Green border, clickable (shows hint: *"Currently open — click to watch anyway if waiting for companion seats"*).
       * **Sold / Occupied:** Dark grey, clickable so the user can watch occupied seats in case they get canceled/released.
       * **Blocked / Reserved:** Amber tint, clickable (cinema-blocked seats often release 1–2 hours before showtime).
       * **Selected by User:** Bright Cyan fill with glow ring.
     * Match Rule toggle: **Notify when ANY selected seat opens** vs **Notify when ALL selected seats open**.
     * **"Start Seat Watch"** button.
* **Right Panel — Active Watches & Alert History:**
  * Live cards for each watch job showing:
    * Mode badge (`SHOW OPENING` vs `SEAT WATCH`)
    * Movie, Theatre, Date, Showtime, and Watched Seat chips (e.g., `G10`, `G11`)
    * Last checked timestamp & live status message (e.g., *"Checked 12s ago — H10, H11 still booked"*)
    * Quick actions: **Pause/Resume**, **Open District Page**, **Delete**
  * **Alert Trigger Modal / Banner:** When a match occurs, displays a high-visibility modal with the exact details, plays the selected Web Audio chime (if `sound_enabled == true`), and offers a direct **"Book Now on District ↗"** button.

### 7.2 Web Audio API Synthesizer (`static/app.js`)
* Must unlock `AudioContext` on the user's first click anywhere in the dashboard (and display a subtle *"Click anywhere to arm audio alerts"* badge if `AudioContext.state === 'suspended'`).
* Synthesizes clean polyphonic tones using `OscillatorNode` + `GainNode` with smooth exponential decay:
  * `chime`: Pleasant ascending major triad (`C5 -> E5 -> G5 -> C6`).
  * `bell`: Classic cinema double-ding (`A5 -> E5`).
  * `pulse`: Urgent 3-beep radar alert (`880Hz` pulses).

---

## 8. Step-by-Step Build & Verification Plan for Antigravity

When executing this blueprint, follow these phases in order:

1. **Phase 1: Environment & Dependency Setup**
   * Create the project directory structure (`district-watcher/`).
   * Create `requirements.txt` containing: `fastapi`, `uvicorn[standard]`, `playwright`, `aiosqlite`, `pydantic`, `plyer`, `python-dotenv`.
   * Install Python dependencies and run `playwright install chromium`.
2. **Phase 2: Database & Notification Foundation**
   * Implement `app/database.py` with automatic SQLite table creation and default settings seeding.
   * Implement `app/notifications/notifier.py` supporting native OS notifications (`plyer` with platform fallbacks for Windows/macOS/Linux so it never crashes if a desktop daemon is absent) and database alert logging.
3. **Phase 3: Playwright Scraper Engine (`district.in`)**
   * Implement `app/scraper/browser_manager.py` with an async lock and persistent browser profile.
   * Implement `app/scraper/district_client.py` and `app/scraper/parsers.py` to handle city selection, movie fetching, theatre/showtime extraction, and seat map XHR/DOM parsing.
   * Include robust error handling, screenshot-on-error debugging (`data/debug_error.png`), and graceful fallbacks.
4. **Phase 4: Background Polling Worker & FastAPI Routes**
   * Implement `app/worker/monitor.py` running as a FastAPI lifespan background task, checking `ACTIVE` jobs with randomized 35–55s intervals for both `SHOW_OPENING` and `SEAT_AVAILABILITY` modes.
   * Implement all REST endpoints in `app/api/routes.py`.
5. **Phase 5: Frontend Dashboard & End-to-End Verification**
   * Build `static/index.html`, `static/styles.css`, and `static/app.js` with the complete wizard, interactive seat map grid, active watch list, and Web Audio synthesizer.
   * Start the server via `python run.py`, verify `/api/health`, test `/api/test-alert` (confirming desktop notification + sound toggle behavior), and run a live Playwright test against `https://www.district.in/movies/` to confirm movie, theatre, and seat-map extraction work end-to-end.