import sys
import os
import time
import threading
import logging
from typing import Optional

logger = logging.getLogger("district_watcher.sound_alarm")

class LocalAlarmPlayer:
    """
    Local OS-level audio alarm player.
    Plays a continuous, attention-grabbing looping alarm sound directly on the host machine
    so the user does NOT need to keep the browser open to hear the alert.
    """
    def __init__(self):
        self._is_ringing: bool = False
        self._lock = threading.Lock()
        self._stop_timer: Optional[threading.Timer] = None
        self._custom_thread: Optional[threading.Thread] = None

    @property
    def is_ringing(self) -> bool:
        return self._is_ringing

    def start_alarm(self, timeout_seconds: int = 60) -> None:
        """Starts continuous looping alarm audio on the local computer."""
        with self._lock:
            if self._is_ringing:
                logger.info("Local alarm is already ringing.")
                return

            self._is_ringing = True
            logger.info(f"🚨 Starting continuous local OS sound cue (timeout: {timeout_seconds}s)...")

            # Cancel any previous auto-silence timer
            if self._stop_timer:
                self._stop_timer.cancel()
                self._stop_timer = None

            # Schedule auto-silence after timeout_seconds (safety timeout)
            self._stop_timer = threading.Timer(timeout_seconds, self.stop_alarm)
            self._stop_timer.daemon = True
            self._stop_timer.start()

            # Platform-specific audio playback
            if sys.platform == "win32":
                self._start_windows_alarm()
            elif sys.platform == "darwin":
                self._start_macos_alarm()
            else:
                self._start_linux_alarm()

    def stop_alarm(self) -> None:
        """Silences the continuous local alarm audio immediately."""
        with self._lock:
            if not self._is_ringing:
                return

            self._is_ringing = False
            logger.info("🔇 Local OS alarm silenced.")

            if self._stop_timer:
                self._stop_timer.cancel()
                self._stop_timer = None

            if sys.platform == "win32":
                try:
                    import winsound
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception as e:
                    logger.debug(f"winsound stop failed: {e}")

    def _start_windows_alarm(self) -> None:
        try:
            import winsound
            # Candidate alarm sound files in Windows Media directory
            candidates = [
                r"C:\Windows\Media\Alarm01.wav",
                r"C:\Windows\Media\Alarm02.wav",
                r"C:\Windows\Media\Alarm03.wav",
                r"C:\Windows\Media\ringout.wav",
                r"C:\Windows\Media\tada.wav",
            ]
            chosen_wav = None
            for p in candidates:
                if os.path.exists(p):
                    chosen_wav = p
                    break

            if chosen_wav:
                # Play continuously in loop asynchronously via native Windows audio
                winsound.PlaySound(
                    chosen_wav,
                    winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP
                )
                logger.info(f"Playing Windows native alarm loop from {chosen_wav}")
            else:
                # Fallback to oscillating frequency beeps in a background daemon thread
                self._start_beep_loop()

        except Exception as e:
            logger.warning(f"Failed to play Windows native alarm sound: {e}; falling back to beeps.")
            self._start_beep_loop()

    def _start_beep_loop(self) -> None:
        def beep_worker():
            import winsound
            while self._is_ringing:
                try:
                    winsound.Beep(900, 250)
                    if not self._is_ringing:
                        break
                    time.sleep(0.08)
                    winsound.Beep(1200, 300)
                    if not self._is_ringing:
                        break
                    time.sleep(0.4)
                except Exception:
                    break

        self._custom_thread = threading.Thread(target=beep_worker, daemon=True)
        self._custom_thread.start()

    def _start_macos_alarm(self) -> None:
        import subprocess
        def mac_worker():
            while self._is_ringing:
                try:
                    subprocess.run(["afplay", "/System/Library/Sounds/Ping.aiff"], timeout=3, check=False)
                    time.sleep(0.3)
                except Exception:
                    break
        self._custom_thread = threading.Thread(target=mac_worker, daemon=True)
        self._custom_thread.start()

    def _start_linux_alarm(self) -> None:
        import subprocess
        def linux_worker():
            while self._is_ringing:
                try:
                    subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"], timeout=3, check=False)
                    time.sleep(0.5)
                except Exception:
                    break
        self._custom_thread = threading.Thread(target=linux_worker, daemon=True)
        self._custom_thread.start()


# Global alarm instance
local_alarm = LocalAlarmPlayer()
