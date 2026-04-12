"""PrintAction: print a formatted line to stdout for each matching review."""

from __future__ import annotations

from typing import ClassVar

import attrs
from jinja2 import TemplateError

from frigate_monitoring.actions.base import DEFAULT_TEMPLATE, Action, render_template
from frigate_monitoring.review import FrigateReview


@attrs.define
class PrintAction(Action):
    """Print a formatted line to stdout for each matching review.

    Parameters
    ----------
    template:
        A Jinja2 template string using the variables listed in
        :mod:`review` module docstring.
        Example: ``"[{{ camera }}] {{ severity }}: {{ objects | join(', ') }} — {{ score_pct }}"``
    """

    DEFAULT_TEMPLATE: ClassVar[str] = DEFAULT_TEMPLATE

    template: str = DEFAULT_TEMPLATE

    async def handle(self, review: FrigateReview) -> None:
        """Print the rendered template to stdout."""
        try:
            msg = render_template(self.template, review.as_template_vars())
        except TemplateError as exc:
            msg = f"[template error: {exc}] raw: {review}"
        print(msg)
