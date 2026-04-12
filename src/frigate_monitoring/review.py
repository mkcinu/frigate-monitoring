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
can be fetched from the Frigate HTTP API via :attr:`FrigateReview.best_event`.

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

The following come from the best event (highest score) and require an HTTP
call to the Frigate API on first access:

    {{ event_id }}              Best event ID.
    {{ label }}                 Detected object class (e.g. "person").
    {{ sub_label }}             Sub-label for the best event.
    {{ score }}                 Detection confidence, 0.0–1.0.
    {{ score_pct }}             Confidence as a percentage string, e.g. "87.3%".
    {{ top_score }}             Highest confidence seen during this event.
    {{ top_score_pct }}         Same as a percentage string.
    {{ has_clip }}              True if a video clip is available.
    {{ has_snapshot }}          True if a snapshot image is available.
    {{ snapshot_url }}          URL to a JPEG snapshot of the best event.
    {{ thumbnail_url }}         URL to a small JPEG thumbnail.
    {{ clip_url }}              URL to the MP4 video clip.
    {{ gif_url }}               Review-level animated GIF covering the full alert window.
    {{ trigger }}               Trigger that caused this dispatch ("start" or "best").
    {{ external_snapshot_url }} External snapshot URL (requires FRIGATE_EXTERNAL_URL).
    {{ external_thumbnail_url }} External thumbnail URL (requires FRIGATE_EXTERNAL_URL).
    {{ external_clip_url }}     External clip URL (requires FRIGATE_EXTERNAL_URL).
    {{ external_gif_url }}      External review GIF URL (requires FRIGATE_EXTERNAL_URL).
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import attrs
import trio

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
    _best_event: FrigateEvent | None = attrs.field(
        default=None, init=False, repr=False, alias="_best_event"
    )

    async def resolve(self) -> None:
        """Fetch all events concurrently and cache the best one.

        Must be called before accessing :attr:`best_event` or any property that
        depends on it.  Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._best_event is not None:
            return
        if not self.event_ids:
            raise RuntimeError(f"Review {self.review_id} has no associated events.")
        events: list[FrigateEvent] = []

        async def _fetch(eid: str) -> None:
            events.append(await FrigateEvent.fetch(eid))

        async with trio.open_nursery() as nursery:
            for eid in self.event_ids:
                nursery.start_soon(_fetch, eid)

        self._best_event = max(events, key=lambda e: e.top_score)

    @property
    def best_event(self) -> FrigateEvent:
        """Return the cached best event.  Requires :meth:`resolve` to have been awaited."""
        if self._best_event is None:
            raise RuntimeError(
                f"Review {self.review_id}: call 'await review.resolve()' before "
                "accessing best_event or any property that depends on it."
            )
        return self._best_event

    @best_event.setter
    def best_event(self, event: FrigateEvent) -> None:
        """Set the best event directly (used by the tracker)."""
        self._best_event = event

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
    def snapshot_url(self) -> str:
        """JPEG snapshot URL of the best event."""
        return self.best_event.snapshot_url

    @property
    def snapshot_url_cropped(self) -> str:
        """Cropped JPEG snapshot URL of the best event. This only works during ongoing event!
        Later, snapshots are stored as configured in the Frigate settings"""
        return self.best_event.snapshot_url_cropped

    @property
    def thumbnail_url(self) -> str:
        """Thumbnail URL of the best event."""
        return self.best_event.thumbnail_url

    @property
    def clip_url(self) -> str:
        """MP4 clip URL of the best event."""
        return self.best_event.clip_url

    @property
    def gif_url(self) -> str:
        """Review-level animated GIF covering the full alert window."""
        return urls.review_gif_url(self.review_id)

    @property
    def external_snapshot_url(self) -> str:
        """External snapshot URL of the best event. Requires FRIGATE_EXTERNAL_URL."""
        return self.best_event.external_snapshot_url

    @property
    def external_thumbnail_url(self) -> str:
        """External thumbnail URL of the best event. Requires FRIGATE_EXTERNAL_URL."""
        return self.best_event.external_thumbnail_url

    @property
    def external_clip_url(self) -> str:
        """External clip URL of the best event. Requires FRIGATE_EXTERNAL_URL."""
        return self.best_event.external_clip_url

    @property
    def external_gif_url(self) -> str:
        """External review GIF URL. Requires FRIGATE_EXTERNAL_URL."""
        return urls.review_gif_url(self.review_id, external=True)

    def as_template_vars(self) -> dict[str, Any]:
        """Return a flat dict of all variables available in message templates.

        Accessing this triggers an HTTP fetch for the best event if not already cached.
        """
        be = self.best_event
        return {
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
            "event_id": be.event_id,
            "label": be.label,
            "sub_label": be.sub_label,
            "score": be.score,
            "score_pct": be.score_pct,
            "top_score": be.top_score,
            "top_score_pct": be.top_score_pct,
            "has_clip": be.has_clip,
            "has_snapshot": be.has_snapshot,
            "snapshot_url": be.snapshot_url,
            "snapshot_url_cropped": be.snapshot_url_cropped,
            "thumbnail_url": be.thumbnail_url,
            "clip_url": be.clip_url,
            "gif_url": urls.review_gif_url(self.review_id),
            **(
                {
                    "external_snapshot_url": be.external_snapshot_url,
                    "external_thumbnail_url": be.external_thumbnail_url,
                    "external_clip_url": be.external_clip_url,
                    "external_gif_url": urls.review_gif_url(
                        self.review_id, external=True
                    ),
                }
                if get_config().frigate_external_url
                else {}
            ),
        }

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
