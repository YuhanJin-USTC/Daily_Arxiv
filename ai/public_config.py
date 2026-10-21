"""Validate public researcher and mail settings without loading credentials."""

import re
from urllib.parse import urlsplit

STABLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
)
ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _text(value):
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _identities(values, kind):
    if not isinstance(values, list):
        raise ValueError(kind + " must be a list")
    seen = set()
    for item in values:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not STABLE_ID.fullmatch(item["id"])
        ):
            raise ValueError(
                kind
                + " requires a stable ID using letters, digits, hyphens or underscores"
            )
        if item["id"] in seen:
            raise ValueError("Duplicate " + kind + " ID")
        seen.add(item["id"])
        if not isinstance(item.get("enabled", True), bool):
            raise ValueError(kind + " enabled must be boolean")


def validate_public_config(config):
    researchers = config.get("researchers", [])
    _identities(researchers, "Researcher")
    for researcher in researchers:
        if not _text(researcher.get("display_name")):
            raise ValueError("Researcher display_name must be a nonempty name")
        for field in ("aliases", "suspected_aliases"):
            values = researcher.get(field, [])
            if not isinstance(values, list) or any(
                not _text(value) for value in values
            ):
                raise ValueError("Researcher aliases must be lists of nonempty names")
    mail = config.get("notifications")
    if not isinstance(mail, dict) or not isinstance(mail.get("enabled"), bool):
        raise ValueError("Notifications require a boolean enabled setting")
    url = mail.get("site_url", "")
    if not _text(url) or any(char.isspace() for char in url):
        raise ValueError("Notification site_url must be an absolute HTTP(S) URL")
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError as error:
        raise ValueError("Invalid notification site_url") from error
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "Notification site_url must be an absolute HTTP(S) URL without credentials"
        )
    recipients = mail.get("recipients", [])
    _identities(recipients, "Recipient")
    for recipient in recipients:
        if not isinstance(recipient.get("email"), str) or not EMAIL.fullmatch(
            recipient["email"]
        ):
            raise ValueError("Recipient email must be one plain mailbox address")
    smtp = mail.get("smtp")
    if not isinstance(smtp, dict):
        raise ValueError("Notifications require SMTP settings")
    allowed = {
        "host",
        "port",
        "security",
        "sender",
        "username_env",
        "password_env",
        "timeout",
        "max_attempts",
    }
    if set(smtp) - allowed:
        raise ValueError(
            "Unsupported SMTP settings; credentials must only use environment variables"
        )
    if not _text(smtp.get("host")) or not re.fullmatch(r"[A-Za-z0-9.-]+", smtp["host"]):
        raise ValueError("SMTP host must be a hostname")
    if type(smtp.get("port")) is not int or not 1 <= smtp["port"] <= 65535:
        raise ValueError("SMTP port must be between 1 and 65535")
    if smtp.get("security") not in ("ssl", "starttls"):
        raise ValueError("SMTP security must be ssl or starttls")
    if not isinstance(smtp.get("sender"), str) or not EMAIL.fullmatch(smtp["sender"]):
        raise ValueError("SMTP sender must be one plain mailbox address")
    for field in ("username_env", "password_env"):
        if not isinstance(smtp.get(field), str) or not ENVIRONMENT_NAME.fullmatch(
            smtp[field]
        ):
            raise ValueError("SMTP credential settings must name environment variables")
    if smtp["username_env"] == smtp["password_env"]:
        raise ValueError(
            "SMTP username and password must use separate environment variables"
        )
    for field in ("timeout", "max_attempts"):
        if type(smtp.get(field)) is not int or smtp[field] < 1:
            raise ValueError("SMTP timeout and max_attempts must be positive integers")
    return config
