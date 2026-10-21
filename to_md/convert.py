"""Render validated summaries without overwriting Markdown on input failure."""

import argparse
from pathlib import Path

from ai.config import settings
from ai.quality import read_records, validate_records
from ai.storage import write_bytes


def convert(source, language=None):
    source = Path(source)
    rows = read_records(source)
    validate_records(rows)
    config = settings()
    language = language or config["language"]
    preferred = config["categories"]
    template = (Path(__file__).parent / "paper_template.md").read_text()
    if language == "Chinese":
        for old, new in (
            ("Main category:", "分类："),
            ("Details", "详细分析"),
            ("Motivation:", "研究动机："),
            ("Method:", "方法："),
            ("Result:", "结果："),
            ("Conclusion:", "结论："),
            ("Abstract:", "原始摘要："),
        ):
            template = template.replace(old, new)
    grouped = {}
    for row in rows:
        categories = row["categories"]
        category = next((c for c in preferred if c in categories), categories[0])
        grouped.setdefault(category, []).append(row)
    names = sorted(
        grouped,
        key=lambda c: (preferred.index(c) if c in preferred else len(preferred), c),
    )
    toc = "目录" if language == "Chinese" else "Contents"
    back = "返回目录" if language == "Chinese" else "Back"
    parts = [f'<div id="toc"></div>\n\n# {toc}\n']
    parts += [
        f"- [{category}](#{category}) ({len(grouped[category])})" for category in names
    ]
    index = 0
    for category in names:
        parts.append(
            f'\n<div id="{category}"></div>\n\n# {category} [[{back}]](#toc)\n'
        )
        for row in grouped[category]:
            index += 1
            parts.append(
                template.format(
                    title=row["title"],
                    authors=", ".join(row["authors"]),
                    summary=row["summary"],
                    url=row["abs"],
                    cate=category,
                    idx=index,
                    **row["AI"],
                )
            )
    target = source.with_name(source.stem.split("_AI_enhanced_", 1)[0] + ".md")
    write_bytes(target, ("\n\n".join(parts) + "\n").encode())
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    args = parser.parse_args()
    convert(args.data)


if __name__ == "__main__":
    main()
