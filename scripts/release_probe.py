"""Preview or send scoped English infrastructure tests, without paper notices."""

import argparse
import copy
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.config import settings
from ai.public_config import STABLE_ID
from ai.storage import write_json
from daily_arxiv.notifications import (
    DeliveryFailure,
    SMTPTransport,
    set_email_content,
    validate_state,
)
from scripts.publish_data import Publisher

PROBE_ID = "initial-release-v1"
RECIPIENT_TEST_PREFIX = "recipient-layout-v1:"
QUEUE = "data/notification-state.json"


def probe_scope(recipient_test=None, recipient_id=None):
    if recipient_test is None:
        return PROBE_ID
    if recipient_id is not None:
        raise ValueError("Recipient selectors cannot be combined")
    if not isinstance(recipient_test, str) or not STABLE_ID.fullmatch(recipient_test):
        raise ValueError("Recipient test requires a configured stable recipient ID")
    return RECIPIENT_TEST_PREFIX + recipient_test


def selected_recipient(config, identifier=None):
    recipients = config["notifications"]["recipients"]
    matches = [
        item
        for item in recipients
        if item.get("enabled", True)
        and (identifier is None or item["id"] == identifier)
    ]
    if not matches:
        raise ValueError("Release probe requires one enabled configured recipient")
    return {key: matches[0][key] for key in ("id", "email")}


def probe_record(config, recipient_id, day, *, recipient_test=None):
    scope = probe_scope(recipient_test, recipient_id)
    recipient = selected_recipient(config, recipient_test or recipient_id)
    site = config["notifications"]["site_url"]
    token = hashlib.sha256(
        json.dumps([scope, recipient, site], sort_keys=True).encode()
    ).hexdigest()[:32]
    return {
        "probe_id": scope,
        "recipient": recipient,
        "date": day,
        "site_url": site,
        "sender": config["notifications"]["smtp"]["sender"],
        "message_id": f"<daily-arxiv-release-{token}@{urlsplit(site).hostname}>",
        "status": "pending",
        "attempts": 0,
        "last_error": None,
        "resolutions": [],
    }


def validate_probe(record, expected_scope=None):
    if not isinstance(record, dict) or record.get("status") not in (
        "pending",
        "sending",
        "sent",
        "failed",
        "uncertain",
        "cancelled",
    ):
        raise ValueError(
            "Invalid release probe state; refusing to reset delivery history"
        )
    if (
        type(record.get("attempts")) is not int
        or record["attempts"] < 0
        or not isinstance(record.get("resolutions"), list)
    ):
        raise ValueError("Invalid release probe attempt history")
    date.fromisoformat(record["date"])
    for field in ("site_url", "sender", "message_id"):
        if (
            not isinstance(record.get(field), str)
            or not record[field]
            or "\n" in record[field]
            or "\r" in record[field]
        ):
            raise ValueError("Invalid release probe message metadata")
    recipient = record.get("recipient", {})
    if (
        not isinstance(recipient, dict)
        or not recipient.get("id")
        or not recipient.get("email")
    ):
        raise ValueError("Invalid release probe recipient")
    if record.get("probe_id") not in (PROBE_ID, probe_scope(recipient["id"])) or (
        expected_scope is not None and record["probe_id"] != expected_scope
    ):
        raise ValueError("Probe identity does not match its saved recipient scope")
    return record


def message_for(record):
    validate_probe(record)
    message = EmailMessage()
    message["From"] = record["sender"]
    message["To"] = record["recipient"]["email"]
    recipient_test = record["probe_id"] != PROBE_ID
    message["Subject"] = (
        "Daily Arxiv font and inbox test"
        if recipient_test
        else "Daily Arxiv SMTP release verification"
    )
    message["Date"] = format_datetime(
        datetime.fromisoformat(record["date"]).replace(tzinfo=timezone.utc)
    )
    message["Message-ID"] = record["message_id"]
    text = (
        "This is the one-time English delivery test for the bilingual Daily Arxiv site.\n\n"
        "This message tests SMTP delivery only. It is not a paper digest, and no historical paper notification is being sent.\n\n"
        "Site: " + record["site_url"] + "\n"
        "Probe ID: " + PROBE_ID + "\n\n"
        "The sending state was saved before SMTP. Please retain this message as delivery evidence.\n"
    )
    if recipient_test:
        text = (
            "This is a one-time font and inbox delivery test for the bilingual Daily Arxiv site.\n\n"
            "This is not a paper digest. No historical paper notifications are being sent.\n\n"
            "The HTML version requests Times New Roman, with Times and serif fallbacks when the font is unavailable.\n\n"
            "Site: " + record["site_url"] + "\n"
            "Test ID: " + record["probe_id"] + "\n\n"
            "The sending state was saved before SMTP. Please retain this message as delivery evidence.\n"
        )
    set_email_content(message, text, [record["site_url"]])
    return message


def preview(state, config, recipient_id=None, day=None, *, recipient_test=None):
    validate_state(state)
    scope = probe_scope(recipient_test, recipient_id)
    records = state.get("release_probes", {})
    if not isinstance(records, dict):
        raise ValueError("Invalid release probe history")
    record = (
        records[scope]
        if scope in records
        else probe_record(
            config,
            recipient_id,
            day or date.today().isoformat(),
            recipient_test=recipient_test,
        )
    )
    validate_probe(record, scope)
    return message_for(record)


def dispatch_probe(
    state,
    config,
    persist,
    recipient_id=None,
    transport=None,
    environment=None,
    day=None,
    *,
    recipient_test=None,
):
    validate_state(state)
    scope = probe_scope(recipient_test, recipient_id)
    day = day or date.today().isoformat()
    date.fromisoformat(day)
    environment = os.environ if environment is None else environment
    report = {
        "probe_id": scope,
        "sent": 0,
        "failed": 0,
        "uncertain": 0,
        "errors": [],
        "blocked": [],
    }
    mail = config["notifications"]
    if not mail.get("enabled", False) or environment.get("ALLOW_SMTP_SEND") != "1":
        report["blocked"].append("sending_disabled")
        return report
    if not callable(persist):
        raise ValueError("A durable publication callback is required before SMTP")
    records = state.get("release_probes", {})
    if not isinstance(records, dict):
        raise ValueError("Invalid release probe history")
    record = records.get(scope)
    if scope in records:
        validate_probe(record, scope)
        if record["status"] in ("sent", "cancelled"):
            report["status"] = record["status"]
            return report
        if record["status"] == "sending":
            record.update(
                status="uncertain", last_error="interrupted_after_durable_sending_state"
            )
            try:
                persist(copy.deepcopy(state))
            except Exception:
                report["errors"].append("uncertain_state_persistence_failed")
        if record["status"] == "uncertain":
            report["uncertain"] = 1
            report["blocked"].append("manual_resolution_required")
            return report
        configured = selected_recipient(
            config, recipient_test or recipient_id or record["recipient"]["id"]
        )
        if configured != record["recipient"]:
            report["blocked"].append("recipient_changed")
            return report
        if record["sender"] != mail["smtp"]["sender"]:
            report["blocked"].append("sender_changed")
            return report
    else:
        record = probe_record(config, recipient_id, day, recipient_test=recipient_test)
    maximum = mail["smtp"]["max_attempts"]
    if record["attempts"] >= maximum:
        report["blocked"].append("retry_limit_reached")
        return report
    if transport is None:
        transport = SMTPTransport(mail["smtp"], environment)
    message = message_for(record)
    state.setdefault("release_probes", {})[scope] = record
    record.update(status="sending", last_error=None)
    record["attempts"] += 1
    try:
        persist(copy.deepcopy(state))
    except Exception:
        report["errors"].append("pre_send_persistence_failed")
        return report
    status, failure, diagnostic = "sent", None, None
    try:
        transport(message)
    except DeliveryFailure as error:
        status, failure = "failed", error.code
        diagnostic = error.diagnostic
    except Exception:
        status, failure = "uncertain", "smtp_acceptance_unknown"
    record.update(status=status, last_error=failure)
    record.pop("last_diagnostic", None)
    if diagnostic:
        record["last_diagnostic"] = copy.deepcopy(diagnostic)
        report["diagnostic"] = copy.deepcopy(diagnostic)
    if status == "sent":
        record["sent_date"] = day
    try:
        persist(copy.deepcopy(state))
    except Exception:
        record.pop("sent_date", None)
        record.update(status="uncertain", last_error="post_send_persistence_failed")
        report["uncertain"] = 1
        report["errors"].append("post_send_persistence_failed")
        try:
            persist(copy.deepcopy(state))
        except Exception:
            report["errors"].append("uncertain_state_persistence_failed")
        return report
    report[status] = 1
    report["status"] = status
    return report


def resolve_probe(state, resolution, note, day=None, *, recipient_test=None):
    validate_state(state)
    scope = probe_scope(recipient_test)
    if resolution not in ("sent", "retry", "cancelled") or not note.strip():
        raise ValueError("Resolution requires an operator evidence note")
    record = validate_probe(state["release_probes"][scope], scope)
    allowed = {"uncertain", "sending", "failed"}
    if resolution == "cancelled":
        allowed.add("pending")
    if record["status"] not in allowed:
        raise ValueError(
            "Only failed or uncertain delivery may be retried or confirmed"
        )
    day = day or date.today().isoformat()
    date.fromisoformat(day)
    prior = {
        key: copy.deepcopy(value)
        for key, value in record.items()
        if key != "resolutions"
    }
    record["resolutions"].append(
        {"date": day, "resolution": resolution, "note": note, "prior": prior}
    )
    record.update(
        status="pending" if resolution == "retry" else resolution, last_error=None
    )
    if resolution == "retry":
        record["attempts"] = 0
    if resolution == "sent":
        record["sent_date"] = day
    return state


def rebind_sender(state, config, note, day=None, *, recipient_test=None):
    validate_state(state)
    scope = probe_scope(recipient_test)
    if not note.strip():
        raise ValueError("Sender change requires an operator evidence note")
    record = validate_probe(state["release_probes"][scope], scope)
    if record["status"] != "failed":
        raise ValueError("Only definitively failed probes may change sender")
    sender = config["notifications"]["smtp"]["sender"]
    if record["sender"] == sender:
        raise ValueError("Probe sender already matches configuration")
    day = day or date.today().isoformat()
    date.fromisoformat(day)
    prior = {
        key: copy.deepcopy(value)
        for key, value in record.items()
        if key != "resolutions"
    }
    record["resolutions"].append(
        {"date": day, "resolution": "sender_change", "note": note, "prior": prior}
    )
    record["sender"] = sender
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--recipient",
        help="Enabled recipient ID; default is the first enabled configured recipient",
    )
    selector.add_argument(
        "--recipient-test",
        help="One independent font/inbox test for this enabled configured recipient ID",
    )
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--publish", action="store_true")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--send", action="store_true")
    action.add_argument(
        "--check-auth",
        action="store_true",
        help="One SMTP authentication diagnostic; no message, publication or queue access",
    )
    action.add_argument("--resolve", choices=("sent", "retry", "cancelled"))
    action.add_argument(
        "--rebind-sender",
        action="store_true",
        help="Rebind a failed probe to the configured sender, retaining failed status, attempts and last error",
    )
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    config = settings()
    if args.check_auth:
        if (
            args.source
            or args.publish
            or args.recipient is not None
            or args.recipient_test is not None
            or args.note
        ):
            parser.error(
                "--check-auth does not accept source, publication, recipient or resolution options"
            )
        report = SMTPTransport(config["notifications"]["smtp"]).check_auth()
        print(json.dumps(report, indent=2))
        return int(not report["ok"])
    scope = probe_scope(args.recipient_test, args.recipient)
    if not args.source:
        parser.error("--source is required for preview, send or resolution")
    state_path = args.source / QUEUE
    state = validate_state(json.loads(state_path.read_text()))
    if args.note and not (args.resolve or args.rebind_sender):
        parser.error("--note requires --resolve or --rebind-sender")
    if not args.send and not args.resolve and not args.rebind_sender:
        if args.publish:
            parser.error("Preview does not publish state")
        print(
            preview(
                state,
                config,
                args.recipient,
                args.date.isoformat(),
                recipient_test=args.recipient_test,
            )
        )
        return 0
    if not args.publish:
        parser.error(
            "Sending, resolution or sender change requires --publish for durable state"
        )
    publisher = Publisher(args.source, args.repository)

    def persist(value):
        write_json(state_path, value)
        publisher([QUEUE])

    if args.rebind_sender:
        rebind_sender(
            state,
            config,
            args.note,
            args.date.isoformat(),
            recipient_test=args.recipient_test,
        )
        persist(state)
        print(json.dumps({"probe_id": scope, "resolution": "sender_change"}))
        return 0
    if args.resolve:
        resolve_probe(
            state,
            args.resolve,
            args.note,
            args.date.isoformat(),
            recipient_test=args.recipient_test,
        )
        persist(state)
        print(json.dumps({"probe_id": scope, "resolution": args.resolve}))
        return 0
    if os.environ.get("ALLOW_SMTP_SEND") != "1":
        parser.error("--send requires ALLOW_SMTP_SEND=1")
    report = dispatch_probe(
        state,
        config,
        persist,
        args.recipient,
        day=args.date.isoformat(),
        recipient_test=args.recipient_test,
    )
    print(json.dumps(report, indent=2))
    return int(
        bool(
            report["errors"]
            or report["blocked"]
            or report["failed"]
            or report["uncertain"]
        )
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            f"Release probe failed ({type(error).__name__}); credentials and server response suppressed.",
            file=sys.stderr,
        )
        raise SystemExit(1)
