import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daily_arxiv"))
from daily_arxiv.notifications import DeliveryFailure, enqueue_discoveries, new_state
from scripts.release_probe import PROBE_ID, dispatch_probe, preview, resolve_probe
from test_notifications import DAY, ENV, configuration
from test_researchers import paper


class ReleaseProbeTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()
        self.state = new_state(["2601.11111"])
        self.saved = []
        self.sent = []

    def dispatch(self, **kwargs):
        return dispatch_probe(
            self.state,
            self.config,
            kwargs.pop("persist", self.saved.append),
            transport=kwargs.pop("transport", self.sent.append),
            environment=kwargs.pop("environment", ENV),
            day=DAY,
            **kwargs,
        )

    def record(self):
        return self.state["release_probes"][PROBE_ID]

    def test_preview_is_infrastructure_only_and_has_no_side_effects(self):
        before = copy.deepcopy(self.state)
        message = preview(self.state, self.config, day=DAY)
        self.assertIn("not a paper digest", message.get_content())
        self.assertIn("no historical paper notification", message.get_content())
        self.assertNotIn("arxiv.org/abs/", message.get_content())
        self.assertEqual(str(message["To"]), "first@example.org")
        self.assertEqual(self.state, before)
        self.assertEqual(self.sent, [])

    def test_exactly_one_configured_recipient_and_durable_sending_before_transport(
        self,
    ):
        def transport(message):
            self.assertEqual(
                self.saved[-1]["release_probes"][PROBE_ID]["status"], "sending"
            )
            self.sent.append(message)

        before = copy.deepcopy(self.state)
        self.assertEqual(self.dispatch(transport=transport)["sent"], 1)
        self.assertEqual(str(self.sent[0]["To"]), "first@example.org")
        self.assertEqual(self.record()["status"], "sent")
        for key, value in before.items():
            self.assertEqual(self.state[key], value)
        result = self.dispatch(recipient_id="second")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["sent"], 0)
        self.assertEqual(len(self.sent), 1)

    def test_selected_recipient_must_be_enabled_and_configured(self):
        for recipient in ("unknown", "disabled"):
            self.config["notifications"]["recipients"].append(
                {"id": "disabled", "email": "disabled@example.org", "enabled": False}
            )
            with self.assertRaises(ValueError):
                self.dispatch(recipient_id=recipient)
        self.assertNotIn("release_probes", self.state)
        self.assertEqual(self.sent, [])

    def test_retry_has_stable_message_id_and_bounded_explicit_failures(self):
        messages = []

        def fail(message):
            messages.append(message)
            raise DeliveryFailure("server secret-like text must not persist")

        self.assertEqual(self.dispatch(transport=fail)["failed"], 1)
        self.assertEqual(self.dispatch(transport=fail)["failed"], 1)
        result = self.dispatch(transport=fail)
        self.assertIn("retry_limit_reached", result["blocked"])
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["Message-ID"], messages[1]["Message-ID"])
        self.assertNotIn("secret-like", json.dumps(self.state))

    def test_ambiguous_send_never_automatically_retries(self):
        result = self.dispatch(
            transport=Mock(side_effect=TimeoutError("response lost"))
        )
        self.assertEqual(result["uncertain"], 1)
        self.assertEqual(self.dispatch()["uncertain"], 1)
        self.assertEqual(self.sent, [])
        with self.assertRaises(ValueError):
            resolve_probe(self.state, "retry", "", DAY)
        resolve_probe(
            self.state, "sent", "Recipient confirmed the stable Message-ID", DAY
        )
        self.assertEqual(self.dispatch()["status"], "sent")
        self.assertEqual(self.sent, [])

    def test_pre_send_persistence_failure_prevents_send_and_recovery_is_uncertain(self):
        result = self.dispatch(persist=Mock(side_effect=OSError("push failed")))
        self.assertIn("pre_send_persistence_failed", result["errors"])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.record()["status"], "sending")
        self.assertEqual(self.dispatch()["uncertain"], 1)
        self.assertEqual(self.record()["status"], "uncertain")
        self.assertEqual(self.sent, [])

    def test_post_send_persistence_failure_retains_uncertainty(self):
        calls = 0

        def persist(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("push failed")
            self.saved.append(value)

        result = self.dispatch(persist=persist)
        self.assertEqual(result["uncertain"], 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(
            self.saved[-1]["release_probes"][PROBE_ID]["status"], "uncertain"
        )
        self.dispatch()
        self.assertEqual(len(self.sent), 1)

    def test_missing_guard_or_credentials_never_connect(self):
        with patch("daily_arxiv.notifications.smtplib.SMTP_SSL") as connect:
            self.assertIn("sending_disabled", self.dispatch(environment={})["blocked"])
            with self.assertRaises(ValueError):
                dispatch_probe(
                    self.state,
                    self.config,
                    self.saved.append,
                    environment={"ALLOW_SMTP_SEND": "1"},
                    day=DAY,
                )
            connect.assert_not_called()
        self.assertEqual(self.saved, [])
        self.assertNotIn("release_probes", self.state)

    def test_failed_probe_does_not_retarget_after_email_change(self):
        self.dispatch(transport=Mock(side_effect=DeliveryFailure()))
        self.config["notifications"]["recipients"][0]["email"] = "changed@example.org"
        self.assertIn("recipient_changed", self.dispatch()["blocked"])
        resolve_probe(
            self.state, "cancelled", "Cancel old recipient's failed probe", DAY
        )
        self.assertEqual(self.dispatch()["status"], "cancelled")
        self.assertEqual(self.sent, [])

    def test_probe_survives_normal_queue_serialization_and_discovery(self):
        self.dispatch()
        restored = json.loads(json.dumps(self.state))
        updated = enqueue_discoveries(restored, [paper()], DAY, self.config)
        self.assertEqual(updated["release_probes"], self.state["release_probes"])
        self.assertEqual(updated["historical_ids"], ["2601.11111"])
        self.assertIn("2610.12345", updated["discoveries"])

    def test_corrupted_probe_history_never_resets_to_a_new_send(self):
        for value in (None, {}, [], {"status": "sent"}):
            self.state["release_probes"] = {PROBE_ID: value}
            with self.assertRaises(ValueError):
                self.dispatch()
            with self.assertRaises(ValueError):
                preview(self.state, self.config, day=DAY)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.saved, [])

    def test_manual_retry_requires_evidence_and_keeps_prior_attempts(self):
        self.dispatch(transport=Mock(side_effect=TimeoutError()))
        resolve_probe(
            self.state,
            "retry",
            "SMTP log proves the DATA command was not accepted",
            DAY,
        )
        self.assertEqual(self.record()["attempts"], 0)
        self.assertEqual(self.record()["resolutions"][0]["prior"]["attempts"], 1)
        self.assertEqual(self.dispatch()["sent"], 1)
        self.assertEqual(len(self.sent), 1)

    def test_default_cli_preview_does_not_write_or_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            path = root / "data/notification-state.json"
            path.write_text(json.dumps(self.state))
            before = path.read_bytes()
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/release_probe.py"),
                    "--source",
                    str(root),
                    "--date",
                    DAY,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SMTP release verification", result.stdout)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
