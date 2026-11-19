import sys
import os
import subprocess
import asyncio
import logging
from typing import Optional
from app.database import get_settings, create_alert_log

logger = logging.getLogger("district_watcher.notifier")

def _send_windows_toast(title: str, message: str) -> bool:
    """Send a native Windows notification via PowerShell (Toast or Balloon fallback)."""
    # Clean text to prevent command injection
    safe_title = title.replace('"', '`"').replace("'", "''")
    safe_msg = message.replace('"', '`"').replace("'", "''")

    # 1. Attempt WinRT Toast Notification
    toast_cmd = f"""
    try {{
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
        $xml.LoadXml($template.GetXml())
        $textNodes = $xml.GetElementsByTagName('text')
        $textNodes.Item(0).AppendChild($xml.CreateTextNode('{safe_title}')) | Out-Null
        $textNodes.Item(1).AppendChild($xml.CreateTextNode('{safe_msg}')) | Out-Null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('District Watcher').Show($toast)
        exit 0
    }} catch {{
        # Fallback to NotifyIcon balloon
        [void] [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
        $objNotifyIcon = New-Object System.Windows.Forms.NotifyIcon
        $objNotifyIcon.Icon = [System.Drawing.SystemIcons]::Information
        $objNotifyIcon.BalloonTipIcon = 'Info'
        $objNotifyIcon.BalloonTipTitle = '{safe_title}'
        $objNotifyIcon.BalloonTipText = '{safe_msg}'
        $objNotifyIcon.Visible = $True
        $objNotifyIcon.ShowBalloonTip(10000)
        Start-Sleep -Seconds 1
        $objNotifyIcon.Dispose()
    }}
    """
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", toast_cmd],
            capture_output=True,
            timeout=8,
            check=False
        )
        return True
    except Exception as e:
        logger.warning(f"PowerShell toast notification failed: {e}")
        return False

def _send_macos_notification(title: str, message: str) -> bool:
    safe_title = title.replace('"', '\\"')
    safe_msg = message.replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5, check=False)
        return True
    except Exception as e:
        logger.warning(f"macOS notification failed: {e}")
        return False

def _send_linux_notification(title: str, message: str) -> bool:
    try:
        subprocess.run(["notify-send", title, message], capture_output=True, timeout=5, check=False)
        return True
    except Exception as e:
        logger.warning(f"Linux notify-send failed: {e}")
        return False

def send_os_desktop_notification(title: str, message: str) -> None:
    """Send desktop notification using plyer with platform-specific native fallbacks."""
    # First try plyer
    plyer_succeeded = False
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="District Watcher",
            timeout=10,
        )
        plyer_succeeded = True
        logger.info(f"Notification sent via plyer: {title} - {message}")
    except Exception as e:
        logger.debug(f"plyer.notification.notify failed ({e}), trying native platform fallback...")

    if not plyer_succeeded:
        if sys.platform == "win32":
            _send_windows_toast(title, message)
        elif sys.platform == "darwin":
            _send_macos_notification(title, message)
        elif sys.platform.startswith("linux"):
            _send_linux_notification(title, message)

async def trigger_alert(
    watch_job_id: int,
    event_type: str,
    title: str,
    message: str,
) -> int:
    """
    Records alert in SQLite DB and fires OS desktop notification (if enabled in settings).
    The frontend polling /api/alerts/unacknowledged handles browser chime + popup banner.
    """
    logger.info(f"Triggering Alert for job #{watch_job_id} [{event_type}]: {title} - {message}")
    
    # 1. Log in database for UI polling / history
    alert_id = await create_alert_log(
        watch_job_id=watch_job_id,
        event_type=event_type,
        title=title,
        message=message,
    )

    # 2. Check settings for desktop notifications
    settings = await get_settings()
    if settings.get("desktop_notifications_enabled", True):
        # Run desktop notification in threadpool so it doesn't block async event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, send_os_desktop_notification, title, message)

    return alert_id
