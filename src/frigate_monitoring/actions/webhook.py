"""WebhookAction: send HTTP requests for each matching review."""

from __future__ import annotations

import json
import logging

import attrs
import httpx

from frigate_monitoring.actions.base import Action, render_template
from frigate_monitoring.review import FrigateReview

log = logging.getLogger(__name__)


@attrs.define
class WebhookAction(Action):
    """Send an HTTP request to an arbitrary URL for each matching review.

    All string fields support the same template variables as
    :class:`~actions.print_action.PrintAction`.

    Parameters
    ----------
    url:
        Target URL template.
    method:
        HTTP method (GET, POST, PUT, PATCH, DELETE).
    body:
        Optional JSON body template.  Each value is expanded with template
        variables.  When ``None``, the full template vars dict is sent as JSON.
    headers:
        Extra HTTP headers to include.
    timeout:
        Request timeout in seconds.
    """

    url: str
    method: str = "POST"
    body: dict[str, str] | None = None
    headers: dict[str, str] = attrs.field(factory=dict[str, str])
    timeout: float = 10.0

    async def handle(self, review: FrigateReview) -> None:
        """Send the HTTP request."""
        template_vars = review.as_template_vars()
        target_url = render_template(self.url, template_vars)

        if self.body is not None:
            body = {k: render_template(v, template_vars) for k, v in self.body.items()}
        else:
            body = {k: str(v) for k, v in template_vars.items()}

        rendered_headers = {
            k: render_template(v, template_vars) for k, v in self.headers.items()
        }
        rendered_headers.setdefault("Content-Type", "application/json")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(
                method=self.method.upper(),
                url=target_url,
                content=json.dumps(body).encode(),
                headers=rendered_headers,
            )
        resp.raise_for_status()
        log.debug("Webhook %s %s → %s", self.method, target_url, resp.status_code)
