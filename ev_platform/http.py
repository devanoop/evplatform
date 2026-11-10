"""A polite HTTP client: honours robots.txt, identifies itself, rate-limits per host, retries.

Every source that touches the web goes through this, so robots.txt rules and crawl delays are
enforced in one place. Note robots.txt is necessary but not sufficient: a site's terms of use
can still forbid automated access, which is why OEM URLs are an explicit allowlist in
data/oem_pages.yaml that a human reviews before adding a site.
"""

import logging
import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import get_settings

log = logging.getLogger(__name__)


class RobotsDisallowed(Exception):
    pass


class PoliteClient:
    def __init__(self, user_agent: str | None = None, delay: float | None = None):
        s = get_settings()
        self.user_agent = user_agent or s.http_user_agent
        self.delay = s.crawl_delay_seconds if delay is None else delay
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Language": "en-IN,en;q=0.8"},
            timeout=s.http_timeout_seconds,
            follow_redirects=True,
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # robots.txt -----------------------------------------------------------------------
    def _robots_for(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = RobotFileParser()
            try:
                r = self._client.get(origin + "/robots.txt")
                if r.status_code in (401, 403):
                    # Per RFC 9309 an access-restricted robots.txt means "assume disallowed".
                    rp.disallow_all = True
                elif r.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError as e:
                log.warning("robots.txt unreachable for %s (%s); treating as disallowed", origin, e)
                rp.disallow_all = True
            self._robots[origin] = rp
        return self._robots[origin]

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        return rp is None or rp.can_fetch(self.user_agent, url)

    # throttling -----------------------------------------------------------------------
    def _wait_turn(self, url: str) -> None:
        host = urlsplit(url).netloc
        rp = self._robots.get(f"{urlsplit(url).scheme}://{host}")
        delay = self.delay
        if rp is not None:
            crawl_delay = rp.crawl_delay(self.user_agent)
            if crawl_delay:
                delay = max(delay, float(crawl_delay))
        with self._lock:
            last = self._last_hit.get(host)
            if last is not None:
                wait = last + delay - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            self._last_hit[host] = time.monotonic()

    # public ---------------------------------------------------------------------------
    def get(self, url: str, *, check_robots: bool = True, retries: int = 3, **kw) -> httpx.Response:
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(url)
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._wait_turn(url)
            try:
                r = self._client.get(url, **kw)
                if r.status_code in (429, 502, 503, 504):
                    retry_after = r.headers.get("Retry-After")
                    sleep = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt * 5
                    log.info("%s returned %s, backing off %.0fs", url, r.status_code, sleep)
                    time.sleep(min(sleep, 120))
                    continue
                r.raise_for_status()
                return r
            except httpx.TransportError as e:
                last_exc = e
                time.sleep(2**attempt)
        if last_exc:
            raise last_exc
        raise httpx.HTTPError(f"giving up on {url} after {retries} attempts")
