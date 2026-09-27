"""
Multi-channel notification dispatchers for PulseGuard.
Supports Discord, Telegram, Slack, and generic JSON Webhooks using urllib.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Optional

logger = logging.getLogger("pulseguard.notifiers")


class BaseNotifier:
    def send(self, title: str, message: str, level: str = "warning") -> bool:
        raise NotImplementedError


class ConsoleNotifier(BaseNotifier):
    def send(self, title: str, message: str, level: str = "warning") -> bool:
        prefix = "🚨 [ALERT]" if level in ("danger", "warning") else "✅ [RECOVERY]"
        print(f"\n{prefix} {title}\n{message}\n")
        return True


class DiscordNotifier(BaseNotifier):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, message: str, level: str = "warning") -> bool:
        # Colors: red for danger/warning, green for recovery/info
        color = 0xDC2626 if level in ("danger", "warning") else 0x16A34A
        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color,
                    "footer": {"text": "PulseGuard Heartbeat Monitor"}
                }
            ]
        }
        return _post_json(self.webhook_url, payload)


class TelegramNotifier(BaseNotifier):
    def __init__(self, bot_token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id

    def send(self, title: str, message: str, level: str = "warning") -> bool:
        emoji = "🚨" if level in ("danger", "warning") else "✅"
        text = f"{emoji} *{title}*\n\n{message}"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        return _post_json(self.url, payload)


class SlackNotifier(BaseNotifier):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, message: str, level: str = "warning") -> bool:
        emoji = ":rotating_light:" if level in ("danger", "warning") else ":white_check_mark:"
        payload = {
            "text": f"{emoji} *{title}*\n```{message}```"
        }
        return _post_json(self.webhook_url, payload)


class WebhookNotifier(BaseNotifier):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, message: str, level: str = "warning") -> bool:
        payload = {
            "title": title,
            "message": message,
            "level": level,
            "source": "pulseguard"
        }
        return _post_json(self.webhook_url, payload)


def _post_json(url: str, payload: dict[str, Any], timeout: int = 10) -> bool:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "PulseGuard/1.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        logger.error(f"Failed to deliver notification to {url}: {e}")
        return False
