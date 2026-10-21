import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from ai import deepseek, enhance
from ai.config import settings
from ai.errors import AuthenticationFailure, EnhancementError, safe_failure
from ai.quality import FIELDS, valid_ai, validate_records
from ai.storage import write_bytes

GOOD = {key: "Valid " + key for key in FIELDS}


def paper(identifier="2610.26164"):
    return {
        "id": identifier,
        "title": "Test",
        "summary": "A full abstract",
        "authors": ["Author"],
        "categories": ["physics.plasm-ph"],
        "abs": "https://arxiv.org/abs/" + identifier,
    }


def completion(fields=GOOD, finish="stop"):
    return {
        "id": "offline",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-flash",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(fields),
                    "reasoning_content": "PRIVATE_REASONING",
                },
            }
        ],
    }


class ModelTests(unittest.TestCase):
    def chain(self, handler):
        transport = httpx.Client(
            transport=httpx.MockTransport(handler), trust_env=False
        )
        self.addCleanup(transport.close)
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-test-key"}),
            patch.object(
                deepseek,
                "OpenAI",
                side_effect=lambda **kw: OpenAI(**kw, http_client=transport),
            ),
        ):
            chain = deepseek.DeepSeekSummaryChain()
        self.addCleanup(chain.close)
        return chain

    def test_max_request_and_partial_recovery_in_both_languages(self):
        for language in ("English", "Chinese"):
            requests = []

            def handle(request):
                body = json.loads(request.content)
                requests.append(body)
                self.assertEqual(request.url.host, "api.deepseek.com")
                fields = {
                    k: v
                    for k, v in GOOD.items()
                    if len(requests) > 1 or k != "conclusion"
                }
                if len(requests) > 1:
                    fields["tldr"] = "Do not overwrite"
                return httpx.Response(200, json=completion(fields))

            chain = self.chain(handle)
            original = paper()
            original["summary"] = "Full abstract " * 10000 + "END_OF_INPUT"
            with patch.object(enhance, "is_sensitive", return_value=False):
                result = enhance.process_single_item(chain, original, language)
            self.assertEqual(result["AI"], GOOD)
            self.assertNotIn("AI", original)
            self.assertEqual(len(requests), 2)
            for body in requests:
                self.assertEqual(body["model"], "deepseek-flash")
                self.assertEqual(body["thinking"], {"type": "enabled"})
                self.assertEqual(body["reasoning_effort"], "max")
                self.assertEqual(body["max_tokens"], 393216)
                self.assertEqual(body["response_format"], {"type": "json_object"})
                self.assertIn("END_OF_INPUT", body["messages"][1]["content"])
                self.assertIn(language, body["messages"][0]["content"])
                for key in (
                    "tools",
                    "tool_choice",
                    "max_completion_tokens",
                    "context_length",
                    "temperature",
                ):
                    self.assertNotIn(key, body)

    def test_auth_parameter_and_truncation_errors_stop_before_second_paper(self):
        for status, payload in [
            (
                401,
                {"error": {"message": "PRIVATE_BODY", "type": "authentication_error"}},
            ),
            (403, {"error": {"message": "PRIVATE_BODY", "type": "permission_denied"}}),
            (
                400,
                {"error": {"message": "PRIVATE_BODY", "type": "invalid_request_error"}},
            ),
            (200, completion(finish="length")),
        ]:
            with self.subTest(status=status):
                calls = []

                def handle(request):
                    calls.append(request)
                    return httpx.Response(status, json=payload)

                with (
                    patch.object(enhance, "is_sensitive", return_value=False),
                    self.assertRaises(EnhancementError) as error,
                ):
                    enhance.process_all_items(
                        [paper(), paper("2610.24394")], "English", self.chain(handle)
                    )
                self.assertEqual(len(calls), 1)
                self.assertNotIn("PRIVATE", str(error.exception))
                if status in (401, 403):
                    self.assertIsInstance(error.exception, AuthenticationFailure)

    def test_complete_existing_fields_make_no_model_call(self):
        chain = Mock()
        with patch.object(enhance, "is_sensitive", return_value=False):
            result = enhance.process_single_item(
                chain, {**paper(), "AI": GOOD}, "Chinese"
            )
        chain.invoke.assert_not_called()
        self.assertEqual(result["AI"], GOOD)

    def test_content_check_outage_and_rejection_cannot_drop_rows(self):
        with patch.object(
            enhance.requests, "post", side_effect=RuntimeError("PRIVATE")
        ):
            with self.assertRaises(EnhancementError):
                enhance.is_sensitive("abstract")
        with (
            patch.object(enhance, "is_sensitive", return_value=True),
            self.assertRaises(EnhancementError),
        ):
            enhance.process_all_items([paper()], "English", Mock())

    def test_wrapped_authentication_error_is_redacted(self):
        inner = RuntimeError("PRIVATE")
        inner.status_code = 401
        outer = ValueError("PRIVATE")
        outer.__cause__ = inner
        self.assertIsInstance(safe_failure(outer), AuthenticationFailure)
        self.assertNotIn("PRIVATE", str(safe_failure(outer)))

    def test_daily_failure_preserves_output_and_saves_completed_and_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "2026-10-20.jsonl"
            source.write_text(json.dumps(paper()) + "\n")
            target = source.with_name(
                "2026-10-20_AI_enhanced_" + settings()["language"] + ".jsonl"
            )
            target.write_bytes(b"previous healthy output\r\n")
            partial = {**paper(), "AI": {"tldr": "Retain this"}}
            error = EnhancementError("Incomplete", partial)
            error.completed = []
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-test-key"}),
                patch.object(enhance, "process_all_items", side_effect=error),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(enhance.main(["--data", str(source)]), 1)
            self.assertEqual(target.read_bytes(), b"previous healthy output\r\n")
            checkpoint = json.loads(target.with_suffix(".partial.json").read_text())
            self.assertEqual(checkpoint["partial"]["AI"], partial["AI"])

    def test_configuration_check_prints_no_secret_values(self):
        for key in ("", " SECRET ", "contains space"):
            log = io.StringIO()
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": key}),
                contextlib.redirect_stderr(log),
            ):
                self.assertEqual(enhance.main(["--check-config"]), 1)
            self.assertNotIn("SECRET", log.getvalue())

    def test_quality_and_atomic_failure_preserve_previous_file(self):
        for bad in ("", None, 12, "Processing failed", "Conclusion extraction failed"):
            self.assertFalse(valid_ai({**GOOD, "conclusion": bad}))
        for rows in ([], [paper()], [{**paper(), "AI": GOOD}] * 2):
            with self.assertRaises(ValueError):
                validate_records(rows)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "data"
            target.write_bytes(b"old")
            with (
                patch("ai.storage.os.replace", side_effect=OSError()),
                self.assertRaises(OSError),
            ):
                write_bytes(target, b"new")
            self.assertEqual(target.read_bytes(), b"old")
            self.assertEqual(list(Path(temp).iterdir()), [target])
