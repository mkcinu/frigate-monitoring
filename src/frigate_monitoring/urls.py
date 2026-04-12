"""Helpers that build Frigate HTTP API URLs from an event ID or camera name."""

from frigate_monitoring.config import get_config


def _base(external: bool) -> str:
    cfg = get_config()
    if external:
        if not cfg.frigate_external_url:
            raise RuntimeError(
                "frigate_external_url is not configured. "
                "Set FRIGATE_EXTERNAL_URL in your environment or config file."
            )
        return cfg.frigate_external_url.rstrip("/")
    return cfg.frigate_base_url


def snapshot_url(
    event_id: str, *, bbox: bool = False, external: bool = False, cropped: bool = False
) -> str:
    """JPEG still of the detected object.  Pass ``bbox=True`` to draw a bounding box."""
    qs = "?bbox=1" if bbox else ""
    if cropped:
        qs += ("&" if qs else "") + "crop=1"
    return f"{_base(external)}/api/events/{event_id}/snapshot.jpg{qs}"


def thumbnail_url(event_id: str, *, external: bool = False) -> str:
    """Small JPEG thumbnail (lower resolution than the snapshot)."""
    return f"{_base(external)}/api/events/{event_id}/thumbnail.jpg"


def clip_url(event_id: str, *, external: bool = False) -> str:
    """MP4 video clip of the event."""
    return f"{_base(external)}/api/events/{event_id}/clip.mp4"


def gif_url(event_id: str, *, external: bool = False) -> str:
    """Animated GIF preview of the event clip."""
    return f"{_base(external)}/api/events/{event_id}/preview.gif"


def review_gif_url(review_id: str, *, external: bool = False) -> str:
    """Animated GIF preview covering the full review duration."""
    return f"{_base(external)}/api/review/{review_id}/preview?format=gif"


def latest_snapshot_url(camera: str, *, external: bool = False) -> str:
    """Latest frame from a camera (not tied to a specific event)."""
    return f"{_base(external)}/api/{camera}/latest.jpg"
