"""Send a push notification via ntfy.sh for every alert.

Set your topic: export NTFY_TOPIC=my-frigate-alerts
"""

# pylint: disable=duplicate-code

import os

import httpx
import trio

from frigate_monitoring.actions.callback import CallbackAction
from frigate_monitoring.config import Config, init
from frigate_monitoring.filter import ReviewFilter
from frigate_monitoring.listener import FrigateListener
from frigate_monitoring.review import FrigateReview

NTFY_URL = f"https://ntfy.sh/{os.environ.get('NTFY_TOPIC', 'my-frigate-alerts')}"


async def notify(review: FrigateReview) -> None:
    """Send an ntfy notification with the snapshot attached."""
    be = review.best_event
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(
            NTFY_URL,
            content=f"{review.camera}: {be.label} ({be.score_pct})".encode(),
            headers={"Title": "Frigate alert", "Attach": review.external_snapshot_url},
        )


def main() -> None:
    """Run the listener and notify on completed alert reviews."""
    init(Config.from_env())
    listener = FrigateListener()
    listener.add_action(
        CallbackAction(notify),
        filter=ReviewFilter(alerts_only=True, triggers=["best"]),
    )
    trio.run(listener.run)


if __name__ == "__main__":
    main()
