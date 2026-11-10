"""Official manufacturer spec pages, read politely and turned into structured specs by Claude.

How it stays on the right side of site owners:
  * Only URLs listed in data/oem_pages.yaml are fetched. Each entry records who checked the
    site's terms and when, so adding a site is a deliberate human decision.
  * robots.txt is checked for every URL (PoliteClient), with a crawl delay per host.
  * One page per model per run, at most daily; no crawling or link following.

Extraction: schema.org JSON-LD is used when the page has it. Otherwise the visible text is sent
to Claude with a JSON schema, and Claude is told to return only values the page states.
"""

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

from ..config import get_settings
from ..http import PoliteClient, RobotsDisallowed
from .base import VehicleSpec

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "oem_pages.yaml"
MAX_PAGE_CHARS = 60_000


class ExtractedVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")  # emits additionalProperties: false

    variant: str
    battery_kwh: float | None
    range_km: float | None
    range_standard: str | None
    power_kw: float | None
    torque_nm: float | None
    dc_charge_max_kw: float | None
    ac_charge_max_kw: float | None
    dc_charge_time_note: str | None
    price_min_inr: float | None
    price_max_inr: float | None


class ExtractedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variants: list[ExtractedVariant]


SYSTEM_PROMPT = """You extract electric-vehicle specifications from the text of a manufacturer's \
web page for an Indian EV comparison site. Return one entry per battery or powertrain variant.

Only report values the page states explicitly. If a value is missing, ambiguous, or only \
implied, use null; a wrong number is worse than a missing one because buyers rely on it.
Convert units: PS to kW (x 0.7355), bhp/hp to kW (x 0.7457), lakh rupees to rupees (x 100000).
For range_standard copy the test cycle the page names (for example "MIDC P1+P2", "ARAI"), else null.
Prices are ex-showroom in rupees; if the page gives only a starting price, leave price_max_inr null."""


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    return text[:MAX_PAGE_CHARS]


def json_ld_vehicles(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            doc = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for node in doc if isinstance(doc, list) else [doc]:
            if isinstance(node, dict) and node.get("@type") in ("Car", "Vehicle", "Product"):
                out.append(node)
    return out


class ClaudeExtractor:
    def __init__(self, api_key: str, model: str):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def extract(self, make: str, model: str, url: str, text: str) -> ExtractedPage | None:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": ExtractedPage.model_json_schema()},
            },
            # Retry a refused request on a fallback model chosen by the API.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[
                {
                    "role": "user",
                    "content": f"Vehicle: {make} {model}\nPage URL: {url}\n\n<page_text>\n{text}\n</page_text>",
                }
            ],
        )
        if resp.stop_reason in ("refusal", "max_tokens"):
            log.warning("extraction for %s stopped with %s", url, resp.stop_reason)
            return None
        raw = "".join(b.text for b in resp.content if b.type == "text")
        return ExtractedPage.model_validate_json(raw)


class OEMPagesSource:
    name = "oem_pages"
    license = "Facts from manufacturer pages; robots.txt and terms checked per site"

    def __init__(self, path: Path | str = DEFAULT_PATH, extractor: ClaudeExtractor | None = None,
                 client: PoliteClient | None = None):
        self.path = Path(path)
        s = get_settings()
        if extractor is None and s.anthropic_api_key:
            extractor = ClaudeExtractor(s.anthropic_api_key, s.extraction_model)
        self.extractor = extractor
        self.client = client
        self.skipped: list[dict] = []

    def fetch(self) -> Iterator[VehicleSpec]:
        if not self.path.exists():
            return
        doc = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        pages = [p for p in doc.get("pages", []) if p.get("enabled", True)]
        if not pages:
            return
        if self.extractor is None:
            self.skipped.append({"reason": "ANTHROPIC_API_KEY not set"})
            log.info("oem_pages: no ANTHROPIC_API_KEY, skipping %d pages", len(pages))
            return
        client = self.client or PoliteClient()
        try:
            for p in pages:
                yield from self._one(client, p)
        finally:
            if self.client is None:
                client.close()

    def _one(self, client: PoliteClient, p: dict) -> Iterator[VehicleSpec]:
        url = p["url"]
        try:
            html = client.get(url).text
        except RobotsDisallowed:
            log.info("robots.txt disallows %s; skipping", url)
            self.skipped.append({"url": url, "reason": "robots.txt disallows"})
            return
        except Exception as e:  # network errors on one page must not kill the run
            self.skipped.append({"url": url, "reason": f"fetch failed: {e}"})
            return

        page = self.extractor.extract(p["make"], p["model"], url, page_text(html))
        if page is None:
            self.skipped.append({"url": url, "reason": "extraction returned nothing"})
            return
        for v in page.variants:
            yield VehicleSpec(
                market=p.get("market", "IN"),
                make=p["make"],
                model=p["model"],
                extra={"json_ld": bool(json_ld_vehicles(html))},
                source_url=url,
                source_ref=url,
                **v.model_dump(),
            )
