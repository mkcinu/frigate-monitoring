"""Tests for ReviewFilter.matches."""

from __future__ import annotations

from datetime import datetime, time

from tests.conftest import make_payload

from frigate_monitoring.filter import ReviewFilter
from frigate_monitoring.review import FrigateReview


def _review(**kwargs: object) -> FrigateReview:
    return FrigateReview.from_payload(make_payload(**kwargs))  # type: ignore[arg-type]


def _review_at(t: time, **kwargs: object) -> FrigateReview:
    """Build a review whose start_ts falls at the given local time today."""
    ts = datetime.combine(datetime.today().date(), t).timestamp()
    return _review(start_time=ts, **kwargs)


def test_empty_filter_matches_everything() -> None:
    f = ReviewFilter()
    assert f.matches(_review())
    assert f.matches(_review(severity="detection", camera="garage"))


def test_camera_filter() -> None:
    f = ReviewFilter(cameras=["front_door"])
    assert f.matches(_review(camera="front_door"))
    assert not f.matches(_review(camera="garage"))


def test_camera_filter_multiple() -> None:
    f = ReviewFilter(cameras=["front_door", "back_door"])
    assert f.matches(_review(camera="front_door"))
    assert f.matches(_review(camera="back_door"))
    assert not f.matches(_review(camera="garage"))


def test_objects_filter() -> None:
    f = ReviewFilter(objects=["person"])
    assert f.matches(_review(objects=["person"]))
    assert f.matches(_review(objects=["person", "car"]))
    assert not f.matches(_review(objects=["car"]))


def test_objects_filter_any_match() -> None:
    f = ReviewFilter(objects=["person", "dog"])
    assert f.matches(_review(objects=["dog", "cat"]))


def test_review_types_filter() -> None:
    f = ReviewFilter(review_types=["end"])
    assert f.matches(_review(review_type="end"))
    assert not f.matches(_review(review_type="new"))


def test_alerts_only() -> None:
    f = ReviewFilter(alerts_only=True)
    assert f.matches(_review(severity="alert"))
    assert not f.matches(_review(severity="detection"))


def test_zones_filter() -> None:
    f = ReviewFilter(zones=["yard"])
    assert f.matches(_review(zones=["yard", "driveway"]))
    assert not f.matches(_review(zones=["garage"]))


def test_time_range_daytime_inside() -> None:
    f = ReviewFilter(time_range=(time(8, 0), time(20, 0)))
    assert f.matches(_review_at(time(8, 0)))  # start boundary (inclusive)
    assert f.matches(_review_at(time(12, 0)))
    assert f.matches(_review_at(time(19, 59)))


def test_time_range_daytime_outside() -> None:
    f = ReviewFilter(time_range=(time(8, 0), time(20, 0)))
    assert not f.matches(_review_at(time(7, 59)))
    assert not f.matches(_review_at(time(20, 0)))  # end boundary (exclusive)
    assert not f.matches(_review_at(time(23, 0)))


def test_time_range_overnight_inside() -> None:
    f = ReviewFilter(time_range=(time(22, 0), time(6, 0)))
    assert f.matches(_review_at(time(22, 0)))  # start boundary (inclusive)
    assert f.matches(_review_at(time(23, 30)))
    assert f.matches(_review_at(time(0, 0)))
    assert f.matches(_review_at(time(5, 59)))


def test_time_range_overnight_outside() -> None:
    f = ReviewFilter(time_range=(time(22, 0), time(6, 0)))
    assert not f.matches(_review_at(time(6, 0)))  # end boundary (exclusive)
    assert not f.matches(_review_at(time(12, 0)))
    assert not f.matches(_review_at(time(21, 59)))


def test_time_range_none_matches_any_time() -> None:
    f = ReviewFilter()
    assert f.matches(_review_at(time(3, 0)))
    assert f.matches(_review_at(time(15, 0)))


def test_combined_filters_all_must_match() -> None:
    f = ReviewFilter(
        cameras=["front_door"],
        objects=["person"],
        alerts_only=True,
        review_types=["end"],
        zones=["yard"],
    )
    assert f.matches(
        _review(
            camera="front_door",
            objects=["person"],
            severity="alert",
            review_type="end",
            zones=["yard"],
        )
    )
    # Fails on camera
    assert not f.matches(
        _review(
            camera="garage",
            objects=["person"],
            severity="alert",
            review_type="end",
            zones=["yard"],
        )
    )
    # Fails on severity
    assert not f.matches(
        _review(
            camera="front_door",
            objects=["person"],
            severity="detection",
            review_type="end",
            zones=["yard"],
        )
    )
