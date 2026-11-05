"""WhatsApp alert notification module for the IoE Fall Detection System.

Supports CallMeBot (free/instant setup), Twilio WhatsApp API, and Meta WhatsApp Cloud API
using only Python's standard library so no extra third-party dependencies are required.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATHS = (MODULE_DIR / ".env", MODULE_DIR.parent / ".env")


def load_dotenv_files(paths: tuple[Path, ...] = DEFAULT_ENV_PATHS) -> None:
    """Load key=value pairs from .env files into os.environ without overwriting existing vars."""
    for path in paths:
        if not path.is_file():
            continue
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            pass


def format_whatsapp_message(
    device_id: str,
    event_type: str,
    reason: str,
    ml_status: str | None = None,
    timestamp_str: str | None = None,
) -> str:
    """Format a human-readable emergency WhatsApp message for caregivers."""
    now_str = timestamp_str or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if ml_status is None:
        if "manual sos" in reason.lower():
            ml_status = "N/A (Manual SOS Trigger)"
        else:
            ml_status = "Pending / Threshold Trigger"

    lines = [
        "*EMERGENCY FALL ALERT*",
        f"• *Device:* {device_id}",
        f"• *Event:* {event_type}",
        f"• *Reason:* {reason}",
        f"• *ML Verification:* {ml_status}",
        f"• *Time:* {now_str}",
        "",
        "Please check on the individual immediately!",
    ]
    return "\n".join(lines)


class WhatsAppNotifier:
    """Rate-limited WhatsApp notification client supporting CallMeBot, Twilio, and Meta Cloud API."""

    def __init__(
        self,
        env: dict[str, str] | None = None,
        http_opener: Callable[..., object] | None = None,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        load_dotenv_files()
        cfg = env if env is not None else os.environ
        self.enabled = cfg.get("WHATSAPP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
        self.provider = cfg.get("WHATSAPP_PROVIDER", "callmebot").strip().lower()
        self.alert_mode = cfg.get("WHATSAPP_ALERT_MODE", "hybrid").strip().lower()
        try:
            self.cooldown_seconds = float(cfg.get("WHATSAPP_COOLDOWN_SECONDS", "30"))
        except ValueError:
            self.cooldown_seconds = 30.0

        # CallMeBot settings
        self.callmebot_phone = cfg.get("CALLMEBOT_PHONE", "").strip()
        self.callmebot_apikey = cfg.get("CALLMEBOT_API_KEY", "").strip()

        # Twilio WhatsApp settings
        self.twilio_sid = cfg.get("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_token = cfg.get("TWILIO_AUTH_TOKEN", "").strip()
        self.twilio_from = cfg.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886").strip()
        self.twilio_to = [
            item.strip()
            for item in cfg.get("CAREGIVER_WHATSAPP_TO", "").split(",")
            if item.strip()
        ]

        # Meta WhatsApp Cloud API settings
        self.meta_token = cfg.get("META_ACCESS_TOKEN", "").strip()
        self.meta_phone_id = cfg.get("META_PHONE_NUMBER_ID", "").strip()
        self.meta_to = [
            item.strip().lstrip("+")
            for item in cfg.get("CAREGIVER_WHATSAPP_TO", "").split(",")
            if item.strip()
        ]

        self._opener = http_opener or urllib.request.urlopen
        self._time_fn = time_fn
        self._last_sent_by_device: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_configured(self) -> bool:
        """Return True if the selected provider has all required credentials present."""
        if not self.enabled:
            return False
        if self.provider == "callmebot":
            return bool(self.callmebot_phone and self.callmebot_apikey)
        if self.provider == "twilio":
            return bool(self.twilio_sid and self.twilio_token and self.twilio_from and self.twilio_to)
        if self.provider == "meta":
            return bool(self.meta_token and self.meta_phone_id and self.meta_to)
        return False

    def _check_and_update_cooldown(self, device_id: str) -> bool:
        now = self._time_fn()
        with self._lock:
            last_time = self._last_sent_by_device.get(device_id)
            if last_time is not None and (now - last_time) < self.cooldown_seconds:
                return False
            self._last_sent_by_device[device_id] = now
            return True

    def send_alert(
        self,
        device_id: str,
        event_type: str,
        reason: str,
        ml_status: str | None = None,
        async_send: bool = True,
    ) -> bool:
        """Send a WhatsApp alert if enabled, configured, and outside the cooldown window."""
        if not self.enabled:
            print("[WhatsApp] Notifications disabled via WHATSAPP_ENABLED=false.")
            return False

        if not self.is_configured():
            print(
                f"[WhatsApp] Provider '{self.provider}' is not configured yet. "
                "Set credentials in ml/.env (see ml/.env.example)."
            )
            return False

        if not self._check_and_update_cooldown(device_id):
            print(f"[WhatsApp] Skipped duplicate alert for '{device_id}' (cooldown {self.cooldown_seconds}s active).")
            return False

        message = format_whatsapp_message(
            device_id=device_id,
            event_type=event_type,
            reason=reason,
            ml_status=ml_status,
        )

        if async_send:
            thread = threading.Thread(
                target=self._dispatch_message,
                args=(message,),
                daemon=True,
            )
            thread.start()
            return True
        return self._dispatch_message(message)

    def _dispatch_message(self, message: str) -> bool:
        try:
            if self.provider == "callmebot":
                self._send_callmebot(message)
            elif self.provider == "twilio":
                self._send_twilio(message)
            elif self.provider == "meta":
                self._send_meta(message)
            else:
                print(f"[WhatsApp] Unsupported provider: {self.provider}")
                return False
            print(f"[WhatsApp] Alert sent successfully via {self.provider}.")
            return True
        except Exception as exc:
            print(f"[WhatsApp] Failed to send alert via {self.provider}: {exc}")
            return False

    def _send_callmebot(self, message: str) -> None:
        query = urllib.parse.urlencode(
            {
                "phone": self.callmebot_phone,
                "text": message,
                "apikey": self.callmebot_apikey,
            }
        )
        url = f"https://api.callmebot.com/whatsapp.php?{query}"
        req = urllib.request.Request(url, method="GET")
        with self._opener(req, timeout=8) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise RuntimeError(f"CallMeBot HTTP {status}")

    def _send_twilio(self, message: str) -> None:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
        credentials = f"{self.twilio_sid}:{self.twilio_token}".encode("utf-8")
        auth_header = "Basic " + base64.b64encode(credentials).decode("ascii")
        from_addr = self.twilio_from if self.twilio_from.startswith("whatsapp:") else f"whatsapp:{self.twilio_from}"

        for recipient in self.twilio_to:
            to_addr = recipient if recipient.startswith("whatsapp:") else f"whatsapp:{recipient}"
            data = urllib.parse.urlencode({"From": from_addr, "To": to_addr, "Body": message}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            )
            with self._opener(req, timeout=8) as response:
                status = getattr(response, "status", 201)
                if status >= 400:
                    raise RuntimeError(f"Twilio HTTP {status}")

    def _send_meta(self, message: str) -> None:
        url = f"https://graph.facebook.com/v19.0/{self.meta_phone_id}/messages"
        for recipient in self.meta_to:
            payload = json.dumps(
                {
                    "messaging_product": "whatsapp",
                    "to": recipient,
                    "type": "text",
                    "text": {"preview_url": False, "body": message},
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.meta_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with self._opener(req, timeout=8) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise RuntimeError(f"Meta Cloud API HTTP {status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test WhatsApp fall alert using ml/.env settings.")
    parser.add_argument("--device", default="wearable-01", help="Device ID to display in the test message.")
    parser.add_argument("--reason", default="Test fall alert from CLI", help="Alert reason string.")
    args = parser.parse_args()

    notifier = WhatsAppNotifier()
    print(f"Provider: {notifier.provider} | Configured: {notifier.is_configured()} | Mode: {notifier.alert_mode}")
    ok = notifier.send_alert(
        device_id=args.device,
        event_type="FALL_ALERT",
        reason=args.reason,
        ml_status="Confirmed by Random Forest Classifier (CLI Test)",
        async_send=False,
    )
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

