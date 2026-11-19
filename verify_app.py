import httpx
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    print("=" * 60)
    print("🚀 RUNNING DISTRICT WATCHER END-TO-END VERIFICATION")
    print("=" * 60)

    client = httpx.Client(base_url=BASE_URL, timeout=35.0)

    # 1. Health check
    print("\n[1] Testing GET /api/health...")
    resp = client.get("/api/health")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    health = resp.json()
    print("    Health:", json.dumps(health))
    assert health["status"] == "ok"

    # 2. UI HTML Serving
    print("\n[2] Testing GET / (Index UI)...")
    resp = client.get("/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "District Watch" in resp.text
    print(f"    Index HTML loaded successfully ({len(resp.text)} bytes)")

    # 3. Settings Get and Update
    print("\n[3] Testing GET /api/settings and PUT /api/settings...")
    # Reset to ON first
    client.put("/api/settings", json={"sound_enabled": True, "sound_tone": "chime", "sound_volume": 0.8})
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    settings = resp.json()
    print("    Current settings:", settings)
    assert settings["sound_enabled"] is True

    # Test toggling sound and updating tone & volume
    resp = client.put("/api/settings", json={"sound_enabled": False, "sound_tone": "bell", "sound_volume": 0.95})
    assert resp.status_code == 200
    updated = resp.json()
    print("    Updated settings (Sound OFF):", updated)
    assert updated["sound_enabled"] is False
    assert updated["sound_tone"] == "bell"
    assert updated["sound_volume"] == 0.95

    # Toggle back to sound ON
    resp = client.put("/api/settings", json={"sound_enabled": True, "sound_tone": "chime", "sound_volume": 0.8})
    assert resp.status_code == 200
    assert resp.json()["sound_enabled"] is True
    print("    Restored settings (Sound ON)")

    # 4. Test Alert Trigger
    print("\n[4] Testing POST /api/test-alert (Desktop notification & audio cue trigger)...")
    resp = client.post("/api/test-alert", json={"title": "Verification Test", "message": "Antigravity live verification alert"})
    assert resp.status_code == 200
    alert_info = resp.json()
    print("    Test alert response:", alert_info)
    alert_id = alert_info["alert_id"]

    # 5. Check Unacknowledged Alerts
    print("\n[5] Testing GET /api/alerts/unacknowledged...")
    resp = client.get("/api/alerts/unacknowledged")
    assert resp.status_code == 200
    unacked = resp.json()
    print(f"    Unacknowledged alerts count: {len(unacked)}")
    assert any(a["id"] == alert_id for a in unacked)

    # 6. Acknowledge Alert
    print(f"\n[6] Testing POST /api/alerts/{alert_id}/ack...")
    resp = client.post(f"/api/alerts/{alert_id}/ack")
    assert resp.status_code == 200
    print("    Alert acknowledged successfully")

    # Verify no longer in unacknowledged
    resp = client.get("/api/alerts/unacknowledged")
    remaining_unacked = [a for a in resp.json() if a["id"] == alert_id]
    assert len(remaining_unacked) == 0, "Alert should be acknowledged"

    # 7. Test Live Showtimes on District
    print("\n[7] Testing GET /api/shows with Avengers: Doomsday on Dec 19 in Chennai...")
    resp = client.get("/api/shows", params={
        "movie_url": "https://www.district.in/movies/avengers-doomsday-movie-tickets-MV176735",
        "date": "2026-12-19",
        "city": "Chennai"
    })
    assert resp.status_code == 200
    shows_data = resp.json()
    theatres = shows_data["theatres"]
    print(f"    Found {len(theatres)} theatres on Dec 19:")
    for t in theatres[:3]:
        times = [s["time_str"] for s in t["showtimes"]]
        print(f"      - {t['theatre_name']}: {times}")
    assert len(theatres) >= 1, "Should find at least 1 theatre on Dec 19"

    # 8. Create Mode 1 (Show Opening) Watch Job
    print("\n[8] Testing POST /api/watches (Mode 1: SHOW_OPENING)...")
    mode1_payload = {
        "mode": "SHOW_OPENING",
        "city": "Chennai",
        "movie_title": "Avengers: Doomsday",
        "movie_url": "https://www.district.in/movies/avengers-doomsday-movie-tickets-MV176735",
        "target_date": "2026-12-25",
        "theatre_name": "PVR Palazzo, The Nexus Vijaya Mall, Chennai",
        "showtime_str": "Evening",
    }
    resp = client.post("/api/watches", json=mode1_payload)
    assert resp.status_code == 200
    job1 = resp.json()
    print(f"    Created Job #{job1['id']} [{job1['mode']}]: {job1['movie_title']} @ {job1['theatre_name']}")

    # 9. Create Mode 2 (Seat Availability) Watch Job
    print("\n[9] Testing POST /api/watches (Mode 2: SEAT_AVAILABILITY)...")
    mode2_payload = {
        "mode": "SEAT_AVAILABILITY",
        "city": "Chennai",
        "movie_title": "Avengers: Doomsday",
        "movie_url": "https://www.district.in/movies/avengers-doomsday-movie-tickets-in-chennai-MV176735",
        "target_date": "2026-12-19",
        "theatre_name": "PVR Aerohub, Chennai",
        "showtime_str": "09:25 AM",
        "watched_seats": ["G10", "G11"],
        "match_rule": "ANY",
    }
    resp = client.post("/api/watches", json=mode2_payload)
    assert resp.status_code == 200
    job2 = resp.json()
    print(f"    Created Job #{job2['id']} [{job2['mode']}]: {job2['movie_title']} watching seats {job2['watched_seats']}")

    # 10. List Watches
    print("\n[10] Testing GET /api/watches...")
    resp = client.get("/api/watches")
    assert resp.status_code == 200
    all_jobs = resp.json()
    print(f"    Total active jobs in queue: {len(all_jobs)}")
    assert len(all_jobs) >= 2

    # 11. Seat Map Extraction API
    print("\n[11] Testing POST /api/seat-map...")
    seat_req = {
        "movie_url": "https://www.district.in/movies/avengers-doomsday-movie-tickets-in-chennai-MV176735",
        "date": "2026-12-19",
        "theatre_name": "PVR Aerohub, Chennai",
        "showtime_str": "09:25 AM",
    }
    resp = client.post("/api/seat-map", json=seat_req)
    assert resp.status_code == 200
    s_map = resp.json()
    print(f"    Seat map parsed: Screen: {s_map['screen_name']}, Total Seats: {len(s_map['seats'])}")
    print(f"    Available: {s_map['total_available']}, Sold: {s_map['total_sold']}, Categories: {[c['name'] for c in s_map['categories']]}")
    assert len(s_map["seats"]) > 0

    # 12. Delete Test Watch
    print(f"\n[12] Testing DELETE /api/watches/{job2['id']}...")
    resp = client.delete(f"/api/watches/{job2['id']}")
    assert resp.status_code == 200
    print("    Deleted test watch successfully")

    print("\n" + "=" * 60)
    print("✨ ALL 12 VERIFICATION SUITES PASSED FLAWLESSLY! ✨")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
