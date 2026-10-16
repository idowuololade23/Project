import io
import pytest
import json
from pathlib import Path

from app import create_app
import app as application
from config import TestingConfig
from database import db
from models import Analysis
from services.classifier import classify_content
from services.extractor import ExtractedPage, ExtractionError, _validate_public_url
from services.sentiment import analyze_aspects


@pytest.fixture()
def client():
    app = create_app(TestingConfig)
    with app.test_client() as client:
        with app.app_context():
            db.drop_all()
            db.create_all()
        yield client


def submit_text(client, text):
    client.get("/")
    with client.session_transaction() as session:
        token = session.get("_csrf_token")
    return client.post("/analyze", data={"_csrf_token": token, "text": text}, follow_redirects=True)


def test_review_analysis_persists_aspect_sentiment(client):
    text = (
        "This product review is excellent. The battery is excellent but the price is too high. "
        "The design is beautiful and I recommend this product."
    )
    response = submit_text(client, text)
    assert response.status_code == 200
    assert b"Sentiment mix" in response.data
    assert b"Battery" in response.data
    with client.application.app_context():
        saved = db.session.query(Analysis).one()
        assert saved.is_review is True
        assert saved.content_type == "product_review"
        assert {aspect.aspect: aspect.sentiment for aspect in saved.aspects}["battery"] == "positive"
        assert {aspect.aspect: aspect.sentiment for aspect in saved.aspects}["price"] == "negative"


def test_informational_content_uses_content_mode(client):
    text = (
        "Research article: This study examines how communities use public libraries. "
        "The methodology compares survey results with published research. "
        "The findings describe learning, access, and community participation."
    )
    response = submit_text(client, text)
    assert response.status_code == 200
    assert b"Topics in this content" in response.data
    assert b"review sentiment metrics are not applicable" in response.data


def test_requires_exactly_one_input(client):
    client.get("/")
    with client.session_transaction() as session:
        token = session.get("_csrf_token")
    response = client.post("/analyze", data={"_csrf_token": token}, follow_redirects=True)
    assert b"Choose a webpage URL, pasted text, or one review file." in response.data


def test_uploading_csv_analyzes_reviews_and_records_upload_source(client):
    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/analyze",
        data={
            "_csrf_token": token,
            "file": (
                io.BytesIO(
                    b'review,rating\n"The battery is excellent but the price is too high. I recommend this product.",5\n'
                ),
                "customer-reviews.csv",
            ),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Sentiment mix" in response.data
    assert b"Uploaded: customer-reviews.csv" in response.data
    with client.application.app_context():
        saved = db.session.query(Analysis).one()
        assert saved.extraction_method == "upload_csv"
        assert saved.source_url is None
        assert "The battery is excellent" in saved.extracted_text
        assert {aspect.aspect: aspect.sentiment for aspect in saved.aspects}["price"] == "negative"


def test_uploading_docx_extracts_review_text_for_analysis(client):
    import zipfile

    document_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>This product review is excellent.</w:t></w:r></w:p>
      <w:p><w:r><w:t>The battery is excellent and the design is beautiful.</w:t></w:r></w:p>
      <w:p><w:r><w:t>I recommend this product.</w:t></w:r></w:p></w:body>
    </w:document>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as document:
        document.writestr("word/document.xml", document_xml)

    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/analyze",
        data={
            "_csrf_token": token,
            "file": (io.BytesIO(output.getvalue()), "review.docx"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Sentiment mix" in response.data
    with client.application.app_context():
        saved = db.session.query(Analysis).one()
        assert saved.extraction_method == "upload_docx"
        assert "The battery is excellent" in saved.extracted_text


def test_browser_extension_text_is_saved_with_its_source_page(client):
    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/analyze",
        data={
            "_csrf_token": token,
            "text": "The product review is excellent. The battery is excellent but the price is too high.",
            "captured_url": "https://example.com/reviews/pixel",
            "captured_title": "Pixel customer reviews",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Pixel customer reviews" in response.data
    assert b"https://example.com/reviews/pixel" in response.data
    with client.application.app_context():
        saved = db.session.query(Analysis).order_by(Analysis.id.desc()).first()
        assert saved.extraction_method == "browser_extension"
        assert saved.source_url == "https://example.com/reviews/pixel"


def test_uploaded_file_and_pasted_text_cannot_be_combined(client):
    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/analyze",
        data={
            "_csrf_token": token,
            "text": "Some manually pasted content.",
            "file": (io.BytesIO(b"Uploaded content."), "review.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert b"Choose a webpage URL, pasted text, or one review file." in response.data
    with client.application.app_context():
        assert db.session.query(Analysis).count() == 0


def test_oversized_upload_gets_a_clear_size_error(client):
    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/analyze",
        data={
            "_csrf_token": token,
            "file": (io.BytesIO(b"x" * (1024 * 1024 + 1)), "too-large.txt"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert b"keep files under 1 MB" in response.data


def test_browser_extension_source_requires_http_or_https_url(client):
    response = submit_text(client, "The review has enough words to satisfy normal text input validation.")
    assert response.status_code == 200

    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/analyze",
        data={
            "_csrf_token": token,
            "text": "The review has enough words to satisfy normal text input validation.",
            "captured_url": "javascript:alert(1)",
        },
        follow_redirects=True,
    )
    assert b"invalid source URL" in response.data


def test_analysis_records_are_private_to_the_creating_browser(client):
    response = submit_text(
        client,
        "This product review is excellent. The battery is excellent and the design is beautiful.",
    )
    assert response.status_code == 200
    with client.application.app_context():
        analysis_id = db.session.query(Analysis.id).one()[0]

    other_browser = client.application.test_client()
    assert other_browser.get(f"/analysis/{analysis_id}").status_code == 404
    assert b"product review is excellent" not in other_browser.get("/history").data.lower()


def test_webpage_analysis_records_dynamic_extraction_method(client, monkeypatch):
    arguments = {}

    def fake_extractor(url, **kwargs):
        arguments.update(kwargs)
        return ExtractedPage(
            url=url,
            title="Product review",
            text=(
                "This product review is excellent. Battery life is excellent, "
                "but the price is too high for most buyers."
            ),
            method="javascript",
        )

    monkeypatch.setattr(application, "extract_webpage", fake_extractor)
    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/analyze",
        data={"_csrf_token": token, "url": "https://example.com/review"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Javascript extraction" in response.data
    assert arguments["dynamic_enabled"] is False
    with client.application.app_context():
        saved = db.session.query(Analysis).one()
        assert saved.extraction_method == "javascript"
        assert saved.source_url == "https://example.com/review"


def test_owner_can_delete_analysis_and_its_aspects(client):
    submit_text(
        client,
        "This product review is excellent. The battery is excellent and the design is beautiful.",
    )
    with client.application.app_context():
        saved = db.session.query(Analysis).one()
        analysis_id = saved.id
        assert saved.aspects
    with client.session_transaction() as session:
        token = session["_csrf_token"]

    response = client.post(
        f"/analysis/{analysis_id}/delete",
        data={"_csrf_token": token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.application.app_context():
        assert db.session.query(Analysis).count() == 0


def test_owner_can_delete_all_saved_analyses(client):
    submit_text(
        client,
        "This product review is excellent. The battery is excellent and the design is beautiful.",
    )
    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/history/delete-all", data={"_csrf_token": token}, follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Deleted 1 saved analysis" in response.data
    with client.application.app_context():
        assert db.session.query(Analysis).count() == 0


def test_analysis_endpoint_is_rate_limited(client):
    client.application.config["ANALYSIS_RATE_LIMIT"] = "1 per hour"
    first = submit_text(
        client,
        "This product review is excellent. The battery is excellent and the design is beautiful.",
    )
    assert first.status_code == 200
    client.get("/")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    second = client.post(
        "/analyze",
        data={"_csrf_token": token, "text": "This product review is excellent. " * 8},
    )
    assert second.status_code == 429


def test_classifier_identifies_bible_commentary():
    result = classify_content(
        "Bible commentary on the Gospel and scripture, exploring the meaning of this verse."
    )
    assert result["content_type"] == "bible_commentary"
    assert result["is_review"] is False


def test_mixed_aspect_feedback_without_review_keyword_is_review_mode(client):
    response = submit_text(
        client,
        "The battery is excellent but the price is too high.",
    )
    assert response.status_code == 200
    assert b"Sentiment mix" in response.data
    assert b"Battery" in response.data
    assert b"Price" in response.data


def test_labeled_classification_corpus_meets_accuracy_baseline():
    cases_path = Path(__file__).parent / "data" / "classification_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    correct = [
        case for case in cases
        if classify_content(case["text"], case["title"])["content_type"] == case["expected"]
    ]
    accuracy = len(correct) / len(cases)
    assert accuracy >= 0.85, (
        f"Classification accuracy {accuracy:.0%} below 85%; "
        f"misses: {[case for case in cases if case not in correct]}"
    )


def test_labeled_aspect_corpus_meets_sentiment_baseline():
    cases_path = Path(__file__).parent / "data" / "aspect_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    correct = 0
    misses = []
    for case in cases:
        results = {
            result["aspect"]: result["sentiment"]
            for result in analyze_aspects(case["text"])
        }
        if results.get(case["aspect"]) == case["sentiment"]:
            correct += 1
        else:
            misses.append({**case, "actual": results.get(case["aspect"])})
    accuracy = correct / len(cases)
    assert accuracy >= 0.9, (
        f"Aspect sentiment accuracy {accuracy:.0%} below 90%; misses: {misses}"
    )


def test_summary_keeps_distinct_relevant_points():
    from services.summarizer import summarize_content

    text = (
        "Customer feedback highlights the long battery life as a major strength. "
        "Several reviewers praise the bright screen and sturdy design. "
        "A recurring concern is the expensive price, especially for students. "
        "Overall buyers appreciate the dependable performance."
    )
    result = summarize_content(text, [], review_mode=False)
    summary = result["executive_summary"].lower()
    assert "battery" in summary
    assert "price" in summary
    assert len(summary) <= 900


def test_labeled_summary_corpus_meets_key_term_coverage_baseline():
    from services.summarizer import summarize_content

    cases_path = Path(__file__).parent / "data" / "summary_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    required = [
        term
        for case in cases
        for term in case["must_mention"]
    ]
    covered = sum(
        term.casefold() in summarize_content(case["text"], [], False)["executive_summary"].casefold()
        for case in cases
        for term in case["must_mention"]
    )
    coverage = covered / len(required)
    assert coverage >= 0.8, (
        f"Summary key-term coverage {coverage:.0%} below 80%; "
        "review the labeled summary fixtures."
    )


def test_sentiment_detects_negation():
    aspects = analyze_aspects("The battery is not good, and the camera is excellent.")
    mapped = {aspect["aspect"]: aspect["sentiment"] for aspect in aspects}
    assert mapped["battery"] == "negative"
    assert mapped["camera"] == "positive"


def test_neutral_aspect_mentions_are_counted():
    aspects = analyze_aspects("The camera and battery are included in the package.")
    mapped = {aspect["aspect"]: aspect["sentiment"] for aspect in aspects}
    assert mapped["camera"] == "neutral"
    assert mapped["battery"] == "neutral"


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://localhost", "http://example.com:invalid"])
def test_extractor_rejects_private_and_invalid_destinations(url):
    with pytest.raises(ExtractionError):
        _validate_public_url(url)


def test_health_and_history_pages(client):
    assert client.get("/health").json == {"status": "ok"}
    assert client.get("/history").status_code == 200


def test_private_pages_disable_caching_and_include_security_headers(client):
    response = client.get("/")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_production_configuration_refuses_in_memory_rate_limiting():
    class UnsafeProductionConfig(TestingConfig):
        APP_ENV = "production"
        SECRET_KEY = "test-secret-key-that-is-long-enough-for-production"
        SQLALCHEMY_DATABASE_URI = "postgresql+psycopg://db/insightlens"
        RATELIMIT_STORAGE_URI = "memory://"
        SESSION_COOKIE_SECURE = True
        TRUSTED_PROXY_COUNT = 1

    with pytest.raises(RuntimeError, match="shared rate-limit store"):
        create_app(UnsafeProductionConfig)
