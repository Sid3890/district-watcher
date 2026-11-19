import os
import re
import json
import asyncio
import logging
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page, Route
from app.config import (
    HEADLESS,
    VIEWPORT,
    TIMEZONE,
    USER_AGENT,
    BLOCKED_DOMAINS,
    BROWSER_STATE_PATH,
    DATA_DIR,
)

logger = logging.getLogger("district_watcher.browser")

class BrowserManager:
    """
    Singleton Playwright Chromium controller with async lock concurrency control.
    Guarantees thread-safety and race-condition prevention across worker polling
    and interactive UI queries.
    """
    def __init__(self):
        self._lock = asyncio.Lock()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._is_ready: bool = False

    async def _init_locked(self) -> None:
        """Internal initialization while self._lock is already held."""
        if self._is_ready and self._context:
            return

        logger.info("Initializing Playwright Chromium instance...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        # Load stored storage_state if exists
        storage_state = None
        if BROWSER_STATE_PATH.exists():
            try:
                storage_state = str(BROWSER_STATE_PATH)
                logger.info(f"Loading persistent browser state from {storage_state}")
            except Exception as e:
                logger.warning(f"Failed to read browser state: {e}")

        self._context = await self._browser.new_context(
            viewport=VIEWPORT,
            timezone_id=TIMEZONE,
            user_agent=USER_AGENT,
            locale="en-IN",
            storage_state=storage_state,
        )

        # Target only known tracker domains for aborting, avoiding global **/* intercept overhead
        async def _abort_route(route: Route):
            try:
                await route.abort()
            except Exception:
                pass

        tracker_pattern = re.compile(r"(" + "|".join([re.escape(d) for d in BLOCKED_DOMAINS]) + r")")
        await self._context.route(tracker_pattern, _abort_route)

        self._is_ready = True
        logger.info("Playwright Chromium initialized and ready.")

    async def initialize(self) -> None:
        """Starts Playwright and sets up browser context."""
        async with self._lock:
            await self._init_locked()

    async def save_storage_state(self) -> None:
        """Persists current browser cookies and localStorage."""
        if self._context:
            try:
                await self._context.storage_state(path=str(BROWSER_STATE_PATH))
                logger.debug(f"Saved browser state to {BROWSER_STATE_PATH}")
            except Exception as e:
                logger.warning(f"Could not save storage state: {e}")

    @asynccontextmanager
    async def get_page(self) -> AsyncGenerator[Page, None]:
        """
        Context manager that acquires the single-instance browser lock,
        allocates a new page (or reuses context), yields the page, and closes it.
        """
        async with self._lock:
            if not self._is_ready or not self._context:
                await self._init_locked()

            page = await self._context.new_page()
            # Set default navigation timeouts
            page.set_default_timeout(35000)
            page.set_default_navigation_timeout(35000)
            try:
                yield page
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

    async def close(self) -> None:
        """Closes browser context and Playwright process cleanly."""
        async with self._lock:
            if self._context:
                await self.save_storage_state()
                try:
                    await self._context.close()
                except Exception:
                    pass
                self._context = None
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            self._is_ready = False
            logger.info("Playwright Chromium shut down cleanly.")

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self._context is not None


# Global singleton
browser_manager = BrowserManager()
