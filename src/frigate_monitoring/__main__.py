"""Entry point for ``python -m frigate_monitoring``."""

import argparse
import logging
from pathlib import Path

import trio

from frigate_monitoring.config import Config, init
from frigate_monitoring.listener import FrigateListener


def _default_listener() -> FrigateListener:
    from frigate_monitoring.actions.print_action import PrintAction
    from frigate_monitoring.filter import ReviewFilter

    listener = FrigateListener()
    listener.add_action(
        PrintAction(
            template=(
                "[{camera}] *** {review_type}: {severity}"
                " — {objects} ({score_pct}) ***\n"
                "  Snapshot : {snapshot_url}\n"
                "  GIF      : {gif_url}\n"
                "  Clip     : {clip_url}\n"
                "  Event ID : {event_id}\n"
            ),
        ),
        filter=ReviewFilter(triggers=["best"]),
    )
    return listener


async def _async_main(args: argparse.Namespace, listener: FrigateListener) -> None:
    if args.replay:
        from frigate_monitoring.recorder import replay

        await replay(Path(args.replay), listener, realtime=args.realtime)
    else:
        await listener.run()


def main() -> None:
    """Run the listener with a minimal default configuration."""
    parser = argparse.ArgumentParser(
        prog="frigate-monitor",
        description="Subscribe to Frigate MQTT reviews and dispatch actions.",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="Path to a YAML configuration file.",
    )
    parser.add_argument(
        "--record",
        metavar="FILE",
        help="Record incoming MQTT messages to a JSONL file.",
    )
    parser.add_argument(
        "--replay",
        metavar="FILE",
        help="Replay a recorded JSONL file instead of connecting to MQTT.",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="When replaying, sleep between messages to match original timing.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if args.verbose:
        logging.getLogger("frigate_monitoring").setLevel(logging.DEBUG)

    if args.config:
        from frigate_monitoring.loader import from_yaml

        listener = from_yaml(args.config)
    else:
        cfg = Config.from_env()
        init(cfg)
        listener = _default_listener()

    if args.record:
        from frigate_monitoring.recorder import MqttRecorder

        listener.add_recorder(MqttRecorder(Path(args.record)))

    try:
        trio.run(_async_main, args, listener)
    except KeyboardInterrupt:
        logging.info("Shutting down.")


if __name__ == "__main__":
    main()
