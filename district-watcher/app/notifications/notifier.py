import sys
import os
import subprocess
import asyncio
import logging
from typing import Optional
import httpx
from app.config import NTFY_TOPIC
from app.database import get_settings, create_alert_log
from app.notifications.sound_alarm import local_alarm

logger = logging.getLogger("district_watcher.notifier")

def _send_windows_toast(title: str, message: str) -> bool:
    """Send a native Windows notification via PowerShell WinRT Toast using env vars for safe formatting."""
    env = os.environ.copy()
    env["TOAST_TITLE"] = title
    env["TOAST_MSG"] = message

    toast_cmd = """
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
        $xml.LoadXml($template.GetXml())
        $textNodes = $xml.GetElementsByTagName('text')
        $textNodes.Item(0).AppendChild($xml.CreateTextNode($env:TOAST_TITLE)) | Out-Null
        $textNodes.Item(1).AppendChild($xml.CreateTextNode($env:TOAST_MSG)) | Out-Null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('District Watcher').Show($toast)
        exit 0
    } catch {
        exit 1
    }
    """
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", toast_cmd],
            capture_output=True,
            timeout=8,
            check=False,
            env=env
        )
        return res.returncode == 0
    except Exception as e:
        logger.warning(f"PowerShell toast notification failed: {e}")
        return False

def _send_macos_notification(title: str, message: str) -> bool:
    safe_title = title.replace('"', '\\"')
    safe_msg = message.replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5, check=False)
        return res.returncode == 0
    except Exception as e:
        logger.warning(f"macOS notification failed: {e}")
        return False

def _send_linux_notification(title: str, message: str) -> bool:
    try:
        res = subprocess.run(["notify-send", title, message], capture_output=True, timeout=5, check=False)
        return res.returncode == 0
    except Exception as e:
        logger.warning(f"Linux notify-send failed: {e}")
        return False

def send_os_desktop_notification(title: str, message: str) -> None:
    """Send desktop notification using OS-native notification systems."""
    if sys.platform == "win32":
        if _send_windows_toast(title, message):
            logger.info(f"Windows desktop toast notification sent: {title}")
            return
    elif sys.platform == "darwin":
        if _send_macos_notification(title, message):
            logger.info(f"macOS desktop notification sent: {title}")
            return
    elif sys.platform.startswith("linux"):
        if _send_linux_notification(title, message):
            logger.info(f"Linux desktop notification sent: {title}")
            return

    # Fallback to plyer
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="District Watcher",
            timeout=10,
        )
        logger.info(f"Notification sent via plyer: {title}")
    except Exception as e:
        logger.debug(f"plyer fallback notification failed: {e}")

async def send_phone_push_notification(title: str, message: str, click_url: Optional[str] = None) -> bool:
    """Send free push notification to user's phone via ntfy.sh (works when phone is locked & screen off)."""
    topic = (NTFY_TOPIC or "").strip()
    if not topic:
        return False
    
    headers = {
        "Title": title,
        "Priority": "urgent",
        "Tags": "ticket,loudspeaker,movie_camera",
    }
    if click_url:
        headers["Click"] = click_url

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://ntfy.sh/{topic}",
                content=message.encode("utf-8"),
                headers=headers,
            )
            if resp.status_code == 200:
                logger.info(f"Phone push notification sent via ntfy.sh/{topic}")
                return True
            else:
                logger.warning(f"ntfy.sh responded with {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        logger.warning(f"ntfy push notification failed: {e}")
        return False

async def trigger_alert(
    watch_job_id: int,
    event_type: str,
    title: str,
    message: str,
    click_url: Optional[str] = None,
) -> int:
    """
    Records alert in SQLite DB, fires OS desktop notification, rings local host alarm,
    and pushes to user's phone via ntfy.sh (so the phone rings even if browser is closed).
    """
    logger.info(f"Triggering Alert for job #{watch_job_id} [{event_type}]: {title}\n{message}")
    
    # 1. Log in database for UI polling / history
    alert_id = await create_alert_log(
        watch_job_id=watch_job_id,
        event_type=event_type,
        title=title,
        message=message,
    )

    # 2. Check settings for desktop notifications & local audio alarm
    settings = await get_settings()
    if settings.get("desktop_notifications_enabled", True):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, send_os_desktop_notification, title, message)

    # 3. Continuous local OS audio cue (runs on host so browser does not need to be open)
    if settings.get("sound_enabled", True):
        local_alarm.start_alarm(timeout_seconds=60)

    # 4. Instant push notification to phone (ntfy.sh)
    await send_phone_push_notification(title, message, click_url)

    return alert_id
