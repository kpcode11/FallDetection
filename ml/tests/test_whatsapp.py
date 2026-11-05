import sys
import urllib.parse
import unittest
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_DIR))
import server  # noqa: E402
import train  # noqa: E402
import whatsapp_notifier  # noqa: E402


class DummyResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyModel:
    def __init__(self, prediction: int) -> None:
        self.prediction = prediction

    def predict(self, features):
        return np.array([self.prediction])


class DummyMQTTClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, payload: str) -> None:
        self.published.append((topic, payload))


class WhatsAppAlertTests(unittest.TestCase):
    def setUp(self) -> None:
        server.recent_ml_results.clear()
        self.requests = []
        self.current_time = 1000.0

    def fake_opener(self, req, timeout=8):
        self.requests.append((req, timeout))
        return DummyResponse(200)

    def make_notifier(self, **overrides) -> whatsapp_notifier.WhatsAppNotifier:
        env = {
            "WHATSAPP_ENABLED": "true",
            "WHATSAPP_PROVIDER": "callmebot",
            "WHATSAPP_ALERT_MODE": "hybrid",
            "WHATSAPP_COOLDOWN_SECONDS": "30",
            "CALLMEBOT_PHONE": "+919876543210",
            "CALLMEBOT_API_KEY": "123456",
        }
        env.update(overrides)
        return whatsapp_notifier.WhatsAppNotifier(
            env=env,
            http_opener=self.fake_opener,
            time_fn=lambda: self.current_time,
        )

    def test_callmebot_sends_and_enforces_cooldown(self):
        notifier = self.make_notifier()
        sent1 = notifier.send_alert(
            device_id="wearable-01",
            event_type="FALL_ALERT",
            reason="Fall confirmed - no response from wearer",
            ml_status="Confirmed by Random Forest Classifier",
            async_send=False,
        )
        self.assertTrue(sent1)
        self.assertEqual(len(self.requests), 1)
        req, _ = self.requests[0]
        self.assertIn("api.callmebot.com/whatsapp.php", req.full_url)
        self.assertIn("apikey=123456", req.full_url)

        # Immediate second alert for same device should be blocked by 30s cooldown
        sent2 = notifier.send_alert(
            device_id="wearable-01",
            event_type="FALL_ALERT",
            reason="Fall confirmed - no response from wearer",
            async_send=False,
        )
        self.assertFalse(sent2)
        self.assertEqual(len(self.requests), 1)

        # Advance past cooldown -> allowed again
        self.current_time += 31.0
        sent3 = notifier.send_alert(
            device_id="wearable-01",
            event_type="FALL_ALERT",
            reason="Fall confirmed - no response from wearer",
            async_send=False,
        )
        self.assertTrue(sent3)
        self.assertEqual(len(self.requests), 2)

    def test_twilio_formats_post_and_supports_multiple_recipients(self):
        notifier = self.make_notifier(
            WHATSAPP_PROVIDER="twilio",
            TWILIO_ACCOUNT_SID="AC111122223333",
            TWILIO_AUTH_TOKEN="secret_token",
            TWILIO_WHATSAPP_FROM="whatsapp:+14155238886",
            CAREGIVER_WHATSAPP_TO="+919876543210, +919123456789",
        )
        sent = notifier.send_alert(
            device_id="wearable-01",
            event_type="FALL_ALERT",
            reason="Manual SOS button pressed",
            async_send=False,
        )
        self.assertTrue(sent)
        self.assertEqual(len(self.requests), 2)
        first_req, _ = self.requests[0]
        self.assertEqual(first_req.get_method(), "POST")
        self.assertIn("Accounts/AC111122223333/Messages.json", first_req.full_url)
        body_params = urllib.parse.parse_qs(first_req.data.decode("utf-8"))
        self.assertEqual(body_params["To"], ["whatsapp:+919876543210"])
        self.assertIn("Manual SOS button pressed", body_params["Body"][0])

    def test_cancelled_grace_period_does_not_send_whatsapp_in_hybrid_mode(self):
        notifier = self.make_notifier(WHATSAPP_ALERT_MODE="hybrid")
        mqtt_client = DummyMQTTClient()
        window = np.ones((train.WINDOW_SIZE, 3)).tolist()

        # Impact triggers publishWindowData() at start of 8s grace period
        is_fall = server.handle_sensor_data(
            mqtt_client,
            {"device": "wearable-01", "window": window},
            active_model=DummyModel(1),
            active_notifier=notifier,
            now_fn=lambda: self.current_time,
        )
        self.assertTrue(is_fall)
        # User clicks SOS button during 8s grace period -> ESP32 never sends FALL_ALERT
        self.assertEqual(len(self.requests), 0)

        # If 8s expires without cancel, ESP32 sends FALL_ALERT -> WhatsApp is sent with ML confirmation
        sent = server.handle_alert_message(
            {
                "device": "wearable-01",
                "event": "FALL_ALERT",
                "reason": "Fall confirmed - no response from wearer",
            },
            active_notifier=notifier,
            now_fn=lambda: self.current_time + 8.0,
        )
        self.assertTrue(sent)

    def test_ml_strict_mode_suppresses_adl_window_but_allows_manual_sos(self):
        notifier = self.make_notifier(WHATSAPP_ALERT_MODE="ml_strict")
        mqtt_client = DummyMQTTClient()
        window = np.ones((train.WINDOW_SIZE, 3)).tolist()

        # ML classifies window as ADL (0)
        server.handle_sensor_data(
            mqtt_client,
            {"device": "wearable-01", "window": window},
            active_model=DummyModel(0),
            active_notifier=notifier,
            now_fn=lambda: self.current_time,
        )
        suppressed = server.handle_alert_message(
            {
                "device": "wearable-01",
                "event": "FALL_ALERT",
                "reason": "Fall confirmed - no response from wearer",
            },
            active_notifier=notifier,
            now_fn=lambda: self.current_time + 8.0,
        )
        self.assertFalse(suppressed)

        # Manual SOS must still send even in ml_strict mode
        manual_ok = server.handle_alert_message(
            {
                "device": "wearable-01",
                "event": "FALL_ALERT",
                "reason": "Manual SOS button pressed",
            },
            active_notifier=notifier,
            now_fn=lambda: self.current_time + 10.0,
        )
        self.assertTrue(manual_ok)


if __name__ == "__main__":
    unittest.main()

