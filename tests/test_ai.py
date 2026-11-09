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
from ai.reuse import generation_provenance
from ai.storage import write_bytes

GOOD = {key: "Valid " + key for key in FIELDS}
TOPICS = {
    "keywords": ["vacuum birefringence", "strong-field QED", "probe polarization"],
    "laser_plasma_keywords": ["vacuum birefringence", "strong-field QED"],
}


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

    def test_topics_use_the_normal_english_completion_with_title_and_entire_abstract(
        self,
    ):
        requests = []

        def handle(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json=completion({**GOOD, "topics": TOPICS}))

        original = {
            **paper(),
            "title": "Vacuum birefringence from intense lasers",
            "summary": "A full abstract " * 1000 + "END_OF_INPUT",
        }
        with patch.object(enhance, "is_sensitive", return_value=False) as moderation:
            (result,) = enhance.process_all_items(
                [original], "English", self.chain(handle), topics_enabled=True
            )
        self.assertEqual(len(requests), 1)
        system, user = (message["content"] for message in requests[0]["messages"])
        self.assertIn("strong-field optics or vacuum strong-field QED", system)
        self.assertIn("laser_plasma_keywords", system)
        self.assertIn(original["title"], user)
        self.assertIn(original["summary"], user)
        self.assertEqual(result["topics"], TOPICS)
        self.assertEqual(result["AI"], GOOD)
        moderation.assert_any_call(original["title"])
        moderation.assert_any_call("\n".join(TOPICS["keywords"]))
        self.assertNotIn("topics", original)

    def test_legacy_and_chinese_requests_ignore_supplied_and_model_topics(self):
        original = {**paper(), "topics": TOPICS, "topics_enabled": True}
        for language, enabled in [("English", False), ("Chinese", True)]:
            chain = Mock()
            chain.invoke.return_value = {**GOOD, "topics": TOPICS}
            with patch.object(enhance, "is_sensitive", return_value=False):
                row = enhance.process_single_item(
                    chain, original, language, topics_enabled=enabled
                )
            chain.invoke.assert_called_once_with(
                {"content": paper()["summary"], "language": language}
            )
            self.assertEqual(row["AI"], GOOD)
            self.assertNotIn("topics", row)
            self.assertNotIn("topics_enabled", row)

    def test_rejected_title_or_source_outage_stops_before_model_and_cleans_checkpoint(
        self,
    ):
        partial_ai = {"tldr": GOOD["tldr"]}
        original = {
            **paper(),
            "AI": partial_ai,
            "topics": TOPICS,
            "topics_enabled": True,
        }
        for rejection in (True, EnhancementError("Content-check service failed")):
            chain = Mock()
            progress = Mock()
            with (
                patch.object(
                    enhance, "is_sensitive", side_effect=[False, rejection]
                ) as moderation,
                self.assertRaises(EnhancementError) as failure,
            ):
                enhance.process_all_items(
                    [original], "English", chain, progress, topics_enabled=True
                )
            self.assertEqual(
                [call.args[0] for call in moderation.call_args_list],
                [
                    original["summary"],
                    original["title"],
                ],
            )
            chain.invoke.assert_not_called()
            snapshot = failure.exception.record
            self.assertEqual(snapshot["AI"], partial_ai)
            self.assertNotIn("topics", snapshot)
            self.assertNotIn("topics_enabled", snapshot)
            progress.assert_called_once_with([], snapshot)

    def test_topic_moderation_outage_or_rejection_preserves_the_summary(self):
        text = "\n".join(TOPICS["keywords"])
        for fail in (True, EnhancementError("moderation unavailable")):

            def moderate(content):
                if content == text:
                    if isinstance(fail, Exception):
                        raise fail
                    return fail
                return False

            chain = Mock()
            chain.invoke.return_value = {**GOOD, "topics": TOPICS}
            with patch.object(enhance, "is_sensitive", side_effect=moderate):
                row = enhance.process_single_item(
                    chain, paper(), "English", topics_enabled=True
                )
            self.assertEqual(row["AI"], GOOD)
            self.assertNotIn("topics", row)
            chain.invoke.assert_called_once()

    def test_only_a_matching_topic_checkpoint_resumes_partial_results(self):
        chain = Mock()
        chain.invoke.side_effect = [
            {"tldr": GOOD["tldr"], "topics": TOPICS},
            RuntimeError(),
        ]
        with (
            patch.object(enhance, "is_sensitive", return_value=False),
            self.assertRaises(EnhancementError) as failure,
        ):
            enhance.process_single_item(chain, paper(), "English", topics_enabled=True)
        partial = failure.exception.record
        self.assertEqual(partial["AI"], {"tldr": GOOD["tldr"]})
        self.assertEqual(partial["topics"], TOPICS)

        provenance = generation_provenance(topics_enabled=True)
        self.assertNotEqual(provenance, generation_provenance())
        with patch.object(deepseek, "TOPIC_INSTRUCTIONS", "CHANGED"):
            self.assertNotEqual(provenance, generation_provenance(topics_enabled=True))
        path = Mock()
        path.read_text.return_value = json.dumps(
            {
                "source_sha256": "bound",
                "provenance": provenance,
                "language": "English",
                "partial": partial,
            }
        )
        with self.assertRaisesRegex(ValueError, "provenance"):
            enhance.resume_rows([paper()], path, "bound", "English")
        with self.assertRaisesRegex(ValueError, "title"):
            enhance.resume_rows(
                [{**paper(), "title": "Other"}],
                path,
                "bound",
                "English",
                topics_enabled=True,
            )
        rows = enhance.resume_rows(
            [paper()], path, "bound", "English", topics_enabled=True
        )
        chain = Mock()
        chain.invoke.return_value = {"topics": None, **GOOD}
        with patch.object(enhance, "is_sensitive", return_value=False):
            (result,) = enhance.process_all_items(
                rows, "English", chain, topics_enabled=True
            )
        self.assertEqual(result["AI"], GOOD)
        self.assertEqual(result["topics"], TOPICS)
        chain.invoke.assert_called_once()
        with patch.object(enhance, "is_sensitive", return_value=False):
            complete = enhance.process_single_item(
                chain, {**paper(), "AI": GOOD}, "English", topics_enabled=True
            )
        self.assertNotIn("topics", complete)
        chain.invoke.assert_called_once()

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
