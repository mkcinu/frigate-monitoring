"""CallbackAction: call an arbitrary function for each matching review."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import attrs

from frigate_monitoring.actions.base import Action
from frigate_monitoring.review import FrigateReview


@attrs.define
class CallbackAction(Action):
    """Call an async function for each matching review.

    Parameters
    ----------
    callback:
        An async callable that accepts a single :class:`~review.FrigateReview`
        argument.

    Example
    -------
    ::

        async def notify(review: FrigateReview) -> None:
            async with httpx.AsyncClient() as client:
                await client.post("https://ntfy.sh/my-topic", content=review.camera)

        listener.add_action(
            CallbackAction(notify),
            filter=ReviewFilter(alerts_only=True),
        )
    """

    callback: Callable[[FrigateReview], Awaitable[None]]

    async def handle(self, review: FrigateReview) -> None:
        """Invoke the callback with the review."""
        await self.callback(review)
