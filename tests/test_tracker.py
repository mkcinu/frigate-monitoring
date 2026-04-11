"""Tests for ReviewTracker and event ranking."""

from __future__ import annotations

from tests.conftest import make_payload

from frigate_monitoring.event import FrigateEvent
from frigate_monitoring.review import FrigateReview
from frigate_monitoring.tracker import ReviewTracker, event_rank, pick_best


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


class TestEventRank:
    def test_higher_top_score_wins(self) -> None:
        low = _event(top_score=0.7)
        high = _event(top_score=0.95)
        assert event_rank(high) > event_rank(low)

    def test_snapshot_preferred(self) -> None:
        no_snap = _event(top_score=0.9, has_snapshot=False)
        has_snap = _event(top_score=0.9, has_snapshot=True)
        assert event_rank(has_snap) > event_rank(no_snap)

    def test_moving_preferred_over_stationary(self) -> None:
        still = _event(top_score=0.9, stationary=True)
        moving = _event(top_score=0.9, stationary=False)
        assert event_rank(moving) > event_rank(still)

    def test_score_breaks_tie(self) -> None:
        low_score = _event(top_score=0.9, score=0.7)
        high_score = _event(top_score=0.9, score=0.85)
        assert event_rank(high_score) > event_rank(low_score)


class TestPickBest:
    def test_empty_returns_none(self) -> None:
        assert pick_best([]) is None

    def test_single_event(self) -> None:
        ev = _event()
        assert pick_best([ev]) is ev

    def test_picks_highest_ranked(self) -> None:
        low = _event(event_id="low", top_score=0.5)
        high = _event(event_id="high", top_score=0.95)
        assert pick_best([low, high]) is high


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
        assert tracker.should_fire_start(review.review_id, action_idx=0) is True

    def test_should_fire_start_deduplicates(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        tracker.should_fire_start(review.review_id, action_idx=0)
        assert tracker.should_fire_start(review.review_id, action_idx=0) is False

    def test_different_actions_fire_independently(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        assert tracker.should_fire_start(review.review_id, action_idx=0) is True
        assert tracker.should_fire_start(review.review_id, action_idx=1) is True
        assert tracker.should_fire_start(review.review_id, action_idx=0) is False
        assert tracker.should_fire_start(review.review_id, action_idx=1) is False

    def test_should_fire_start_unknown_review(self) -> None:
        tracker = ReviewTracker()
        assert tracker.should_fire_start("nonexistent", action_idx=0) is False

    def test_end_clears_state(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracker.update(review)
        tracker.should_fire_start(review.review_id, action_idx=0)
        tracker.end(review.review_id)
        assert tracker.get(review.review_id) is None

    def test_eviction(self) -> None:
        tracker = ReviewTracker(max_tracked=3)
        for i in range(5):
            tracker.update(_review(review_id=f"r{i}"))
        assert tracker.get("r0") is None
        assert tracker.get("r1") is None
        assert tracker.get("r2") is not None
        assert tracker.get("r3") is not None
        assert tracker.get("r4") is not None

    def test_add_events_updates_best(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        low = _event(event_id="low", top_score=0.5)
        high = _event(event_id="high", top_score=0.95)
        tracked.add_events([low, high])
        assert tracked.best_event is high

    def test_add_events_accumulates(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        tracked.add_events([_event(event_id="ev1", top_score=0.5)])
        tracked.add_events([_event(event_id="ev2", top_score=0.95)])
        assert tracked.best_event is not None
        assert tracked.best_event.event_id == "ev2"
        assert len(tracked.events) == 2

    def test_add_events_replaces_same_id_with_updated_score(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        tracked.add_events([_event(event_id="ev1", top_score=0.5)])
        tracked.add_events([_event(event_id="ev1", top_score=0.95)])
        assert len(tracked.events) == 1
        assert tracked.best_event is not None
        assert tracked.best_event.top_score == 0.95

    def test_best_changed_since_start_when_same(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        tracked.add_events([_event(event_id="ev1", top_score=0.9)])
        tracked.mark_started(action_idx=0)
        assert not tracked.best_changed_since_start(action_idx=0)

    def test_best_changed_since_start_when_different(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        tracked.add_events([_event(event_id="ev1", top_score=0.5)])
        tracked.mark_started(action_idx=0)
        tracked.add_events([_event(event_id="ev2", top_score=0.95)])
        assert tracked.best_changed_since_start(action_idx=0)

    def test_best_changed_since_start_without_start(self) -> None:
        tracker = ReviewTracker()
        review = _review()
        tracked = tracker.update(review)
        tracked.add_events([_event(event_id="ev1", top_score=0.9)])
        assert tracked.best_changed_since_start(action_idx=0)
