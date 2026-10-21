import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daily_arxiv"))
from daily_arxiv.researchers import (
    build_index,
    config_digest,
    match_paper,
    normalize_name,
)

CATEGORIES = ["physics.plasm-ph"]
RESEARCHERS = [
    {
        "id": "arefiev",
        "display_name": "Alexey Arefiev",
        "enabled": True,
        "aliases": ["Alexey V. Arefiev"],
        "suspected_aliases": ["A. Arefiev", "A. V. Arefiev"],
    },
    {
        "id": "vieira",
        "display_name": "Jorge Vieira",
        "enabled": True,
        "aliases": [],
        "suspected_aliases": ["J. Vieira"],
    },
]


def paper(identifier="2610.12345v2", authors=None):
    return {
        "id": identifier,
        "authors": authors or ["Alexey Arefiev"],
        "categories": CATEGORIES,
        "title": "A <plasma> & photon study",
        "summary": "Raw abstract.",
        "abs": "https://arxiv.org/abs/" + identifier,
        "pdf": "https://arxiv.org/pdf/" + identifier,
    }


class ResearcherTests(unittest.TestCase):
    def test_full_names_aliases_and_initials_keep_their_confidence(self):
        rows = match_paper(
            paper(
                authors=[
                    "  ＡＬＥＸＥＹ\tAREFIEV ",
                    "Alexey V Arefiev",
                    "A.V. Arefiev",
                    "Jorge Vieira",
                ]
            ),
            RESEARCHERS,
            CATEGORIES,
        )
        self.assertEqual(
            [item["kind"] for item in rows],
            ["reliable", "reliable", "suspected", "reliable"],
        )
        self.assertEqual(
            [item["basis"] for item in rows],
            ["full_name", "confirmed_alias", "unconfirmed_alias", "full_name"],
        )
        self.assertEqual(rows[0]["author"], "  ＡＬＥＸＥＹ\tAREFIEV ")
        self.assertEqual(
            normalize_name("A. V. Arefiev"), normalize_name("A.V. Arefiev")
        )

    def test_no_substring_fuzzy_or_inferred_initial_match(self):
        for author in (
            "Alex Arefiev",
            "Arefiev",
            "Alexey Arefiev Jr",
            "Alexey.Arefiev",
            "J Vieira Smith",
            "J. Arefiev",
        ):
            self.assertEqual(
                match_paper(paper(authors=[author]), RESEARCHERS, CATEGORIES), []
            )

    def test_scope_disabled_and_html_names(self):
        researchers = copy.deepcopy(RESEARCHERS)
        researchers[0]["enabled"] = False
        self.assertEqual(match_paper(paper(), researchers, CATEGORIES), [])
        self.assertEqual(match_paper(paper(), RESEARCHERS, ["physics.optics"]), [])
        name = '<Author & "Co">'
        researchers = [{"id": "special", "display_name": name, "enabled": True}]
        self.assertEqual(
            match_paper(paper(authors=[name]), researchers, CATEGORIES)[0]["author"],
            name,
        )

    def test_middle_author_and_multiple_matches_are_preserved(self):
        authors = ["Other Author"] * 30
        authors[14:16] = ["Alexey Arefiev", "Jorge Vieira"]
        self.assertEqual(
            len(match_paper(paper(authors=authors), RESEARCHERS, CATEGORIES)), 2
        )

    def test_index_scans_raw_history_and_deduplicates_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for day, row in (
                ("2026-10-20", paper()),
                ("2026-10-21", paper("2610.12345v3")),
            ):
                (root / f"{day}.jsonl").write_text(json.dumps(row) + "\n")
            (root / "2026-10-19_AI_enhanced_English.jsonl").write_text(
                json.dumps(paper("2610.11111")) + "\n"
            )
            index = build_index(root, RESEARCHERS, CATEGORIES)
            self.assertEqual(list(index["papers"]), ["2610.12345"])
            self.assertEqual(
                index["papers"]["2610.12345"],
                match_paper(paper(), RESEARCHERS, CATEGORIES),
            )
            self.assertEqual(
                index["config_digest"], config_digest(RESEARCHERS, CATEGORIES)
            )
            self.assertNotEqual(
                config_digest(RESEARCHERS, ["physics.optics"]), index["config_digest"]
            )
            changed = copy.deepcopy(RESEARCHERS)
            changed[0]["enabled"] = False
            self.assertNotEqual(config_digest(changed), index["config_digest"])


if __name__ == "__main__":
    unittest.main()
