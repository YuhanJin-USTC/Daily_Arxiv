"""Durable per-recipient queue with conservative SMTP uncertainty handling."""

import copy
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import hashlib
import json
import os
import smtplib
import ssl
from urllib.parse import urlparse

from .history import paper_id
from .researchers import config_digest, match_paper


class DeliveryFailure(Exception):
    """The server did not accept this message."""


class DeliveryUncertain(Exception):
    """The server may have accepted this message."""


def new_state(historical_ids=()):
    return {
        "schema_version": 1,
        "historical_ids": sorted({paper_id(value) for value in historical_ids}),
        "discoveries": {},
        "deliveries": {},
        "batches": {},
        "resolutions": [],
    }


def validate_state(state):
    if state.get("schema_version") != 1:
        raise ValueError("Unsupported notification state")
    if not all(
        key in state
        for key in (
            "historical_ids",
            "discoveries",
            "deliveries",
            "batches",
            "resolutions",
        )
    ):
        raise ValueError(
            "Incomplete notification state; refusing to reset deduplication"
        )
    for recipient, deliveries in state["deliveries"].items():
        for identifier, item in deliveries.items():
            if (
                identifier != paper_id(identifier)
                or identifier not in state["discoveries"]
            ):
                raise ValueError("Notification identity is inconsistent")
            if item["status"] not in (
                "pending",
                "sending",
                "sent",
                "failed",
                "uncertain",
                "cancelled",
            ):
                raise ValueError("Unknown notification delivery status")
            if item["recipient"]["id"] != recipient:
                raise ValueError("Notification recipient is inconsistent")
    return state


def enqueue_discoveries(state, rows, day, config, historical_ids=()):
    """Capture eligibility once, including papers without a reliable match."""
    state = copy.deepcopy(validate_state(state))
    date.fromisoformat(day)
    historical = set(state["historical_ids"]) | {
        paper_id(value) for value in historical_ids
    }
    if historical.intersection(state["discoveries"]):
        raise ValueError("A discovered paper cannot become migration history")
    state["historical_ids"] = sorted(historical)
    researchers = config.get("researchers", [])
    recipients = [
        {"id": item["id"], "email": item["email"]}
        for item in config.get("notifications", {}).get("recipients", [])
        if item.get("enabled", True)
    ]
    for row in rows:
        identifier = paper_id(row["id"])
        if identifier in historical or identifier in state["discoveries"]:
            continue
        for field in ("title", "summary", "authors", "categories", "abs", "pdf"):
            if not row.get(field):
                raise ValueError("Cannot queue incomplete raw metadata: " + identifier)
        if not isinstance(row["authors"], list) or not all(
            isinstance(name, str) and name.strip() for name in row["authors"]
        ):
            raise ValueError("Cannot queue malformed author metadata")
        matches = match_paper(row, researchers, config["categories"])
        reliable = [item for item in matches if item["kind"] == "reliable"]
        state["discoveries"][identifier] = {
            "date": day,
            "paper": {
                key: copy.deepcopy(row[key])
                for key in ("id", "title", "authors", "summary", "categories")
            },
            "matches": matches,
            "config_digest": config_digest(researchers, config["categories"]),
            "recipients": copy.deepcopy(recipients),
        }
        if reliable:
            for recipient in recipients:
                state["deliveries"].setdefault(recipient["id"], {})[identifier] = {
                    "status": "pending",
                    "recipient": copy.deepcopy(recipient),
                    "attempts": 0,
                    "batch_id": None,
                    "last_error": None,
                }
    return state


def _enabled_recipient(config, recipient):
    return any(
        item["id"] == recipient["id"]
        and item["email"] == recipient["email"]
        and item.get("enabled", True)
        for item in config["notifications"].get("recipients", [])
    )


def _identifier(recipient, identifiers, day):
    value = json.dumps([recipient, sorted(identifiers), day], separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def render_message(state, recipient_id, identifiers, day, site_url, sender):
    """Plain text prevents author/title HTML from becoming markup."""
    deliveries = state["deliveries"][recipient_id]
    recipients = {
        deliveries[identifier]["recipient"]["email"] for identifier in identifiers
    }
    if len(recipients) != 1:
        raise ValueError("A digest cannot mix recipient addresses")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipients.pop()
    message["Subject"] = (
        f"Daily Arxiv researcher matches — {day} ({len(identifiers)} papers)"
    )
    message["Date"] = format_datetime(
        datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    )
    hostname = urlparse(site_url).hostname or "daily-arxiv.local"
    message["Message-ID"] = (
        f"<daily-arxiv-{_identifier(recipient_id, identifiers, day)}@{hostname}>"
    )
    text = [
        f"New papers by researchers you follow ({day})",
        "",
        "These matches use confirmed names or aliases. Names alone cannot establish identity.",
        "AI interpretations may still be pending.",
        "",
    ]
    for number, identifier in enumerate(identifiers, 1):
        discovery = state["discoveries"][identifier]
        row = discovery["paper"]
        names = list(
            dict.fromkeys(
                item["display_name"]
                for item in discovery["matches"]
                if item["kind"] == "reliable"
            )
        )
        text.extend(
            [
                f"{number}. {row['title']}",
                "Authors: " + "; ".join(row["authors"]),
                "Matched researchers: " + ", ".join(names),
                "arXiv: https://arxiv.org/abs/" + identifier,
                "Site: " + site_url,
                "",
            ]
        )
    message.set_content("\n".join(text))
    return message


def preview_messages(state, config, day=None):
    validate_state(state)
    day = day or date.today().isoformat()
    mail = config["notifications"]
    previews = {}
    for recipient_id, deliveries in state["deliveries"].items():
        identifiers = [
            identifier
            for identifier, item in deliveries.items()
            if item["status"] in ("pending", "failed")
            and _enabled_recipient(config, item["recipient"])
        ]
        if identifiers:
            previews[recipient_id] = render_message(
                state,
                recipient_id,
                identifiers,
                day,
                mail["site_url"],
                mail["smtp"]["sender"],
            )
    return previews


def recover_inflight(state):
    changed = False
    for deliveries in state["deliveries"].values():
        for item in deliveries.values():
            if item["status"] == "sending":
                item["status"] = "uncertain"
                item["last_error"] = "interrupted_after_durable_sending_state"
                changed = True
    return changed


class SMTPTransport:
    def __init__(self, config, environment=None):
        self.config = config
        environment = os.environ if environment is None else environment
        self.username = environment.get(config["username_env"], "")
        self.password = environment.get(config["password_env"], "")
        if not self.username or not self.password:
            raise ValueError("SMTP credentials are missing; values suppressed")
        if config["security"] not in ("ssl", "starttls"):
            raise ValueError("SMTP requires SSL or STARTTLS")

    def __call__(self, message):
        client = None
        try:
            context = ssl.create_default_context()
            if self.config["security"] == "ssl":
                client = smtplib.SMTP_SSL(
                    self.config["host"],
                    self.config["port"],
                    timeout=self.config.get("timeout", 30),
                    context=context,
                )
            else:
                client = smtplib.SMTP(
                    self.config["host"],
                    self.config["port"],
                    timeout=self.config.get("timeout", 30),
                )
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            client.login(self.username, self.password)
        except Exception as error:
            if client is not None:
                client.close()
            raise DeliveryFailure("smtp_connection_or_authentication_failed") from error
        try:
            refused = client.send_message(message)
            if refused:
                raise DeliveryFailure("smtp_recipient_refused")
        except (
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
            smtplib.SMTPDataError,
            smtplib.SMTPNotSupportedError,
        ) as error:
            raise DeliveryFailure("smtp_explicit_rejection") from error
        except DeliveryFailure:
            raise
        except Exception as error:
            raise DeliveryUncertain("smtp_acceptance_unknown") from error
        finally:
            try:
                client.quit()
            except Exception:
                client.close()


def dispatch(state, config, persist, transport=None, environment=None, day=None):
    """persist must durably publish each state before this function can send."""
    validate_state(state)
    environment = os.environ if environment is None else environment
    day = day or date.today().isoformat()
    date.fromisoformat(day)
    report = {"sent": 0, "failed": 0, "uncertain": 0, "errors": [], "blocked": []}
    mail = config["notifications"]
    if not mail.get("enabled", False) or environment.get("ALLOW_SMTP_SEND") != "1":
        report["blocked"].append("sending_disabled")
        return report
    if not callable(persist):
        raise ValueError("A durable persistence callback is required before SMTP")
    if transport is None:
        transport = SMTPTransport(mail["smtp"], environment)
    maximum = mail["smtp"].get("max_attempts", 3)
    if not isinstance(maximum, int) or maximum < 1:
        raise ValueError("SMTP max_attempts must be positive")
    if recover_inflight(state):
        try:
            persist(copy.deepcopy(state))
        except Exception:
            report["errors"].append("uncertain_state_persistence_failed")
            return report
    for recipient_id, deliveries in state["deliveries"].items():
        if any(item["status"] == "uncertain" for item in deliveries.values()):
            report["blocked"].append("manual_resolution_required:" + recipient_id)
        if any(
            item["status"] == "failed" and item["attempts"] >= maximum
            for item in deliveries.values()
        ):
            report["blocked"].append("retry_limit_reached:" + recipient_id)
        if any(
            batch["recipient_id"] == recipient_id and batch.get("sent_date") == day
            for batch in state["batches"].values()
        ):
            continue
        eligible = [
            identifier
            for identifier, item in deliveries.items()
            if item["status"] in ("pending", "failed")
            and item["attempts"] < maximum
            and _enabled_recipient(config, item["recipient"])
        ]
        blocked = [
            identifier
            for identifier, item in deliveries.items()
            if item["status"] in ("pending", "failed")
            and not _enabled_recipient(config, item["recipient"])
        ]
        if blocked:
            report["blocked"].append(
                "recipient_disabled_or_address_changed:" + recipient_id
            )
        if not eligible:
            continue
        retry = next(
            (
                deliveries[identifier]["batch_id"]
                for identifier in eligible
                if deliveries[identifier]["batch_id"]
            ),
            None,
        )
        if retry:
            batch = state["batches"][retry]
            identifiers = batch["paper_ids"]
            if any(identifier not in eligible for identifier in identifiers):
                report["blocked"].append("batch_requires_manual_resolution:" + retry)
                continue
            batch_id = retry
        else:
            identifiers = [
                identifier
                for identifier in eligible
                if deliveries[identifier]["batch_id"] is None
            ]
            batch_id = _identifier(recipient_id, identifiers, day)
            batch = {
                "recipient_id": recipient_id,
                "paper_ids": identifiers,
                "date": day,
                "site_url": mail["site_url"],
                "sender": mail["smtp"]["sender"],
            }
            state["batches"][batch_id] = batch
        message = render_message(
            state,
            recipient_id,
            identifiers,
            batch["date"],
            batch["site_url"],
            batch["sender"],
        )
        for identifier in identifiers:
            item = deliveries[identifier]
            item.update(status="sending", batch_id=batch_id, last_error=None)
            item["attempts"] += 1
        try:
            persist(copy.deepcopy(state))
        except Exception:
            # A remote push may have succeeded before its response was lost.
            report["errors"].append("pre_send_persistence_failed")
            return report
        status, failure = "sent", None
        try:
            transport(message)
        except DeliveryFailure:
            status, failure = "failed", "smtp_explicit_failure"
        except Exception:
            status, failure = "uncertain", "smtp_acceptance_unknown"
        for identifier in identifiers:
            deliveries[identifier].update(status=status, last_error=failure)
        if status == "sent":
            batch["sent_date"] = day
        try:
            persist(copy.deepcopy(state))
        except Exception:
            if status == "sent":
                batch.pop("sent_date", None)
            for identifier in identifiers:
                deliveries[identifier].update(
                    status="uncertain", last_error="post_send_persistence_failed"
                )
            report["uncertain"] += 1
            report["errors"].append("post_send_persistence_failed")
            try:
                persist(copy.deepcopy(state))
            except Exception:
                report["errors"].append("uncertain_state_persistence_failed")
            return report
        report[status] += 1
    return report


def resolve(state, recipient_id, identifier, resolution, note, day=None):
    """Record explicit cancellation or verified delivery evidence."""
    validate_state(state)
    if resolution not in ("sent", "retry", "cancelled") or not note.strip():
        raise ValueError("Resolution and an operator evidence note are required")
    identifier = paper_id(identifier)
    deliveries = state["deliveries"][recipient_id]
    item = deliveries[identifier]
    allowed = {"uncertain", "sending", "failed"}
    if resolution == "cancelled":
        allowed.add("pending")
    if item["status"] not in allowed:
        raise ValueError(
            "Pending deliveries may only be cancelled; other resolutions require failed or uncertain delivery"
        )
    batch_id = item["batch_id"]
    identifiers = state["batches"][batch_id]["paper_ids"] if batch_id else [identifier]
    for value in identifiers:
        if deliveries[value]["status"] not in allowed:
            raise ValueError("Resolve the complete digest consistently")
    day = day or date.today().isoformat()
    state["resolutions"].append(
        {
            "recipient_id": recipient_id,
            "paper_ids": list(identifiers),
            "resolution": resolution,
            "note": note,
            "date": day,
            "prior": {value: copy.deepcopy(deliveries[value]) for value in identifiers},
        }
    )
    for value in identifiers:
        deliveries[value].update(
            status="pending" if resolution == "retry" else resolution, last_error=None
        )
        if resolution == "retry":
            deliveries[value]["attempts"] = 0
    if resolution == "sent" and batch_id:
        state["batches"][batch_id]["sent_date"] = day
    return state
