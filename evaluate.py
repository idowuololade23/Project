import json
import argparse
from pathlib import Path

from services.classifier import classify_content
from services.extractor import extract_webpage
from services.sentiment import analyze_aspects
from services.summarizer import summarize_content


DATA_DIR = Path(__file__).parent / "tests" / "data"


def _load_cases(filename):
    return json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))


def evaluate(live=False):
    classification_cases = _load_cases("classification_cases.json")
    classification_correct = sum(
        classify_content(case["text"], case["title"])["content_type"] == case["expected"]
        for case in classification_cases
    )

    aspect_cases = _load_cases("aspect_cases.json")
    aspect_correct = sum(
        {
            item["aspect"]: item["sentiment"]
            for item in analyze_aspects(case["text"])
        }.get(case["aspect"]) == case["sentiment"]
        for case in aspect_cases
    )

    summary_cases = _load_cases("summary_cases.json")
    required_terms = 0
    covered_terms = 0
    for case in summary_cases:
        summary = summarize_content(case["text"], [], review_mode=False)["executive_summary"].casefold()
        required_terms += len(case["must_mention"])
        covered_terms += sum(term.casefold() in summary for term in case["must_mention"])

    results = {
        "classification": (classification_correct, len(classification_cases)),
        "aspect_sentiment": (aspect_correct, len(aspect_cases)),
        "summary_key_term_coverage": (covered_terms, required_terms),
    }
    for name, (correct, total) in results.items():
        print(f"{name}: {correct}/{total} ({correct / total:.1%})")
    if live:
        page = extract_webpage(
            "https://quotes.toscrape.com/js/",
            dynamic_min_words=40,
        )
        print(
            f"live_javascript_page: method={page.method}, "
            f"title={page.title!r}, words={len(page.text.split())}"
        )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="Fetch the public Quotes to Scrape JavaScript demo as a network smoke test.",
    )
    evaluate(live=parser.parse_args().live)
