import io
import json
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock
from pydantic import ValidationError
from ai.structure import Structure
from ai.structured_output import (
    DEFAULT_AI_FIELDS,
    enhance_fields,
    response_fields,
    validated_topics,
)

GOOD = {key: "有效内容：" + key for key in DEFAULT_AI_FIELDS}
FOUR = {key: value for key, value in GOOD.items() if key != "conclusion"}
TOPICS = {
    "keywords": ["Strong-field QED", "γ-ray emission", "laser polarization"],
    "laser_plasma_keywords": ["Strong-field QED", "laser polarization"],
}


def envelope(fields):
    return {
        "raw": SimpleNamespace(
            tool_calls=[{"name": "Structure", "args": fields}], additional_kwargs={}
        ),
        "parsed": None,
        "parsing_error": ValueError("missing field"),
    }


class RecoveryTests(unittest.TestCase):
    def test_topic_validation_requires_english_terms_and_an_exact_subset(self):
        normalized = {
            "keywords": [
                "  Strong-field  QED ",
                "γ-ray emission",
                "laser polarization",
            ],
            "laser_plasma_keywords": ["strong-field qed", " LASER POLARIZATION "],
        }
        self.assertEqual(validated_topics(normalized), TOPICS)
        self.assertEqual(
            validated_topics({**TOPICS, "laser_plasma_keywords": []})[
                "laser_plasma_keywords"
            ],
            [],
        )
        for invalid in (
            None,
            [],
            {"keywords": TOPICS["keywords"]},
            {**TOPICS, "keywords": ["one", "two"]},
            {**TOPICS, "keywords": ["a", "b", "c", "d", "e", "f"]},
            {**TOPICS, "keywords": ["term", " TERM", "probe"]},
            {**TOPICS, "keywords": ["laser", "optics", "激光研究"]},
            {**TOPICS, "keywords": ["laser", "optics", "<script>"]},
            {**TOPICS, "laser_plasma_keywords": ["unlisted term"]},
            {
                **TOPICS,
                "laser_plasma_keywords": ["Strong-field QED", "strong-field qed"],
            },
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(validated_topics(invalid))

    def test_partial_topic_response_is_retained_and_does_not_drive_retries(self):
        chain = Mock()
        chain.invoke.side_effect = [
            envelope({**FOUR, "topics": TOPICS}),
            envelope({**GOOD, "topics": {**TOPICS, "laser_plasma_keywords": []}}),
        ]
        result = enhance_fields(chain, "abstract", "English", topic_title="Laser QED")
        self.assertEqual(result.fields, GOOD)
        self.assertEqual(result.topics, TOPICS)
        self.assertEqual(chain.invoke.call_count, 2)
        for call in chain.invoke.call_args_list:
            self.assertEqual(call.args[0]["topic_title"], "Laser QED")
        for value in (None, {"keywords": ["invalid"]}):
            with self.subTest(value=value):
                chain = Mock()
                chain.invoke.return_value = envelope({**GOOD, "topics": value})
                result = enhance_fields(
                    chain, "abstract", "English", topic_title="title"
                )
                self.assertTrue(result.complete)
                self.assertIsNone(result.topics)
                chain.invoke.assert_called_once()

    def test_missing_conclusion_keeps_four_fields_and_repairs_only_missing(self):
        chain = Mock()
        chain.invoke.side_effect = [
            envelope(FOUR),
            envelope({**GOOD, "tldr": "do not overwrite"}),
        ]
        result = enhance_fields(chain, "abstract", "Chinese")
        self.assertEqual(result.fields, GOOD)
        self.assertEqual(result.attempts, 2)
        retry = chain.invoke.call_args.args[0]["content"]
        self.assertIn("missing/invalid fields: conclusion", retry)
        self.assertIn(json.dumps(FOUR, ensure_ascii=False), retry)

    def test_direct_pydantic_validation_error_recovers_partial_input(self):
        try:
            Structure(**FOUR)
        except ValidationError as exc:
            error = exc
        chain = Mock()
        chain.invoke.side_effect = [error, Structure(**GOOD)]
        self.assertEqual(enhance_fields(chain, "abstract", "Chinese").fields, GOOD)

    def test_bounded_retry_exhaustion_retains_partial_fields(self):
        chain = Mock()
        chain.invoke.return_value = envelope(FOUR)
        result = enhance_fields(chain, "abstract", "Chinese")
        self.assertEqual(chain.invoke.call_count, 3)
        self.assertEqual(result.fields, FOUR)
        self.assertEqual(result.missing, ("conclusion",))
        self.assertFalse(result.complete)

    def test_nonempty_strings_required_and_placeholders_not_success(self):
        for bad in (
            None,
            "",
            " \n ",
            23,
            {},
            [],
            "Processing failed",
            "Conclusion extraction failed",
        ):
            with self.subTest(bad=bad):
                chain = Mock()
                chain.invoke.side_effect = [
                    envelope({**FOUR, "conclusion": bad}),
                    envelope(GOOD),
                ]
                self.assertEqual(
                    enhance_fields(chain, "abstract", "Chinese").fields, GOOD
                )
                self.assertEqual(chain.invoke.call_count, 2)

    def test_complete_existing_data_never_calls_model(self):
        chain = Mock()
        self.assertEqual(
            enhance_fields(chain, "abstract", "Chinese", existing=GOOD).attempts, 0
        )
        chain.invoke.assert_not_called()

    def test_provider_error_stops_without_losing_fields_or_logging_body(self):
        class AuthenticationError(Exception):
            pass

        chain = Mock()
        chain.invoke.side_effect = [
            envelope(FOUR),
            AuthenticationError("secret-body-sentinel"),
        ]
        log = io.StringIO()
        with redirect_stderr(log):
            result = enhance_fields(chain, "abstract", "Chinese")
        self.assertEqual(result.fields, FOUR)
        self.assertEqual(result.error_type, "AuthenticationFailure")
        self.assertEqual(chain.invoke.call_count, 2)
        self.assertNotIn("secret-body-sentinel", log.getvalue())

    def test_first_provider_failure_does_not_enter_schema_retry(self):
        chain = Mock()
        chain.invoke.side_effect = RuntimeError("private response body")
        self.assertFalse(enhance_fields(chain, "abstract", "Chinese").complete)
        self.assertEqual(chain.invoke.call_count, 1)

    def test_raw_function_arguments_preserve_latex_escaping(self):
        fields = {
            **GOOD,
            "method": r"由 $\mathbf L\mathbf U=-\mathbf a$ 得到法向速度。",
        }
        raw = SimpleNamespace(
            tool_calls=[],
            additional_kwargs={
                "tool_calls": [
                    {"function": {"name": "Structure", "arguments": json.dumps(fields)}}
                ]
            },
        )
        self.assertEqual(response_fields({"raw": raw, "parsed": None}), fields)

    def test_malformed_json_and_wrong_tool_are_not_salvaged_as_success(self):
        raw = SimpleNamespace(
            tool_calls=[],
            additional_kwargs={
                "tool_calls": [
                    {"function": {"name": "Structure", "arguments": '{"tldr": "broken'}}
                ]
            },
        )
        self.assertEqual(response_fields({"raw": raw, "parsed": None}), {})
        raw.tool_calls = [{"name": "Unrelated", "args": GOOD}]
        raw.additional_kwargs = {}
        self.assertEqual(response_fields({"raw": raw, "parsed": None}), {})

    def test_truncated_json_is_not_accepted_from_a_lenient_parser(self):
        raw = SimpleNamespace(
            content='{"tldr":"truncated', tool_calls=[], additional_kwargs={}
        )
        self.assertEqual(response_fields({"raw": raw, "parsed": Structure(**GOOD)}), {})
