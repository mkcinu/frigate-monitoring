"""PushoverAction: send Pushover push notifications for Frigate reviews."""

from __future__ import annotations

from typing import Any

import attrs
import httpx

from frigate_monitoring.actions.base import Action, render_template
from frigate_monitoring.review import FrigateReview

_API_URL = "https://api.pushover.net/1/messages.json"


@attrs.define
class PushoverOptions:
    """Delivery options passed directly to the Pushover API.

    See https://pushover.net/api for the full parameter reference.

    Parameters
    ----------
    sound:
        Notification sound name, e.g. ``"pushover"``, ``"magic"``, ``"none"``.
        Empty string uses the user/device default.
    priority:
        Delivery priority:

        * ``-2`` — no notification or alert, message stored silently.
        * ``-1`` — quiet; delivered without sound/vibration.
        * ``0``  — normal priority (default).
        * ``1``  — high priority; bypasses quiet hours.
        * ``2``  — emergency; repeats every ``retry`` seconds until acknowledged
          or ``expire`` seconds have passed.  Requires ``retry`` and ``expire``.
    retry:
        Seconds between re-delivery attempts for emergency (priority 2)
        notifications.  Minimum 30.  Ignored for other priorities.
    expire:
        Seconds after which emergency re-delivery stops even if unacknowledged.
        Maximum 10800 (3 hours).  Ignored for other priorities.
    ttl:
        Seconds the notification lives on Pushover's servers before being
        discarded if not yet delivered.  ``0`` means no expiry.
    device:
        Target a specific registered device name.  Empty string delivers to
        all of the user's devices.
    html:
        When ``True``, the message body is rendered as HTML.
    """

    sound: str = ""
    priority: int = 0
    retry: int = 30
    expire: int = 3600
    ttl: int = 0
    device: str = ""
    html: bool = False

    def as_api_params(self) -> dict[str, Any]:
        """Return a dict of non-default fields ready to merge into the API payload."""
        params: dict[str, Any] = {"priority": self.priority}
        if self.sound:
            params["sound"] = self.sound
        if self.priority == 2:
            params["retry"] = self.retry
            params["expire"] = self.expire
        if self.ttl:
            params["ttl"] = self.ttl
        if self.device:
            params["device"] = self.device
        if self.html:
            params["html"] = 1
        return params


@attrs.define
class PushoverAction(Action):
    """Send a Pushover push notification for each matching review.

    All string fields are Jinja2 templates.  The ``events`` list is available
    in templates — each entry is a dict with ``label``, ``score_pct``, etc.
    Leave ``url`` or ``url_title`` empty to omit them from the notification.

    Parameters
    ----------
    token:
        Pushover application API token.
    user_key:
        Pushover user key.
    title:
        Notification title template.
    message:
        Notification body template.
    url:
        Optional URL template attached to the notification.
    url_title:
        Label for the URL.
    attach_snapshot:
        When ``True``, attach the snapshot of the first event that has one.
    options:
        Fine-grained delivery options (sound, priority, TTL, …).
    """

    token: str
    user_key: str
    title: str = "Frigate alert on {{ camera }}"
    message: str = "{{ events | map(attribute='label') | join(', ') }} detected"
    url: str = ""
    url_title: str = ""
    attach_snapshot: bool = True
    options: PushoverOptions = attrs.field(factory=PushoverOptions)

    async def handle(self, review: FrigateReview) -> None:
        """Send the Pushover notification."""
        tpl_vars = review.as_template_vars()
        data: dict[str, Any] = {
            "title": render_template(self.title, tpl_vars),
            "message": render_template(self.message, tpl_vars),
            **self.options.as_api_params(),
        }
        if self.url:
            data["url"] = render_template(self.url, tpl_vars)
        if self.url_title:
            data["url_title"] = render_template(self.url_title, tpl_vars)

        files: dict[str, Any] = {}
        if self.attach_snapshot:
            snap = next(
                (ev.snapshot_bytes for ev in review.events if ev.snapshot_bytes),
                None,
            )
            if snap is not None:
                files["attachment"] = ("snapshot.jpg", snap, "image/jpeg")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _API_URL,
                data={"token": self.token, "user": self.user_key, **data},
                files=files,
                timeout=20.0,
            )
        resp.raise_for_status()
