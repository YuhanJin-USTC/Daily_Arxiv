import copy
from contextlib import redirect_stdout
import io
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
from scripts.release_probe import (
    PROBE_ID,
    dispatch_probe,
    main,
    preview,
    rebind_sender,
    resolve_probe,
)
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

    def test_changed_sender_blocks_transport_until_explicit_rebind(self):
        self.dispatch(transport=Mock(side_effect=DeliveryFailure()))
        before = copy.deepcopy(self.state)
        saved_count = len(self.saved)
        self.config["notifications"]["smtp"]["sender"] = "replacement@example.net"
        report = self.dispatch()
        self.assertIn("sender_changed", report["blocked"])
        self.assertEqual(self.state, before)
        self.assertEqual(len(self.saved), saved_count)
        self.assertEqual(self.sent, [])

    def test_sender_rebind_preserves_failure_evidence_identity_and_attempts(self):
        self.dispatch(
            transport=Mock(
                side_effect=DeliveryFailure(
                    stage="connect", reason="timeout", exception_type="TimeoutError"
                )
            )
        )
        before = copy.deepcopy(self.record())
        self.config["notifications"]["smtp"]["sender"] = "replacement@example.net"
        rebind_sender(
            self.state,
            self.config,
            "User selected a new sender after the definitive connection failure",
            DAY,
        )
        record = self.record()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["sender"], "replacement@example.net")
        for field in (
            "attempts",
            "probe_id",
            "message_id",
            "recipient",
            "date",
            "site_url",
        ):
            self.assertEqual(record[field], before[field])
        self.assertEqual(
            record["resolutions"][-1]["prior"],
            {key: value for key, value in before.items() if key != "resolutions"},
        )
        self.assertEqual(record["resolutions"][-1]["resolution"], "sender_change")
        self.assertEqual(record["last_error"], before["last_error"])
        self.assertEqual(record["last_diagnostic"], before["last_diagnostic"])
        self.assertEqual(self.dispatch()["sent"], 1)
        self.assertEqual(record["attempts"], 2)
        self.assertEqual(str(self.sent[0]["From"]), "replacement@example.net")
        self.assertEqual(str(self.sent[0]["To"]), before["recipient"]["email"])
        self.assertEqual(str(self.sent[0]["Message-ID"]), before["message_id"])

    def test_sender_rebind_only_accepts_failed_with_note_and_changed_sender(self):
        self.dispatch(transport=Mock(side_effect=DeliveryFailure()))
        before = copy.deepcopy(self.state)
        with self.assertRaises(ValueError):
            rebind_sender(self.state, self.config, "No sender changed", DAY)
        self.config["notifications"]["smtp"]["sender"] = "replacement@example.net"
        with self.assertRaises(ValueError):
            rebind_sender(self.state, self.config, "", DAY)
        self.assertEqual(self.state, before)
        for status in ("pending", "sending", "uncertain", "sent", "cancelled"):
            self.record()["status"] = status
            snapshot = copy.deepcopy(self.state)
            with self.assertRaises(ValueError):
                rebind_sender(self.state, self.config, "Attempted sender change", DAY)
            self.assertEqual(self.state, snapshot)

    def test_sender_rebind_cli_publishes_state_without_smtp_or_credentials(self):
        self.dispatch(transport=Mock(side_effect=DeliveryFailure()))
        self.config["notifications"]["smtp"]["sender"] = "replacement@example.net"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            state_path = root / "data/notification-state.json"
            state_path.write_text(json.dumps(self.state))
            argv = [
                "release_probe.py",
                "--source",
                str(root),
                "--rebind-sender",
                "--repository",
                "example/repository",
                "--publish",
                "--note",
                "Confirmed provider switch",
                "--date",
                DAY,
            ]
            with (
                patch("sys.argv", argv),
                patch("scripts.release_probe.settings", return_value=self.config),
                patch("scripts.release_probe.Publisher") as publisher,
                patch("scripts.release_probe.SMTPTransport") as transport,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 0)
                publisher.return_value.assert_called_once_with(
                    ["data/notification-state.json"]
                )
                transport.assert_not_called()
            result = json.loads(state_path.read_text())["release_probes"][PROBE_ID]
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["attempts"], 1)
            self.assertEqual(result["sender"], "replacement@example.net")

    def test_sender_rebind_cli_requires_publication_without_writing(self):
        self.dispatch(transport=Mock(side_effect=DeliveryFailure()))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            state_path = root / "data/notification-state.json"
            state_path.write_text(json.dumps(self.state))
            before = state_path.read_bytes()
            with (
                patch(
                    "sys.argv",
                    [
                        "release_probe.py",
                        "--source",
                        str(root),
                        "--rebind-sender",
                        "--note",
                        "Confirmed switch",
                    ],
                ),
                patch("scripts.release_probe.Publisher") as publisher,
                patch("sys.stderr", io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(state_path.read_bytes(), before)
            publisher.assert_not_called()

    def test_sender_rebind_at_attempt_limit_requires_explicit_retry_resolution(self):
        failure = Mock(
            side_effect=DeliveryFailure(
                stage="connect", reason="timeout", exception_type="TimeoutError"
            )
        )
        for _ in range(self.config["notifications"]["smtp"]["max_attempts"]):
            self.dispatch(transport=failure)
        before = copy.deepcopy(self.record())
        self.config["notifications"]["smtp"]["sender"] = "replacement@example.net"
        rebind_sender(
            self.state,
            self.config,
            "Confirmed sender change after failed attempts",
            DAY,
        )
        self.assertEqual(self.record()["status"], "failed")
        self.assertEqual(self.record()["attempts"], before["attempts"])
        self.assertEqual(self.record()["last_error"], before["last_error"])
        self.assertEqual(self.record()["last_diagnostic"], before["last_diagnostic"])
        report = self.dispatch()
        self.assertIn("retry_limit_reached", report["blocked"])
        self.assertEqual(self.sent, [])
        resolve_probe(
            self.state,
            "retry",
            "Verified no accepted message; approve a new bounded attempt budget",
            DAY,
        )
        self.assertEqual(self.record()["attempts"], 0)
        self.assertEqual(
            self.record()["resolutions"][-1]["prior"]["attempts"], before["attempts"]
        )
        self.assertEqual(self.dispatch()["sent"], 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(str(self.sent[0]["From"]), "replacement@example.net")

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

    def test_sanitized_transport_failure_reason_is_persisted(self):
        failure = DeliveryFailure(
            stage="auth",
            reason="rejected",
            exception_type="SMTPAuthenticationError",
            smtp_code=535,
        )
        report = self.dispatch(transport=Mock(side_effect=failure))
        self.assertEqual(self.record()["last_error"], "smtp_auth_rejected")
        self.assertEqual(self.record()["last_diagnostic"]["smtp_code"], 535)
        self.assertEqual(report["diagnostic"], failure.diagnostic)

    def test_auth_cli_has_no_source_queue_publication_or_send(self):
        result = {
            "ok": True,
            "stage": "auth",
            "code": "smtp_authenticated",
            "smtp_code": 235,
        }
        with (
            patch("sys.argv", ["release_probe.py", "--check-auth"]),
            patch("scripts.release_probe.SMTPTransport") as transport,
            patch("scripts.release_probe.Publisher") as publisher,
            patch("scripts.release_probe.write_json") as write,
            redirect_stdout(io.StringIO()) as output,
        ):
            transport.return_value.check_auth.return_value = result
            self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue()), result)
            transport.return_value.check_auth.assert_called_once()
            publisher.assert_not_called()
            write.assert_not_called()

    def test_auth_cli_rejects_queue_or_publication_flags(self):
        for extra in (
            ["--source", "/not/read"],
            ["--publish"],
            ["--send"],
            ["--resolve", "retry"],
        ):
            with (
                patch("sys.argv", ["release_probe.py", "--check-auth", *extra]),
                patch("scripts.release_probe.SMTPTransport") as transport,
                patch("sys.stderr", io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            self.assertEqual(error.exception.code, 2)
            transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
