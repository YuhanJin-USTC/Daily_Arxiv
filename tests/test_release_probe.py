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
from test_notifications import DAY, ENV, HTMLAudit, configuration
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
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        self.assertIn("not a paper digest", plain)
        self.assertIn("no historical paper notification", plain)
        self.assertNotIn("arxiv.org/abs/", plain)
        self.assertIn("font-family: 'Times New Roman', Times, serif", html)
        self.assertEqual(str(message["To"]), "first@example.org")
        self.assertEqual(self.state, before)
        self.assertEqual(self.sent, [])

    def test_probe_html_escapes_site_url_and_keeps_plain_text(self):
        site = 'https://example.org/?q="<test>"&x=1'
        self.config["notifications"]["site_url"] = site
        message = preview(self.state, self.config, day=DAY)
        plain = message.get_body(preferencelist=("plain",)).get_content()
        self.assertEqual(
            plain,
            (
                "This is the one-time English delivery test for the bilingual Daily Arxiv site.\n\n"
                "This message tests SMTP delivery only. It is not a paper digest, and no historical paper notification is being sent.\n\n"
                "Site: " + site + "\nProbe ID: initial-release-v1\n\n"
                "The sending state was saved before SMTP. Please retain this message as delivery evidence.\n"
            ),
        )
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("&quot;&lt;test&gt;&quot;&amp;x=1", html)
        audit = HTMLAudit()
        audit.feed(html)
        self.assertLessEqual(
            {tag for tag, _ in audit.elements}, {"html", "body", "div", "p", "br", "a"}
        )
        self.assertEqual(
            [attrs["href"] for tag, attrs in audit.elements if tag == "a"], [site]
        )

    def test_probe_html_rejects_non_http_site_url(self):
        self.config["notifications"]["site_url"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            preview(self.state, self.config, day=DAY)

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
            ["--recipient", ""],
            ["--recipient-test", ""],
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


class RecipientLayoutTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()
        self.state = new_state(["2601.11111"])
        dispatch_probe(
            self.state, self.config, Mock(), transport=Mock(), environment=ENV, day=DAY
        )
        self.original = copy.deepcopy(self.state)
        self.scope = "recipient-layout-v1:second"
        self.sent = []
        self.saved = []

    def dispatch(self, **kwargs):
        return dispatch_probe(
            self.state,
            self.config,
            kwargs.pop("persist", self.saved.append),
            transport=kwargs.pop("transport", self.sent.append),
            environment=ENV,
            day=DAY,
            recipient_test=kwargs.pop("recipient_test", "second"),
            **kwargs,
        )

    def changed_recipient_config(self, change):
        config = copy.deepcopy(self.config)
        recipients = config["notifications"]["recipients"]
        if change == "disabled":
            recipients[1]["enabled"] = False
        elif change == "removed":
            recipients.pop(1)
        else:
            recipients[1]["email"] = "changed@example.org"
        return config

    def test_preview_targets_only_selected_inbox_without_mutating_initial(self):
        message = preview(self.state, self.config, day=DAY, recipient_test="second")
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertEqual(str(message["To"]), "second@example.org")
        self.assertEqual(str(message["Subject"]), "Daily Arxiv font and inbox test")
        self.assertIn("not a paper digest", plain)
        self.assertIn("No historical paper notifications", plain)
        self.assertIn(self.scope, plain)
        self.assertIn("font-family: 'Times New Roman', Times, serif", html)
        self.assertNotIn("arxiv.org/abs/", plain)
        repeated = preview(
            self.state, self.config, day="2026-10-22", recipient_test="second"
        )
        self.assertEqual(message["Message-ID"], repeated["Message-ID"])
        self.assertNotEqual(
            message["Message-ID"],
            self.original["release_probes"][PROBE_ID]["message_id"],
        )
        self.assertEqual(self.state, self.original)

    def test_send_once_with_durable_scope_preserves_initial_and_paper_queue(self):
        def transport(message):
            self.assertEqual(
                self.saved[-1]["release_probes"][self.scope]["status"], "sending"
            )
            self.assertEqual(
                self.saved[-1]["release_probes"][PROBE_ID],
                self.original["release_probes"][PROBE_ID],
            )
            self.sent.append(message)

        report = self.dispatch(transport=transport)
        self.assertEqual(report["probe_id"], self.scope)
        self.assertEqual(report["sent"], 1)
        self.assertEqual(str(self.sent[0]["To"]), "second@example.org")
        self.assertEqual(
            self.state["release_probes"][PROBE_ID],
            self.original["release_probes"][PROBE_ID],
        )
        for key in (
            "historical_ids",
            "discoveries",
            "deliveries",
            "batches",
            "resolutions",
        ):
            self.assertEqual(self.state[key], self.original[key])
        before = copy.deepcopy(self.state)
        self.assertEqual(self.dispatch()["sent"], 0)
        self.config["notifications"]["recipients"][1]["email"] = "changed@example.org"
        self.assertEqual(self.dispatch()["sent"], 0)
        self.assertEqual(self.state, before)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(set(self.state["release_probes"]), {PROBE_ID, self.scope})

    def test_only_enabled_configured_ids_and_one_selector_are_accepted(self):
        self.config["notifications"]["recipients"][1]["enabled"] = False
        for identifier in ("second", "unknown", "../second", "second:new", ""):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                self.dispatch(recipient_test=identifier)
        with self.assertRaises(ValueError):
            self.dispatch(recipient_id="first")
        self.assertEqual(self.state, self.original)
        self.assertEqual(self.sent, [])

    def test_unknown_delivery_requires_resolution_in_the_same_scope(self):
        result = self.dispatch(
            transport=Mock(side_effect=TimeoutError("lost response"))
        )
        self.assertEqual(result["uncertain"], 1)
        self.assertEqual(self.dispatch()["uncertain"], 1)
        with self.assertRaises(ValueError):
            resolve_probe(self.state, "sent", "", DAY, recipient_test="second")
        resolve_probe(
            self.state,
            "sent",
            "Selected recipient confirmed the Message-ID",
            DAY,
            recipient_test="second",
        )
        self.assertEqual(self.dispatch()["sent"], 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(
            self.state["release_probes"][PROBE_ID],
            self.original["release_probes"][PROBE_ID],
        )
        self.assertEqual(
            self.state["release_probes"][self.scope]["resolutions"][-1]["prior"][
                "status"
            ],
            "uncertain",
        )

    def test_failed_attempts_are_bounded_and_reuse_the_message_id(self):
        messages = []

        def reject(message):
            messages.append(message)
            raise DeliveryFailure()

        self.assertEqual(self.dispatch(transport=reject)["failed"], 1)
        self.assertEqual(self.dispatch(transport=reject)["failed"], 1)
        self.assertIn("retry_limit_reached", self.dispatch()["blocked"])
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["Message-ID"], messages[1]["Message-ID"])
        resolve_probe(
            self.state,
            "retry",
            "Verified explicit rejection; approve bounded retry",
            DAY,
            recipient_test="second",
        )
        self.assertEqual(self.dispatch()["sent"], 1)
        self.assertEqual(self.sent[0]["Message-ID"], messages[0]["Message-ID"])
        self.assertEqual(
            self.state["release_probes"][PROBE_ID],
            self.original["release_probes"][PROBE_ID],
        )

    def test_persistence_failures_never_resend_or_change_original_probe(self):
        for fail_at in (1, 2):
            with self.subTest(fail_at=fail_at):
                self.state = copy.deepcopy(self.original)
                self.sent = []
                calls = 0

                def persist(value):
                    nonlocal calls
                    calls += 1
                    if calls == fail_at:
                        raise OSError("publish failed")

                report = self.dispatch(persist=persist)
                self.assertTrue(report["errors"])
                self.assertEqual(len(self.sent), fail_at - 1)
                self.assertEqual(self.dispatch()["uncertain"], 1)
                self.assertEqual(len(self.sent), fail_at - 1)
                self.assertEqual(
                    self.state["release_probes"][PROBE_ID],
                    self.original["release_probes"][PROBE_ID],
                )

    def test_misbound_scope_or_recipient_is_rejected_without_sending(self):
        original_probe = self.original["release_probes"][PROBE_ID]
        for wrong in (original_probe, {**original_probe, "probe_id": self.scope}):
            self.state = copy.deepcopy(self.original)
            self.state["release_probes"][self.scope] = copy.deepcopy(wrong)
            with self.assertRaises(ValueError):
                self.dispatch()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.saved, [])

    def test_cli_send_and_manual_resolution_use_the_explicit_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            state_path = root / "data/notification-state.json"
            state_path.write_text(json.dumps(self.state))
            base = [
                "release_probe.py",
                "--source",
                str(root),
                "--repository",
                "example/repository",
                "--recipient-test",
                "second",
                "--publish",
                "--date",
                DAY,
            ]
            phases = []

            def published(paths):
                phases.append(
                    json.loads(state_path.read_text())["release_probes"][self.scope][
                        "status"
                    ]
                )

            with (
                patch("sys.argv", [*base, "--send"]),
                patch("scripts.release_probe.settings", return_value=self.config),
                patch("scripts.release_probe.Publisher") as publisher,
                patch("scripts.release_probe.SMTPTransport") as transport,
                patch.dict("os.environ", ENV),
                redirect_stdout(io.StringIO()),
            ):
                publisher.return_value.side_effect = published
                transport.return_value.side_effect = TimeoutError("unknown")
                self.assertEqual(main(), 1)
                self.assertEqual(phases, ["sending", "uncertain"])
                self.assertEqual(
                    str(transport.return_value.call_args.args[0]["To"]),
                    "second@example.org",
                )
            with (
                patch(
                    "sys.argv",
                    [
                        *base,
                        "--resolve",
                        "sent",
                        "--note",
                        "Inbox confirms this Message-ID",
                    ],
                ),
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
            saved = json.loads(state_path.read_text())
            self.assertEqual(saved["release_probes"][self.scope]["status"], "sent")
            self.assertEqual(
                saved["release_probes"][PROBE_ID],
                self.original["release_probes"][PROBE_ID],
            )

    def test_cli_rejects_combined_selectors_auth_and_arbitrary_probe_id(self):
        for extra in (
            ["--recipient", "first"],
            ["--check-auth"],
            ["--probe-id", "new-arbitrary-id"],
        ):
            with (
                patch(
                    "sys.argv",
                    ["release_probe.py", "--recipient-test", "second", *extra],
                ),
                patch("scripts.release_probe.settings", return_value=self.config),
                patch("scripts.release_probe.SMTPTransport") as transport,
                patch("scripts.release_probe.Publisher") as publisher,
                patch("sys.stderr", io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main()
            self.assertEqual(error.exception.code, 2)
            transport.assert_not_called()
            publisher.assert_not_called()

    def test_cli_resolves_existing_scope_after_recipient_configuration_changes(self):
        self.dispatch(transport=Mock(side_effect=TimeoutError("unknown")))
        for change in ("disabled", "removed", "address"):
            for resolution in ("sent", "cancelled"):
                with (
                    self.subTest(change=change, resolution=resolution),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    (root / "data").mkdir()
                    state_path = root / "data/notification-state.json"
                    state_path.write_text(json.dumps(self.state))
                    base = [
                        "release_probe.py",
                        "--source",
                        str(root),
                        "--repository",
                        "example/repository",
                        "--recipient-test",
                        "second",
                        "--publish",
                        "--date",
                        DAY,
                    ]
                    config = self.changed_recipient_config(change)
                    with (
                        patch(
                            "sys.argv",
                            [
                                *base,
                                "--resolve",
                                resolution,
                                "--note",
                                "Verified mailbox/server evidence for this saved Message-ID",
                            ],
                        ),
                        patch("scripts.release_probe.settings", return_value=config),
                        patch("scripts.release_probe.Publisher") as publisher,
                        patch("scripts.release_probe.SMTPTransport") as transport,
                        redirect_stdout(io.StringIO()),
                    ):
                        self.assertEqual(main(), 0)
                        publisher.return_value.assert_called_once_with(
                            ["data/notification-state.json"]
                        )
                        transport.assert_not_called()
                    saved = json.loads(state_path.read_text())
                    record = saved["release_probes"][self.scope]
                    self.assertEqual(record["status"], resolution)
                    self.assertEqual(record["recipient"]["email"], "second@example.org")
                    self.assertEqual(
                        record["resolutions"][-1]["prior"]["status"], "uncertain"
                    )
                    self.assertEqual(
                        saved["release_probes"][PROBE_ID],
                        self.original["release_probes"][PROBE_ID],
                    )
                    before = state_path.read_bytes()
                    with (
                        patch("sys.argv", [*base, "--send"]),
                        patch("scripts.release_probe.settings", return_value=config),
                        patch("scripts.release_probe.Publisher") as publisher,
                        patch("scripts.release_probe.SMTPTransport") as transport,
                        patch.dict("os.environ", ENV),
                        redirect_stdout(io.StringIO()),
                    ):
                        self.assertEqual(main(), 0)
                        transport.assert_not_called()
                        publisher.return_value.assert_not_called()
                    self.assertEqual(state_path.read_bytes(), before)

    def test_cli_evidence_retry_cannot_bypass_recipient_send_checks(self):
        self.dispatch(transport=Mock(side_effect=TimeoutError("unknown")))
        for change in ("disabled", "removed", "address"):
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                (root / "data").mkdir()
                state_path = root / "data/notification-state.json"
                state_path.write_text(json.dumps(self.state))
                base = [
                    "release_probe.py",
                    "--source",
                    str(root),
                    "--repository",
                    "example/repository",
                    "--recipient-test",
                    "second",
                    "--publish",
                    "--date",
                    DAY,
                ]
                config = self.changed_recipient_config(change)
                with (
                    patch(
                        "sys.argv",
                        [
                            *base,
                            "--resolve",
                            "retry",
                            "--note",
                            "Server evidence proves no message acceptance",
                        ],
                    ),
                    patch("scripts.release_probe.settings", return_value=config),
                    patch("scripts.release_probe.Publisher") as publisher,
                    patch("scripts.release_probe.SMTPTransport") as transport,
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(main(), 0)
                    publisher.return_value.assert_called_once_with(
                        ["data/notification-state.json"]
                    )
                    transport.assert_not_called()
                before = state_path.read_bytes()
                with (
                    patch("sys.argv", [*base, "--send"]),
                    patch("scripts.release_probe.settings", return_value=config),
                    patch("scripts.release_probe.Publisher") as publisher,
                    patch("scripts.release_probe.SMTPTransport") as transport,
                    patch.dict("os.environ", ENV),
                    redirect_stdout(io.StringIO()),
                ):
                    if change == "address":
                        self.assertEqual(main(), 1)
                    else:
                        with self.assertRaisesRegex(
                            ValueError, "enabled configured recipient"
                        ):
                            main()
                    transport.assert_not_called()
                    publisher.return_value.assert_not_called()
                self.assertEqual(state_path.read_bytes(), before)

    def test_cli_new_probe_still_requires_an_enabled_configured_recipient(self):
        for change in ("disabled", "removed"):
            for action in ([], ["--send", "--publish"]):
                with (
                    self.subTest(change=change, action=action),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    (root / "data").mkdir()
                    state_path = root / "data/notification-state.json"
                    state_path.write_text(json.dumps(self.original))
                    before = state_path.read_bytes()
                    with (
                        patch(
                            "sys.argv",
                            [
                                "release_probe.py",
                                "--source",
                                str(root),
                                "--repository",
                                "example/repository",
                                "--recipient-test",
                                "second",
                                *action,
                            ],
                        ),
                        patch(
                            "scripts.release_probe.settings",
                            return_value=self.changed_recipient_config(change),
                        ),
                        patch("scripts.release_probe.Publisher") as publisher,
                        patch("scripts.release_probe.SMTPTransport") as transport,
                        patch.dict("os.environ", ENV),
                        self.assertRaisesRegex(
                            ValueError, "enabled configured recipient"
                        ),
                    ):
                        main()
                    transport.assert_not_called()
                    publisher.return_value.assert_not_called()
                    self.assertEqual(state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
