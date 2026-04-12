"""Send Pushover notifications for every alert review (both new and end events).

Set in your environment or .env:
    PUSHOVER_TOKEN=<your application API token>
    PUSHOVER_USER=<your user key>

See also: pushover.yaml for the YAML equivalent.
"""

import os

import trio

from frigate_monitoring.actions.pushover import PushoverAction, PushoverOptions
from frigate_monitoring.config import Config, init
from frigate_monitoring.filter import ReviewFilter
from frigate_monitoring.listener import FrigateListener


def main() -> None:
    """Run the listener and send Pushover alerts for alert reviews."""
    init(Config.from_env())
    listener = FrigateListener()
    listener.add_action(
        PushoverAction(
            token=os.environ["PUSHOVER_TOKEN"],
            user_key=os.environ["PUSHOVER_USER"],
            message="{{ label }} detected ({{ score_pct }}). See {{ external_clip_url }}",
            url="{{ external_gif_url }}",
            url_title="View GIF",
            options=PushoverOptions(ttl=60),
        ),
        filter=ReviewFilter(alerts_only=False, triggers=["start", "best"]),
    )
    trio.run(listener.run)


if __name__ == "__main__":
    main()
