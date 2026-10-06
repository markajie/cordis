"""Configuration loader for cordis-harness.

Loads settings from cordis.json with environment variable overrides for secrets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "models": {
        "default": "gpt-4o",
        "providers": {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
            }
        },
    },
    "agent": {
        "max_nudges": 2,
    },
    "kernel": {
        "sandbox": False,
        "timeout": 30,
    },
    "context": {
        "project_dir": ".",
        "instructions_file": "CLAUDE.md",
    },
    "transcript": {
        "path": None,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration from a JSON file, merged over defaults.

    Args:
        path: Path to cordis.json. If None, searches current directory.

    Returns:
        Merged configuration dict.
    """
    config = dict(DEFAULT_CONFIG)

    if path is None:
        path = Path("cordis.json")
    else:
        path = Path(path)

    if path.exists():
        with open(path, encoding="utf-8") as f:
            user_config = json.load(f)
        config = _deep_merge(config, user_config)

    # Environment variable overrides for API keys
    providers = config.get("models", {}).get("providers", {})
    for provider_name, provider_cfg in providers.items():
        if isinstance(provider_cfg, dict):
            env_var = provider_cfg.get("api_key_env")
            if env_var and env_var in os.environ:
                provider_cfg["api_key"] = os.environ[env_var]

    return config


def get_plugin_config(config: dict[str, Any], plugin_name: str) -> dict[str, Any]:
    """Extract a plugin's config section from the full config.

    Args:
        config: Full harness configuration.
        plugin_name: Plugin name (e.g., 'models', 'agent', 'kernel').

    Returns:
        Plugin-specific config dict, or empty dict if not found.
    """
    return config.get(plugin_name, {})
