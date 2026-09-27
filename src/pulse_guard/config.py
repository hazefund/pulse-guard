"""
Configuration loader for PulseGuard daemon.
Supports JSON or simple YAML/key-value configuration files.
"""

import json
import os
from typing import Any

from .notifiers import (
    BaseNotifier,
    ConsoleNotifier,
    DiscordNotifier,
    TelegramNotifier,
    SlackNotifier,
    WebhookNotifier
)


def load_config(config_path: str) -> dict[str, Any]:
    if not os.path.exists(config_path):
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Try JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Simple YAML key-value parser fallback if PyYAML is not installed
    config: dict[str, Any] = {}
    current_section = None
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":") and not line.startswith("-"):
            current_section = line[:-1].strip()
            config[current_section] = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if current_section:
                config[current_section][k] = v
            else:
                config[k] = v
    return config


def build_notifiers_from_config(config: dict[str, Any]) -> list[BaseNotifier]:
    notifiers: list[BaseNotifier] = [ConsoleNotifier()]

    alerts_cfg = config.get("alerts", {})

    discord_url = alerts_cfg.get("discord_webhook") or os.environ.get("PULSEGUARD_DISCORD_WEBHOOK")
    if discord_url:
        notifiers.append(DiscordNotifier(discord_url))

    tg_token = alerts_cfg.get("telegram_bot_token") or os.environ.get("PULSEGUARD_TELEGRAM_BOT_TOKEN")
    tg_chat = alerts_cfg.get("telegram_chat_id") or os.environ.get("PULSEGUARD_TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        notifiers.append(TelegramNotifier(tg_token, tg_chat))

    slack_url = alerts_cfg.get("slack_webhook") or os.environ.get("PULSEGUARD_SLACK_WEBHOOK")
    if slack_url:
        notifiers.append(SlackNotifier(slack_url))

    webhook_url = alerts_cfg.get("generic_webhook") or os.environ.get("PULSEGUARD_GENERIC_WEBHOOK")
    if webhook_url:
        notifiers.append(WebhookNotifier(webhook_url))

    return notifiers
