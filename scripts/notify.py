"""Preview queued English mail, or explicitly dispatch with durable publishing."""

import argparse
from datetime import date
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "daily_arxiv"))
from ai.config import settings
from ai.storage import write_bytes, write_json
from daily_arxiv.notifications import (
    dispatch,
    preview_messages,
    resolve,
    validate_state,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--send", action="store_true")
    parser.add_argument(
        "--persist-command",
        help="Command that durably publishes the state; no shell expansion",
    )
    parser.add_argument("--resolve-recipient")
    parser.add_argument("--resolve-paper")
    parser.add_argument(
        "--resolution",
        choices=("sent", "retry", "cancelled"),
        help="Pending deliveries allow cancelled only; failed or uncertain batches require operator evidence",
    )
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    state = validate_state(json.loads(args.state.read_text(encoding="utf-8")))
    config = settings()
    if args.resolve_recipient:
        if args.send or not args.resolve_paper or not args.resolution:
            parser.error(
                "Resolution requires recipient, paper, resolution and note, without --send"
            )
        resolve(
            state,
            args.resolve_recipient,
            args.resolve_paper,
            args.resolution,
            args.note,
            args.date.isoformat(),
        )
        write_json(args.state, state)
        print("Resolution saved locally; publish this state before the next dispatch")
        return 0
    if args.resolve_paper or args.resolution or args.note:
        parser.error("Resolution requires --resolve-recipient")
    if args.send:
        if not args.persist_command:
            parser.error(
                "--send requires --persist-command to publish every state before SMTP"
            )
        command = shlex.split(args.persist_command)
        if not command:
            parser.error("The durable persistence command cannot be empty")

        def persist(value):
            write_json(args.state, value)
            subprocess.run(
                command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

        report = dispatch(state, config, persist, day=args.date.isoformat())
        print(json.dumps(report))
        return (
            1
            if report["errors"]
            or report["failed"]
            or report["uncertain"]
            or report["blocked"]
            else 0
        )
    messages = preview_messages(state, config, args.date.isoformat())
    if args.preview_dir:
        if args.preview_dir.exists():
            parser.error("Preview directory must be new")
        args.preview_dir.mkdir(parents=True)
        for recipient, message in messages.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", recipient):
                raise ValueError("Recipient ID is not safe as a preview filename")
            write_bytes(args.preview_dir / f"{recipient}.eml", message.as_bytes())
            write_bytes(
                args.preview_dir / f"{recipient}.txt", message.get_content().encode()
            )
        print(f"Wrote {len(messages)} previews; no messages sent")
    else:
        for recipient, message in messages.items():
            print(f"Recipient ID: {recipient}\n{message}")
        if not messages:
            print("No pending researcher matches; no messages sent")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError):
        print(
            "Notification operation failed; inspect state and configuration. Credential values suppressed.",
            file=sys.stderr,
        )
        raise SystemExit(1)
