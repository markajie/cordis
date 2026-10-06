"""Cordis Harness: AI coding assistant runtime built on Cordis plugin framework."""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    """CLI entry point for cordis-harness."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Cordis Harness - AI coding assistant",
        prog="cordis-harness",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to cordis.json config file (default: ./cordis.json)",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="Override the default model name",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="Disable kernel sandboxing",
    )

    args = parser.parse_args()

    # Load config once and apply CLI overrides
    from cordis_harness.config import load_config
    config = load_config(args.config)

    if args.model:
        config.setdefault("models", {})["default"] = args.model
    if args.no_sandbox:
        config.setdefault("kernel", {})["sandbox"] = False

    # Run the harness with the already-merged config
    from cordis_harness.bootstrap import run
    try:
        asyncio.run(run(config=config))
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
