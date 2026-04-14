"""FrigateEvent: per-detection detail fetched from the Frigate HTTP API.

Use :meth:`FrigateEvent.fetch` to retrieve a single event by ID, or access
events through :attr:`~review.FrigateReview.events` on a review.
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
    snapshot_bytes: bytes | None = attrs.field(default=None, repr=False)

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
    def external_snapshot_url(self) -> str:
        """External snapshot URL. Requires FRIGATE_EXTERNAL_URL."""
        return urls.snapshot_url(self.event_id, external=True)

    @property
    def external_thumbnail_url(self) -> str:
        """External thumbnail URL. Requires FRIGATE_EXTERNAL_URL."""
        return urls.thumbnail_url(self.event_id, external=True)

    def as_template_vars(self) -> dict[str, Any]:
        """Return a flat dict of event variables for use in templates."""
        cfg = get_config()
        d: dict[str, Any] = {
            "event_id": self.event_id,
            "label": self.label,
            "sub_label": self.sub_label,
            "score": self.score,
            "score_pct": self.score_pct,
            "top_score": self.top_score,
            "top_score_pct": self.top_score_pct,
            "has_snapshot": self.has_snapshot,
            "stationary": self.stationary,
            "snapshot_url": self.snapshot_url,
            "snapshot_url_cropped": self.snapshot_url_cropped,
            "thumbnail_url": self.thumbnail_url,
        }
        if cfg.frigate_external_url:
            d["external_snapshot_url"] = self.external_snapshot_url
            d["external_thumbnail_url"] = self.external_thumbnail_url
        return d

    @classmethod
    async def fetch(cls, event_id: str) -> "FrigateEvent":
        """Fetch event details and snapshot content from the Frigate HTTP API.

        The cropped+bbox snapshot is fetched in the same session and stored in
        :attr:`snapshot_bytes`.  If no snapshot is available yet (404) or the
        fetch fails, :attr:`snapshot_bytes` is left as ``None``.
        """
        cfg = get_config()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{cfg.frigate_base_url}/api/events/{event_id}")
            resp.raise_for_status()
            event = cls._from_api(resp.json())

            if event.has_snapshot:
                snap_resp = await client.get(
                    urls.snapshot_url(event_id, bbox=True, cropped=True),
                    timeout=15.0,
                )
                if snap_resp.status_code == 200:
                    event.snapshot_bytes = snap_resp.content

        return event

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
