"""Preview or send one durable English SMTP release test, without paper notices."""

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
from ai.storage import write_json
from daily_arxiv.notifications import DeliveryFailure, SMTPTransport, validate_state
from scripts.publish_data import Publisher

PROBE_ID = "initial-release-v1"
QUEUE = "data/notification-state.json"


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


def probe_record(config, recipient_id, day):
    recipient = selected_recipient(config, recipient_id)
    site = config["notifications"]["site_url"]
    token = hashlib.sha256(
        json.dumps([PROBE_ID, recipient, site], sort_keys=True).encode()
    ).hexdigest()[:32]
    return {
        "probe_id": PROBE_ID,
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


def validate_probe(record):
    if (
        not isinstance(record, dict)
        or record.get("probe_id") != PROBE_ID
        or record.get("status")
        not in (
            "pending",
            "sending",
            "sent",
            "failed",
            "uncertain",
            "cancelled",
        )
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
    if not recipient.get("id") or not recipient.get("email"):
        raise ValueError("Invalid release probe recipient")
    return record


def message_for(record):
    validate_probe(record)
    message = EmailMessage()
    message["From"] = record["sender"]
    message["To"] = record["recipient"]["email"]
    message["Subject"] = "Daily Arxiv SMTP release verification"
    message["Date"] = format_datetime(
        datetime.fromisoformat(record["date"]).replace(tzinfo=timezone.utc)
    )
    message["Message-ID"] = record["message_id"]
    message.set_content(
        "This is the one-time English delivery test for the bilingual Daily Arxiv site.\n\n"
        "This message tests SMTP delivery only. It is not a paper digest, and no historical paper notification is being sent.\n\n"
        "Site: " + record["site_url"] + "\n"
        "Probe ID: " + PROBE_ID + "\n\n"
        "The sending state was saved before SMTP. Please retain this message as delivery evidence.\n"
    )
    return message


def preview(state, config, recipient_id=None, day=None):
    validate_state(state)
    records = state.get("release_probes", {})
    if not isinstance(records, dict):
        raise ValueError("Invalid release probe history")
    record = (
        records[PROBE_ID]
        if PROBE_ID in records
        else probe_record(config, recipient_id, day or date.today().isoformat())
    )
    return message_for(record)


def dispatch_probe(
    state,
    config,
    persist,
    recipient_id=None,
    transport=None,
    environment=None,
    day=None,
):
    validate_state(state)
    day = day or date.today().isoformat()
    date.fromisoformat(day)
    environment = os.environ if environment is None else environment
    report = {
        "probe_id": PROBE_ID,
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
    record = records.get(PROBE_ID)
    if PROBE_ID in records:
        validate_probe(record)
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
            config, recipient_id or record["recipient"]["id"]
        )
        if configured != record["recipient"]:
            report["blocked"].append("recipient_changed")
            return report
    else:
        record = probe_record(config, recipient_id, day)
    maximum = mail["smtp"]["max_attempts"]
    if record["attempts"] >= maximum:
        report["blocked"].append("retry_limit_reached")
        return report
    if transport is None:
        transport = SMTPTransport(mail["smtp"], environment)
    message = message_for(record)
    state.setdefault("release_probes", {})[PROBE_ID] = record
    record.update(status="sending", last_error=None)
    record["attempts"] += 1
    try:
        persist(copy.deepcopy(state))
    except Exception:
        report["errors"].append("pre_send_persistence_failed")
        return report
    status, failure = "sent", None
    try:
        transport(message)
    except DeliveryFailure:
        status, failure = "failed", "smtp_explicit_failure"
    except Exception:
        status, failure = "uncertain", "smtp_acceptance_unknown"
    record.update(status=status, last_error=failure)
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


def resolve_probe(state, resolution, note, day=None):
    validate_state(state)
    if resolution not in ("sent", "retry", "cancelled") or not note.strip():
        raise ValueError("Resolution requires an operator evidence note")
    record = validate_probe(state["release_probes"][PROBE_ID])
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument(
        "--recipient",
        help="Enabled recipient ID; default is the first enabled configured recipient",
    )
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--publish", action="store_true")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--send", action="store_true")
    action.add_argument("--resolve", choices=("sent", "retry", "cancelled"))
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    state_path = args.source / QUEUE
    state = validate_state(json.loads(state_path.read_text()))
    config = settings()
    if args.note and not args.resolve:
        parser.error("--note requires --resolve")
    if not args.send and not args.resolve:
        if args.publish:
            parser.error("Preview does not publish state")
        print(preview(state, config, args.recipient, args.date.isoformat()))
        return 0
    if not args.publish:
        parser.error("Sending or resolution requires --publish for durable state")
    publisher = Publisher(args.source, args.repository)

    def persist(value):
        write_json(state_path, value)
        publisher([QUEUE])

    if args.resolve:
        resolve_probe(state, args.resolve, args.note, args.date.isoformat())
        persist(state)
        print(json.dumps({"probe_id": PROBE_ID, "resolution": args.resolve}))
        return 0
    if os.environ.get("ALLOW_SMTP_SEND") != "1":
        parser.error("--send requires ALLOW_SMTP_SEND=1")
    report = dispatch_probe(
        state, config, persist, args.recipient, day=args.date.isoformat()
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
