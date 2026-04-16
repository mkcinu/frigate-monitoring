"""Tests for ReviewTracker."""

from __future__ import annotations

from tests.conftest import make_payload

from frigate_monitoring.event import FrigateEvent
from frigate_monitoring.review import FrigateReview
from frigate_monitoring.tracker import ReviewTracker


def _event(
    event_id: str = "ev1",
    top_score: float = 0.9,
    score: float = 0.85,
    has_snapshot: bool = True,
    stationary: bool = False,
    label: str = "person",
) -> FrigateEvent:
    return FrigateEvent(
        event_id=event_id,
        camera="front_door",
        label=label,
        sub_label="",
        score=score,
        top_score=top_score,
        zones=["yard"],
        entered_zones=["yard"],
        has_clip=True,
        has_snapshot=has_snapshot,
        stationary=stationary,
        start_ts=1700000000.0,
        end_ts=1700000010.0,
    )


def _review(**kwargs: object) -> FrigateReview:
    return FrigateReview.from_payload(make_payload(**kwargs))  # type: ignore[arg-type]


class TestReviewTracker:
    def test_update_creates_tracked_review(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        assert tracked.review is review
        assert tracker.get(review.review_id) is tracked

    def test_update_replaces_review(self) -> None:
        tracker = ReviewTracker()
        r1 = _review(severity="detection")
        r2 = _review(severity="alert")
        tracker.update(r1)
        tracked = tracker.update(r2)
        assert tracked.review is r2

    def test_should_fire_start_first_time(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        assert (
            tracker.should_fire_start(review.review_id, action_idx=0, events=[_event()])
            is True
        )

    def test_should_fire_start_deduplicates(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        tracker.should_fire_start(review.review_id, action_idx=0, events=[_event()])
        assert (
            tracker.should_fire_start(review.review_id, action_idx=0, events=[_event()])
            is False
        )

    def test_different_actions_fire_independently(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        evs = [_event()]
        assert (
            tracker.should_fire_start(review.review_id, action_idx=0, events=evs)
            is True
        )
        assert (
            tracker.should_fire_start(review.review_id, action_idx=1, events=evs)
            is True
        )
        assert (
            tracker.should_fire_start(review.review_id, action_idx=0, events=evs)
            is False
        )
        assert (
            tracker.should_fire_start(review.review_id, action_idx=1, events=evs)
            is False
        )

    def test_should_fire_start_unknown_review(self) -> None:
        tracker = ReviewTracker()
        assert (
            tracker.should_fire_start("nonexistent", action_idx=0, events=[]) is False
        )

    def test_end_clears_state(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        tracker.should_fire_start(review.review_id, action_idx=0, events=[_event()])
        tracker.end(review.review_id)
        assert tracker.get(review.review_id) is None

    def test_should_fire_best_identical_events(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        evs = [_event()]
        tracker.should_fire_start(review.review_id, action_idx=0, events=evs)
        assert (
            tracker.should_fire_best(review.review_id, action_idx=0, events=evs)
            is False
        )

    def test_should_fire_best_new_event(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        tracker.should_fire_start(
            review.review_id, action_idx=0, events=[_event("ev1")]
        )
        assert (
            tracker.should_fire_best(
                review.review_id, action_idx=0, events=[_event("ev1"), _event("ev2")]
            )
            is True
        )

    def test_should_fire_best_improved_score(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        tracker.should_fire_start(
            review.review_id, action_idx=0, events=[_event(top_score=0.6)]
        )
        assert (
            tracker.should_fire_best(
                review.review_id, action_idx=0, events=[_event(top_score=0.9)]
            )
            is True
        )

    def test_should_fire_best_no_start_recorded(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        assert (
            tracker.should_fire_best(review.review_id, action_idx=0, events=[_event()])
            is True
        )

    def test_should_fire_best_actions_independent(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        evs = [_event()]
        tracker.should_fire_start(review.review_id, action_idx=0, events=evs)
        # action 1 never had start fired, so best should be allowed
        assert (
            tracker.should_fire_best(review.review_id, action_idx=1, events=evs) is True
        )
        # action 0 had start with same events, so best should be suppressed
        assert (
            tracker.should_fire_best(review.review_id, action_idx=0, events=evs)
            is False
        )

    def test_eviction(self) -> None:
        tracker = ReviewTracker(max_tracked=3)
        for i in range(5):
            tracker.update(_review(review_id=f"r{i}"))
        assert tracker.get("r0") is None
        assert tracker.get("r1") is None
        assert tracker.get("r2") is not None
        assert tracker.get("r3") is not None
        assert tracker.get("r4") is not None

    def test_add_events_accumulates(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        tracked.add_events([_event(event_id="ev1", top_score=0.5)])
        tracked.add_events([_event(event_id="ev2", top_score=0.95)])
        assert len(tracked.events) == 2

    def test_add_events_replaces_with_higher_score(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        tracked.add_events([_event(event_id="ev1", top_score=0.5)])
        tracked.add_events([_event(event_id="ev1", top_score=0.95)])
        assert len(tracked.events) == 1
        assert tracked.events["ev1"].top_score == 0.95

    def test_add_events_keeps_better_existing(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        tracked.add_events([_event(event_id="ev1", top_score=0.95)])
        tracked.add_events([_event(event_id="ev1", top_score=0.5)])
        assert tracked.events["ev1"].top_score == 0.95
