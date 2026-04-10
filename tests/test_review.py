"""Tests for FrigateReview.from_payload and computed properties."""

from __future__ import annotations

from typing import Any

from frigate_monitoring.review import FrigateReview


def test_fallback_to_before() -> None:
    payload: dict[str, Any] = {
        "type": "update",
        "before": {
            "id": "from-before",
            "camera": "back_door",
            "severity": "detection",
            "start_time": 100.0,
            "end_time": 0.0,
            "data": {"detections": ["ev1"], "objects": ["dog"]},
        },
        "after": {},
    }
    review = FrigateReview.from_payload(payload)
    assert review.review_id == "from-before"
    assert review.camera == "back_door"
    assert review.objects == ["dog"]


def test_empty_payload_defaults() -> None:
    payload: dict[str, Any] = {"type": "new", "before": {}, "after": {}}
    review = FrigateReview.from_payload(payload)
    assert review.review_id == ""
    assert review.camera == ""
    assert review.severity == "detection"
    assert review.objects == []
    assert review.event_ids == []


def test_duration_of_ended_review(end_payload: dict[str, Any]) -> None:
    review = FrigateReview.from_payload(end_payload)
    assert review.duration == 30.0


def test_end_time_empty_while_ongoing(sample_review: FrigateReview) -> None:
    assert sample_review.end_time == ""


def test_end_time_present_when_ended(end_payload: dict[str, Any]) -> None:
    review = FrigateReview.from_payload(end_payload)
    assert review.end_time != ""


def test_after_takes_precedence_over_before() -> None:
    payload: dict[str, Any] = {
        "type": "update",
        "before": {
            "id": "old-id",
            "camera": "old_cam",
            "severity": "detection",
            "data": {"objects": ["cat"]},
        },
        "after": {
            "id": "new-id",
            "camera": "new_cam",
            "severity": "alert",
            "data": {"objects": ["person"]},
        },
    }
    review = FrigateReview.from_payload(payload)
    assert review.review_id == "new-id"
    assert review.camera == "new_cam"
    assert review.severity == "alert"
    assert review.objects == ["person"]
