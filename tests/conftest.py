"""Shared test fixtures: sample MQTT payloads and pre-built reviews."""

from __future__ import annotations

from typing import Any

import pytest

from frigate_monitoring.event import FrigateEvent
from frigate_monitoring.review import FrigateReview


@pytest.fixture
def fake_event() -> FrigateEvent:
    return FrigateEvent(
        event_id="ev1",
        camera="front_door",
        label="person",
        sub_label="",
        score=0.85,
        top_score=0.92,
        zones=["yard"],
        entered_zones=["yard"],
        has_clip=True,
        has_snapshot=True,
        stationary=False,
        start_ts=1700000000.0,
        end_ts=1700000010.0,
    )


def make_payload(
    *,
    review_type: str = "new",
    review_id: str = "test-review-001",
    camera: str = "front_door",
    severity: str = "alert",
    start_time: float = 1700000000.0,
    end_time: float = 0.0,
    detections: list[str] | None = None,
    objects: list[str] | None = None,
    zones: list[str] | None = None,
    sub_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Build a realistic Frigate MQTT review payload."""
    data = {
        "detections": detections or ["event-abc-123"],
        "objects": objects or ["person"],
        "zones": zones or ["yard"],
        "sub_labels": sub_labels or [],
    }
    after = {
        "id": review_id,
        "camera": camera,
        "severity": severity,
        "start_time": start_time,
        "end_time": end_time,
        "data": data,
    }
    return {"type": review_type, "before": {}, "after": after}


@pytest.fixture
def sample_payload() -> dict[str, Any]:
    return make_payload()


@pytest.fixture
def sample_review(sample_payload: dict[str, Any]) -> FrigateReview:
    return FrigateReview.from_payload(sample_payload)


@pytest.fixture
def end_payload() -> dict[str, Any]:
    return make_payload(
        review_type="end",
        end_time=1700000030.0,
        objects=["person", "car"],
        zones=["yard", "driveway"],
    )


@pytest.fixture
def detection_payload() -> dict[str, Any]:
    return make_payload(severity="detection", camera="garage")
