import copy
from email.message import EmailMessage
from email.parser import BytesParser
from email import policy
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import smtplib
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daily_arxiv"))
from daily_arxiv.notifications import (
    DeliveryFailure,
    DeliveryUncertain,
    SMTPTransport,
    dispatch,
    enqueue_discoveries,
    new_state,
    preview_messages,
    resolve,
    set_email_content,
)
from ai.config import settings
from daily_arxiv.researchers import build_index
from test_researchers import CATEGORIES, RESEARCHERS, paper

DAY = "2026-10-21"
ENV = {
    "ALLOW_SMTP_SEND": "1",
    "SMTP_USERNAME": "fictional-user",
    "SMTP_PASSWORD": "fictional-client-password",
}


class HTMLAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def configuration():
    return {
        "researchers": copy.deepcopy(RESEARCHERS),
        "categories": CATEGORIES,
        "notifications": {
            "enabled": True,
            "site_url": "https://example.org/daily-arxiv/",
            "recipients": [
                {"id": "first", "email": "first@example.org", "enabled": True},
                {"id": "second", "email": "second@example.org", "enabled": True},
            ],
            "smtp": {
                "host": "mail.example.org",
                "port": 465,
                "security": "ssl",
                "sender": "sender@example.org",
                "username_env": "SMTP_USERNAME",
                "password_env": "SMTP_PASSWORD",
                "timeout": 30,
                "max_attempts": 2,
            },
        },
    }


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()
        self.saved = []
        self.sent = []

    def queue(self, rows=None, state=None, day=DAY):
        return enqueue_discoveries(
            state or new_state(), rows or [paper()], day, self.config
        )

    def dispatch(self, state, **kwargs):
        return dispatch(
            state,
            self.config,
            kwargs.pop("persist", self.saved.append),
            transport=kwargs.pop("transport", self.sent.append),
            environment=kwargs.pop("environment", ENV),
            day=kwargs.pop("day", DAY),
            **kwargs,
        )

    def test_no_reliable_matches_no_mail(self):
        for authors in (["Unknown Author"], ["A. Arefiev"]):
            state = self.queue([paper(authors=authors)])
            self.assertEqual(preview_messages(state, self.config, DAY), {})
            self.assertEqual(self.dispatch(state)["sent"], 0)
        self.assertEqual(self.sent, [])

    def test_configured_initials_never_enqueue_or_send_mail(self):
        config = settings()
        self.config["researchers"] = config["researchers"]
        self.config["categories"] = config["categories"]
        for researcher in config["researchers"]:
            for author in researcher["suspected_aliases"]:
                with self.subTest(author=author):
                    state = self.queue([paper(authors=[author])])
                    matches = state["discoveries"]["2610.12345"]["matches"]
                    self.assertTrue(matches)
                    self.assertTrue(
                        all(match["kind"] == "suspected" for match in matches)
                    )
                    self.assertEqual(state["deliveries"], {})
                    self.assertEqual(preview_messages(state, self.config, DAY), {})
                    self.assertEqual(self.dispatch(state)["sent"], 0)
        self.assertEqual(self.sent, [])

    def test_multiple_authors_and_recipients_one_paper_each(self):
        state = self.queue(
            [paper(authors=["Alexey Arefiev", "Jorge Vieira", '<Other & "Author">'])]
        )
        previews = preview_messages(state, self.config, DAY)
        self.assertEqual(len(previews), 2)
        text = previews["first"].get_body(preferencelist=("plain",)).get_content()
        self.assertIn("Alexey Arefiev, Jorge Vieira", text)
        self.assertIn('<Other & "Author">', text)
        self.assertEqual(text.count("arXiv:"), 1)
        self.assertEqual(previews["first"].get_content_type(), "multipart/alternative")
        self.assertEqual(
            [part.get_content_type() for part in previews["first"].iter_parts()],
            ["text/plain", "text/html"],
        )
        self.assertEqual(self.dispatch(state)["sent"], 2)
        self.assertEqual(
            [str(message["To"]) for message in self.sent],
            ["first@example.org", "second@example.org"],
        )
        self.assertEqual(
            self.saved[0]["deliveries"]["first"]["2610.12345"]["status"], "sending"
        )

    def test_web_index_and_queue_share_identical_match_evidence(self):
        row = paper(authors=["Alexey Arefiev", "J. Vieira"])
        state = self.queue([row])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / f"{DAY}.jsonl").write_text(json.dumps(row) + "\n")
            index = build_index(
                path, self.config["researchers"], self.config["categories"]
            )
        self.assertEqual(
            index["papers"]["2610.12345"], state["discoveries"]["2610.12345"]["matches"]
        )
        self.assertEqual(
            index["config_digest"], state["discoveries"]["2610.12345"]["config_digest"]
        )
        self.assertNotIn(
            "Jorge Vieira",
            preview_messages(state, self.config, DAY)["first"]
            .get_body(preferencelist=("plain",))
            .get_content()
            .split("Matched researchers: ")[1],
        )

    def test_transport_only_runs_after_durable_sending_snapshot(self):
        state = self.queue()

        def transport(message):
            recipient = (
                "first" if str(message["To"]) == "first@example.org" else "second"
            )
            saved = self.saved[-1]["deliveries"][recipient]["2610.12345"]
            self.assertEqual(saved["status"], "sending")
            self.assertEqual(saved["attempts"], 1)
            self.sent.append(message)

        self.assertEqual(self.dispatch(state, transport=transport)["sent"], 2)

    def test_html_escapes_metadata_and_only_links_validated_urls(self):
        author = '<script>alert("author")</script> & Other'
        row = paper(authors=["Alexey Arefiev", author])
        row["title"] = (
            '<img src="https://tracker.example/pixel" onerror="alert(1)"> & "Study"'
        )
        self.config["researchers"][0]["display_name"] = '<Researcher & "Label">'
        self.config["researchers"][0]["aliases"].append("Alexey Arefiev")
        self.config["notifications"]["site_url"] = (
            'https://example.org/daily-arxiv/?q="<tag>"&x=1'
        )
        message = preview_messages(self.queue([row]), self.config, DAY)["first"]
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn(row["title"], plain)
        self.assertIn(author, plain)
        self.assertIn("font-family: 'Times New Roman', Times, serif", html)
        self.assertIn("&lt;img", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;Researcher &amp; &quot;Label&quot;&gt;", html)
        self.assertIn("&quot;&lt;tag&gt;&quot;&amp;x=1", html)
        audit = HTMLAudit()
        audit.feed(html)
        self.assertLessEqual(
            {tag for tag, _ in audit.elements}, {"html", "body", "div", "p", "br", "a"}
        )
        links = {attrs["href"] for tag, attrs in audit.elements if tag == "a"}
        self.assertEqual(
            links,
            {
                self.config["notifications"]["site_url"],
                "https://arxiv.org/abs/2610.12345",
            },
        )
        self.assertFalse(
            any(
                name.startswith("on") or name in ("src", "srcset")
                for _, attrs in audit.elements
                for name in attrs
            )
        )

    def test_multipart_preserves_original_plain_digest(self):
        message = preview_messages(self.queue(), self.config, DAY)["first"]
        expected = (
            "New papers by researchers you follow (2026-10-21)\n\n"
            "These matches use confirmed names or aliases. Names alone cannot establish identity.\n"
            "AI interpretations may still be pending.\n\n"
            "1. A <plasma> & photon study\n"
            "Authors: Alexey Arefiev\n"
            "Matched researchers: Alexey Arefiev\n"
            "arXiv: https://arxiv.org/abs/2610.12345\n"
            "Site: https://example.org/daily-arxiv/\n"
        )
        restored = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
        self.assertEqual(
            restored.get_body(preferencelist=("plain",)).get_content(), expected
        )
        self.assertIn(
            "Times New Roman", restored.get_body(preferencelist=("html",)).get_content()
        )

    def test_html_rejects_non_http_or_credentialed_links(self):
        for url in (
            "javascript:alert(1)",
            "data:text/html,<script>",
            "mailto:a@example.org",
            "//example.org/",
            "https://user:secret@example.org/",
            "https://example.org:bad/",
            "https://example.org/ path",
            "https://example.org/\x00",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                set_email_content(EmailMessage(), "Site: " + url, [url])

    def test_repeated_run_new_version_crosslist_and_ai_do_not_notify_twice(self):
        state = self.queue()
        self.dispatch(state)
        changed = paper("2610.12345v9")
        changed["AI"] = {"tldr": "A different language"}
        changed["categories"] = ["physics.optics", *CATEGORIES]
        state = self.queue([changed], state)
        self.dispatch(state, day="2026-10-22")
        self.assertEqual(len(self.sent), 2)

    def test_history_and_config_changes_never_backfill(self):
        baseline = new_state(["2610.11111v1"])
        state = self.queue(
            [paper("2610.11111"), paper(authors=["A. Arefiev"])], baseline
        )
        self.config["researchers"][0]["aliases"].append("A. Arefiev")
        self.config["notifications"]["recipients"].append(
            {"id": "new", "email": "new@example.org", "enabled": True}
        )
        state = self.queue([paper("2610.11111"), paper()], state)
        self.assertEqual(state["deliveries"], {})
        state = self.queue([paper("2610.22222")], state)
        self.config["notifications"]["recipients"].append(
            {"id": "later", "email": "later@example.org", "enabled": True}
        )
        state = self.queue([paper("2610.22222")], state)
        self.assertNotIn("later", state["deliveries"])
        self.assertEqual(len(state["discoveries"]["2610.12345"]["recipients"]), 2)

    def test_new_recipient_only_receives_future_reliable_discoveries(self):
        historical = paper("2610.11111", authors=["John Patrick Palastro"])
        unmatched = paper("2610.22222", authors=["John Patrick Palastro"])
        state = self.queue(
            [historical, paper(), unmatched], new_state([historical["id"]])
        )
        frozen = copy.deepcopy(state)
        config = settings()
        recipient = next(
            item
            for item in config["notifications"]["recipients"]
            if item["id"] == "xiangtang"
        )
        self.config["researchers"] = config["researchers"]
        self.config["categories"] = config["categories"]
        self.config["notifications"]["recipients"].append(recipient)
        state = self.queue([historical, paper("2610.12345v3"), unmatched], state)
        self.assertEqual(state, frozen)

        day = "2026-10-22"
        future = paper("2610.33333", authors=["John Patrick Palastro"])
        state = self.queue([future], state, day)
        self.assertEqual(set(state["deliveries"]["xiangtang"]), {future["id"]})
        for identifier, discovery in frozen["discoveries"].items():
            self.assertEqual(state["discoveries"][identifier], discovery)
        self.assertEqual(self.dispatch(state, day=day)["sent"], 3)
        message = next(
            message for message in self.sent if str(message["To"]) == recipient["email"]
        )
        text = message.get_body(preferencelist=("plain",)).get_content()
        self.assertIn("John P. Palastro", text)
        self.assertIn(future["id"], text)
        for identifier in (historical["id"], unmatched["id"], "2610.12345"):
            self.assertNotIn(identifier, text)

    def test_no_new_papers_retries_explicit_failure_with_limit(self):
        state = self.queue()
        transport = MagicMock(
            side_effect=DeliveryFailure("do not expose server output")
        )
        self.assertEqual(self.dispatch(state, transport=transport)["failed"], 2)
        state = enqueue_discoveries(state, [], "2026-10-22", self.config)
        self.assertEqual(
            self.dispatch(state, transport=transport, day="2026-10-22")["failed"], 2
        )
        self.assertEqual(
            self.dispatch(state, transport=transport, day="2026-10-23")["failed"], 0
        )
        self.assertEqual(transport.call_count, 4)
        self.assertEqual(state["deliveries"]["first"]["2610.12345"]["attempts"], 2)
        self.assertNotIn("do not expose", json.dumps(state))

    def test_ambiguous_delivery_and_interrupted_sending_never_auto_retry(self):
        state = self.queue()
        self.assertEqual(
            self.dispatch(
                state,
                transport=MagicMock(side_effect=DeliveryUncertain("connection lost")),
            )["uncertain"],
            2,
        )
        self.assertEqual(self.dispatch(state, day="2026-10-22")["sent"], 0)
        self.assertEqual(self.sent, [])
        state["deliveries"]["first"]["2610.12345"]["status"] = "sending"
        self.dispatch(state, day="2026-10-23")
        self.assertEqual(
            state["deliveries"]["first"]["2610.12345"]["status"], "uncertain"
        )
        self.assertEqual(self.sent, [])

    def test_pre_send_persistence_failure_never_calls_transport(self):
        state = self.queue()
        result = self.dispatch(
            state, persist=MagicMock(side_effect=OSError("push failed"))
        )
        self.assertIn("pre_send_persistence_failed", result["errors"])
        self.assertEqual(self.sent, [])
        self.dispatch(state)
        self.assertEqual(
            state["deliveries"]["first"]["2610.12345"]["status"], "uncertain"
        )
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(str(self.sent[0]["To"]), "second@example.org")

    def test_post_send_persistence_failure_becomes_uncertain(self):
        state = self.queue()
        attempts = 0

        def persist(snapshot):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError("push failed after SMTP")
            self.saved.append(snapshot)

        result = self.dispatch(state, persist=persist)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(result["uncertain"], 1)
        self.assertEqual(
            state["deliveries"]["first"]["2610.12345"]["status"], "uncertain"
        )
        self.assertEqual(
            self.saved[-1]["deliveries"]["first"]["2610.12345"]["status"], "uncertain"
        )
        self.dispatch(state, day="2026-10-22")
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(str(self.sent[-1]["To"]), "second@example.org")

    def test_manual_resolution_requires_note_and_resolves_whole_digest(self):
        state = self.queue([paper(), paper("2610.22222")])
        self.dispatch(state, transport=MagicMock(side_effect=DeliveryUncertain()))
        with self.assertRaises(ValueError):
            resolve(state, "first", "2610.12345", "retry", "")
        resolve(
            state, "first", "2610.12345", "retry", "Server logs confirm rejection", DAY
        )
        resolve(
            state, "second", "2610.12345", "sent", "Recipient confirmed delivery", DAY
        )
        self.assertEqual(len(state["resolutions"]), 2)
        self.assertEqual(
            state["deliveries"]["first"]["2610.22222"]["status"], "pending"
        )
        self.assertEqual(self.dispatch(state)["sent"], 1)
        self.assertEqual(len(self.sent), 1)

    def test_one_successful_daily_digest_defers_later_arrivals(self):
        state = self.queue()
        self.dispatch(state)
        state = self.queue([paper("2610.22222")], state)
        self.assertEqual(self.dispatch(state)["sent"], 0)
        self.assertEqual(self.dispatch(state, day="2026-10-22")["sent"], 2)

    def test_disabled_and_changed_recipient_not_silently_retargeted(self):
        state = self.queue()
        self.config["notifications"]["recipients"][0]["email"] = "changed@example.org"
        self.config["notifications"]["recipients"][1]["enabled"] = False
        result = self.dispatch(state)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(len(result["blocked"]), 2)

    def test_pending_recipient_cancellation_preserves_evidence_without_retargeting(
        self,
    ):
        state = self.queue()
        self.config["notifications"]["recipients"][0]["enabled"] = False
        self.config["notifications"]["recipients"][1]["email"] = "changed@example.org"
        before = copy.deepcopy(state)
        for resolution in ("sent", "retry"):
            with self.assertRaises(ValueError):
                resolve(state, "first", "2610.12345", resolution, "Operator note", DAY)
        with self.assertRaises(ValueError):
            resolve(state, "first", "2610.12345", "cancelled", "", DAY)
        self.assertEqual(state, before)
        for recipient in ("first", "second"):
            resolve(
                state,
                recipient,
                "2610.12345",
                "cancelled",
                "Recipient changed; cancel prior pending delivery",
                DAY,
            )
            delivery = state["deliveries"][recipient]["2610.12345"]
            self.assertEqual(delivery["status"], "cancelled")
            self.assertEqual(delivery["attempts"], 0)
            self.assertEqual(
                delivery["recipient"],
                before["deliveries"][recipient]["2610.12345"]["recipient"],
            )
        self.assertEqual(self.dispatch(state)["blocked"], [])
        self.assertEqual(self.sent, [])
        self.assertEqual(
            state["resolutions"][0]["prior"]["2610.12345"]["status"], "pending"
        )

    def test_send_guards_and_missing_credentials_never_connect(self):
        state = self.queue()
        with patch("daily_arxiv.notifications.smtplib.SMTP_SSL") as connect:
            self.assertEqual(
                dispatch(state, self.config, self.saved.append, environment={})["sent"],
                0,
            )
            with self.assertRaises(ValueError):
                dispatch(
                    state,
                    self.config,
                    self.saved.append,
                    environment={"ALLOW_SMTP_SEND": "1"},
                )
            self.config["notifications"]["enabled"] = False
            self.assertEqual(self.dispatch(state)["sent"], 0)
            connect.assert_not_called()
        self.assertEqual(self.saved, [])

    def test_default_cli_only_creates_previews(self):
        state = enqueue_discoveries(new_state(), [paper()], DAY, settings())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            state_file = path / "state.json"
            state_file.write_text(json.dumps(state))
            before = state_file.read_bytes()
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/notify.py"),
                    "--state",
                    str(state_file),
                    "--preview-dir",
                    str(path / "preview"),
                    "--date",
                    DAY,
                ],
                cwd=ROOT,
                env={**os.environ, "ALLOW_SMTP_SEND": "1"},
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("no messages sent", result.stdout)
            self.assertEqual(state_file.read_bytes(), before)
            emails = list((path / "preview").glob("*.eml"))
            self.assertEqual(len(emails), len(state["deliveries"]))
            self.assertTrue(emails)
            for email in emails:
                message = BytesParser(policy=policy.default).parsebytes(
                    email.read_bytes()
                )
                self.assertEqual(message.get_content_type(), "multipart/alternative")
                self.assertEqual(
                    email.with_suffix(".txt").read_text(),
                    message.get_body(preferencelist=("plain",)).get_content(),
                )
                self.assertEqual(
                    email.with_suffix(".html").read_text(),
                    message.get_body(preferencelist=("html",)).get_content(),
                )

    def test_queue_requires_complete_raw_metadata(self):
        row = paper()
        del row["summary"]
        with self.assertRaises(ValueError):
            self.queue([row])


class SMTPTransportTests(unittest.TestCase):
    def message(self):
        config = configuration()
        state = enqueue_discoveries(new_state(), [paper()], DAY, config)
        return preview_messages(state, config, DAY)["first"]

    def test_ssl_auth_uses_explicit_environment_and_quit_failure_is_not_retry(self):
        config = configuration()["notifications"]["smtp"]
        with patch("daily_arxiv.notifications.smtplib.SMTP_SSL") as connect:
            client = connect.return_value
            client.send_message.return_value = {}
            client.quit.side_effect = OSError("quit response lost")
            SMTPTransport(config, ENV)(self.message())
            client.login.assert_called_once_with(
                "fictional-user", "fictional-client-password"
            )
            client.send_message.assert_called_once()

    def test_starttls_and_definite_rejection(self):
        config = configuration()["notifications"]["smtp"]
        config.update(security="starttls", port=587)
        with patch("daily_arxiv.notifications.smtplib.SMTP") as connect:
            client = connect.return_value
            client.send_message.side_effect = smtplib.SMTPDataError(550, b"rejected")
            with self.assertRaises(DeliveryFailure):
                SMTPTransport(config, ENV)(self.message())
            client.starttls.assert_called_once()
            self.assertEqual(client.ehlo.call_count, 2)

    def test_disconnect_before_send_is_definite_but_during_send_is_unknown(self):
        config = configuration()["notifications"]["smtp"]
        for stage, expected in (
            ("login", DeliveryFailure),
            ("send_message", DeliveryUncertain),
        ):
            with patch("daily_arxiv.notifications.smtplib.SMTP_SSL") as connect:
                getattr(
                    connect.return_value, stage
                ).side_effect = smtplib.SMTPServerDisconnected("lost")
                with self.assertRaises(expected):
                    SMTPTransport(config, ENV)(self.message())

    def test_connection_failures_are_precise_without_raw_response(self):
        config = configuration()["notifications"]["smtp"]
        for error, code in (
            (TimeoutError("hidden value"), "smtp_connect_timeout"),
            (socket.gaierror(-2, "hidden hostname"), "smtp_connect_dns_failed"),
            (
                ssl.SSLCertVerificationError(1, "hidden certificate"),
                "smtp_connect_tls_certificate_failed",
            ),
            (
                smtplib.SMTPConnectError(421, b"hidden response"),
                "smtp_connect_rejected",
            ),
        ):
            with (
                self.subTest(code=code),
                patch(
                    "daily_arxiv.notifications.smtplib.SMTP_SSL", side_effect=error
                ) as connect,
            ):
                result = SMTPTransport(config, ENV).check_auth()
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], code)
                self.assertEqual(result["stage"], "connect")
                self.assertEqual(result["exception_type"], type(error).__name__)
                self.assertNotIn("hidden", json.dumps(result))
                connect.assert_called_once()

    def test_auth_only_success_never_issues_envelope_or_data(self):
        config = configuration()["notifications"]["smtp"]
        with patch("daily_arxiv.notifications.smtplib.SMTP_SSL") as connect:
            client = connect.return_value
            client.esmtp_features = {"auth": "PLAIN LOGIN"}
            client.login.return_value = (235, b"hidden server response")
            result = SMTPTransport(config, ENV).check_auth()
            self.assertEqual(
                result,
                {
                    "ok": True,
                    "stage": "auth",
                    "code": "smtp_authenticated",
                    "smtp_code": 235,
                },
            )
            client.login.assert_called_once()
            client.quit.assert_called_once()
            for method in ("send_message", "sendmail", "mail", "rcpt", "data"):
                getattr(client, method).assert_not_called()
            self.assertEqual(client.esmtp_features["auth"], "PLAIN LOGIN")

    def test_auth_diagnostic_preserves_normal_login_negotiation_once(self):
        config = configuration()["notifications"]["smtp"]
        client = smtplib.SMTP()
        client.ehlo_resp = b"already greeted"
        client.esmtp_features = {"auth": "PLAIN LOGIN"}
        client.auth = Mock(
            side_effect=[
                smtplib.SMTPAuthenticationError(535, b"hidden response"),
                (235, b"hidden success"),
            ]
        )
        client.login = Mock(wraps=client.login)
        client.close = Mock()
        client.quit = Mock()
        with patch(
            "daily_arxiv.notifications.smtplib.SMTP_SSL", return_value=client
        ) as connect:
            result = SMTPTransport(config, ENV).check_auth()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "smtp_authenticated")
        self.assertEqual(result["smtp_code"], 235)
        connect.assert_called_once()
        client.login.assert_called_once_with(ENV["SMTP_USERNAME"], ENV["SMTP_PASSWORD"])
        self.assertEqual(
            [call.args[0] for call in client.auth.call_args_list], ["PLAIN", "LOGIN"]
        )
        self.assertEqual(client.esmtp_features["auth"], "PLAIN LOGIN")
        self.assertNotIn("hidden", json.dumps(result))

    def test_auth_and_tls_failure_stages_are_separate(self):
        for security, method, error, expected in (
            (
                "ssl",
                "login",
                smtplib.SMTPAuthenticationError(535, b"hidden"),
                "smtp_auth_rejected",
            ),
            (
                "ssl",
                "ehlo_or_helo_if_needed",
                smtplib.SMTPHeloError(550, b"hidden"),
                "smtp_ehlo_rejected",
            ),
            (
                "starttls",
                "starttls",
                smtplib.SMTPNotSupportedError("hidden"),
                "smtp_starttls_unsupported",
            ),
        ):
            config = configuration()["notifications"]["smtp"]
            config["security"] = security
            factory = "SMTP_SSL" if security == "ssl" else "SMTP"
            with patch("daily_arxiv.notifications.smtplib." + factory) as connect:
                getattr(connect.return_value, method).side_effect = error
                result = SMTPTransport(config, ENV).check_auth()
                self.assertEqual(result["code"], expected)
                self.assertNotIn("hidden", json.dumps(result))
                connect.return_value.send_message.assert_not_called()

    def test_legacy_failure_message_is_never_exposed(self):
        error = DeliveryFailure("password or arbitrary server response")
        self.assertEqual(str(error), "smtp_explicit_failure")
        self.assertEqual(error.diagnostic, {"code": "smtp_explicit_failure"})


if __name__ == "__main__":
    unittest.main()
