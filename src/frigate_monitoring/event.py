"""FrigateEvent: per-detection detail fetched from the Frigate HTTP API.

Use :meth:`FrigateEvent.fetch` to retrieve a single event by ID, or access
events through :attr:`~review.FrigateReview.best_event` on a review.
"""

from __future__ import annotations

from typing import Any

import attrs
import httpx

from frigate_monitoring import urls
from frigate_monitoring.config import get_config


@attrs.define
class FrigateEvent:
    """Single detection event, populated from the Frigate HTTP events API."""

    event_id: str
    camera: str
    label: str
    sub_label: str
    score: float
    top_score: float
    zones: list[str]
    entered_zones: list[str]
    has_clip: bool
    has_snapshot: bool
    stationary: bool
    start_ts: float
    end_ts: float

    @property
    def score_pct(self) -> str:
        """Detection confidence as a percentage string, e.g. "87.3%"."""
        return f"{self.score * 100:.1f}%"

    @property
    def top_score_pct(self) -> str:
        """Best confidence seen so far as a percentage string."""
        return f"{self.top_score * 100:.1f}%"

    @property
    def snapshot_url(self) -> str:
        """URL to a JPEG snapshot of the detected object."""
        return urls.snapshot_url(self.event_id)

    @property
    def snapshot_url_cropped(self) -> str:
        """URL to a cropped JPEG snapshot of the detected object. This only works during ongoing event!
        Later, snapshots are stored as configured in the Frigate settings"""
        return urls.snapshot_url(self.event_id, bbox=True, cropped=True)

    @property
    def thumbnail_url(self) -> str:
        """URL to a small JPEG thumbnail."""
        return urls.thumbnail_url(self.event_id)

    @property
    def clip_url(self) -> str:
        """URL to the MP4 video clip."""
        return urls.clip_url(self.event_id)

    @property
    def gif_url(self) -> str:
        """URL to an animated GIF of the clip."""
        return urls.gif_url(self.event_id)

    @property
    def external_snapshot_url(self) -> str:
        """External snapshot URL. Requires FRIGATE_EXTERNAL_URL."""
        return urls.snapshot_url(self.event_id, external=True)

    @property
    def external_thumbnail_url(self) -> str:
        """External thumbnail URL. Requires FRIGATE_EXTERNAL_URL."""
        return urls.thumbnail_url(self.event_id, external=True)

    @property
    def external_clip_url(self) -> str:
        """External clip URL. Requires FRIGATE_EXTERNAL_URL."""
        return urls.clip_url(self.event_id, external=True)

    @property
    def external_gif_url(self) -> str:
        """External GIF URL. Requires FRIGATE_EXTERNAL_URL."""
        return urls.gif_url(self.event_id, external=True)

    @classmethod
    async def fetch(cls, event_id: str) -> "FrigateEvent":
        """Fetch event details from the Frigate HTTP API."""
        cfg = get_config()
        url = f"{cfg.frigate_base_url}/api/events/{event_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return cls._from_api(resp.json())

    @classmethod
    def _from_api(cls, data: dict[str, Any]) -> FrigateEvent:
        raw_sub: list[str] | str = data.get("sub_label", "")
        if isinstance(raw_sub, list):
            sub_label = raw_sub[0] if raw_sub else ""
        else:
            sub_label = raw_sub or ""

        inner: dict[str, Any] = data.get("data") or {}
        return cls(
            event_id=data.get("id", ""),
            camera=data.get("camera", ""),
            label=data.get("label", ""),
            sub_label=sub_label,
            score=float(inner.get("score") or 0),
            top_score=float(inner.get("top_score") or 0),
            zones=list(data.get("zones") or []),
            entered_zones=list(data.get("entered_zones") or []),
            has_clip=bool(data.get("has_clip", False)),
            has_snapshot=bool(data.get("has_snapshot", False)),
            stationary=bool(data.get("stationary", False)),
            start_ts=float(data.get("start_time") or 0),
            end_ts=float(data.get("end_time") or 0),
        )
