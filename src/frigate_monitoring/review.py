"""FrigateReview dataclass and MQTT payload parser.

Frigate publishes to ``frigate/reviews`` with the JSON shape::

    {
        "type": "new" | "update" | "end",
        "before": { <review snapshot before change> },
        "after":  { <review snapshot after change>  }
    }

``after`` is always the authoritative state.  ``before`` is used as a fallback
when a field is absent from ``after``.

A review groups one or more detection events that occurred together on a single
camera.  The individual events are referenced by ID in ``data.detections`` and
can be fetched from the Frigate HTTP API via :attr:`FrigateReview.events`.

Template variable reference
---------------------------
The following placeholders are available in every message template:

    {{ review_id }}             Frigate's unique review ID.
    {{ review_type }}           One of: new | update | end
    {{ camera }}                Camera name (e.g. "front_door").
    {{ severity }}              "alert" or "detection".
    {{ is_alert }}              True if severity == "alert".
    {{ objects }}               List of detected object types. Use ``| join(', ')`` to render as a string.
    {{ zones }}                 List of active zones.
    {{ sub_labels }}            List of sub-labels (face names, plates, …).
    {{ start_time }}            Review start as a formatted datetime string.
    {{ start_ts }}              Review start as a Unix timestamp (float).
    {{ end_time }}              Formatted review end; empty string while ongoing.
    {{ end_ts }}                Review end as a Unix timestamp (float, 0.0 if ongoing).
    {{ duration }}              Elapsed seconds since review start (float).
    {{ gif_url }}               Review-level animated GIF covering the full alert window.
    {{ external_gif_url }}      External review GIF URL (requires FRIGATE_EXTERNAL_URL).
    {{ trigger }}               Trigger that caused this dispatch ("start" or "best").
    {{ events }}                List of per-event dicts.  Each entry has:
                                  event_id, label, sub_label,
                                  score, score_pct, top_score, top_score_pct,
                                  has_snapshot, stationary,
                                  snapshot_url, snapshot_url_cropped,
                                  thumbnail_url,
                                  external_snapshot_url, external_thumbnail_url
                                  (external_* only when FRIGATE_EXTERNAL_URL is set).
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import attrs

from frigate_monitoring import urls
from frigate_monitoring.config import get_config
from frigate_monitoring.event import FrigateEvent
from frigate_monitoring.types import ReviewType, Severity


@attrs.define(slots=False)
class FrigateReview:
    """Parsed representation of a single Frigate MQTT review message."""

    review_id: str
    review_type: ReviewType
    camera: str
    severity: Severity
    start_ts: float
    end_ts: float
    event_ids: list[str]
    objects: list[str]
    zones: list[str]
    sub_labels: list[str]
    raw: dict[str, Any] = attrs.field(repr=False, factory=dict[str, Any])
    trigger: str = attrs.field(default="", repr=False)
    _resolved_events: list[FrigateEvent] = attrs.field(
        factory=list[FrigateEvent], init=False, repr=False, alias="_resolved_events"
    )

    @property
    def events(self) -> list[FrigateEvent]:
        """Return the resolved events list. Set by the tracker after fetching."""
        return self._resolved_events

    @events.setter
    def events(self, events: list[FrigateEvent]) -> None:
        self._resolved_events = events

    @property
    def is_alert(self) -> bool:
        """Return True when severity is "alert"."""
        return self.severity == "alert"

    @property
    def start_time(self) -> str:
        """Review start formatted per DATETIME_FORMAT."""
        return datetime.fromtimestamp(self.start_ts).strftime(
            get_config().datetime_format
        )

    @property
    def end_time(self) -> str:
        """Review end per DATETIME_FORMAT; empty string while ongoing."""
        if self.end_ts:
            return datetime.fromtimestamp(self.end_ts).strftime(
                get_config().datetime_format
            )
        return ""

    @property
    def duration(self) -> float:
        """Elapsed seconds since review start."""
        end = self.end_ts or time.time()
        return end - self.start_ts

    @property
    def gif_url(self) -> str:
        """Review-level animated GIF covering the full alert window."""
        return urls.review_gif_url(self.review_id)

    @property
    def external_gif_url(self) -> str:
        """External review GIF URL. Requires FRIGATE_EXTERNAL_URL."""
        return urls.review_gif_url(self.review_id, external=True)

    def as_template_vars(self) -> dict[str, Any]:
        """Return a flat dict of all variables available in message templates."""
        cfg = get_config()
        d: dict[str, Any] = {
            "review_id": self.review_id,
            "review_type": self.review_type,
            "trigger": self.trigger,
            "camera": self.camera,
            "severity": self.severity,
            "is_alert": self.is_alert,
            "objects": self.objects,
            "zones": self.zones,
            "sub_labels": self.sub_labels,
            "start_time": self.start_time,
            "start_ts": self.start_ts,
            "end_time": self.end_time,
            "end_ts": self.end_ts,
            "duration": self.duration,
            "gif_url": urls.review_gif_url(self.review_id),
            "events": [e.as_template_vars() for e in self._resolved_events],
        }
        if cfg.frigate_external_url:
            d["external_gif_url"] = urls.review_gif_url(self.review_id, external=True)
        return d

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FrigateReview:
        """Parse a raw Frigate MQTT review payload into a :class:`FrigateReview`."""
        review_type: ReviewType = payload.get("type", "new")
        before: dict[str, Any] = payload.get("before") or {}
        after: dict[str, Any] = payload.get("after") or {}

        def _get(key: str, default: Any = None) -> Any:
            return after.get(key, before.get(key, default))

        data: dict[str, Any] = _get("data") or {}

        return cls(
            review_id=_get("id", ""),
            review_type=review_type,
            camera=_get("camera", ""),
            severity=_get("severity", "detection"),
            start_ts=float(_get("start_time") or 0),
            end_ts=float(_get("end_time") or 0),
            event_ids=list(data.get("detections") or []),
            objects=list(data.get("objects") or []),
            zones=list(data.get("zones") or []),
            sub_labels=list(data.get("sub_labels") or []),
            raw=payload,
        )
