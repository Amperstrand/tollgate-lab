"""Playwright browser testing integration for labgrid.

Labgrid has no native Playwright support. This driver provides browser
automation as a labgrid-compatible driver.
"""

import logging
import attr

from labgrid import target_factory
from labgrid.driver import Driver


@target_factory.reg_driver
@attr.s(eq=False)
class PlaywrightBrowserDriver(Driver):
    """Browser automation via Playwright, registered with labgrid.

    ```yaml
    targets:
      browser:
        resources:
          NetworkService:
            address: "192.168.1.1"
        drivers:
          PlaywrightBrowserDriver:
            headless: true
    ```
    """

    bindings = {"network": "NetworkService"}
    headless = attr.ib(default=True)

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self.logger = logging.getLogger(f"{self}({self.target})")
        self._playwright = None
        self._browser = None
        self._page = None

    def on_activate(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self.logger.info("Playwright browser started")

    def on_deactivate(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self.logger.info("Playwright browser stopped")

    def goto(self, url: str):
        """Navigate to a URL."""
        self._page.goto(url)

    def click(self, selector: str):
        """Click an element by CSS selector."""
        self._page.click(selector)

    def fill(self, selector: str, value: str):
        """Fill a form field."""
        self._page.fill(selector, value)

    def screenshot(self, path: str):
        """Capture a screenshot."""
        self._page.screenshot(path=path)

    @property
    def title(self) -> str:
        """Get the current page title."""
        return self._page.title()

    @property
    def url(self) -> str:
        """Get the current page URL."""
        return self._page.url

    def wait_for_selector(self, selector: str, timeout: float = 30.0):
        """Wait for an element to appear."""
        self._page.wait_for_selector(selector, timeout=int(timeout * 1000))
