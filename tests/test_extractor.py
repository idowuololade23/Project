import pytest

import services.extractor as extractor
from services.extractor import ExtractedPage, ExtractionError, extract_webpage


def test_dynamic_fallback_is_used_for_thin_static_pages(monkeypatch):
    static = ExtractedPage(
        url="https://example.com/article",
        title="Loading",
        text=" ".join(["Loading"] * 10),
    )
    dynamic_text = " ".join(["JavaScript rendered article text"] * 15)
    dynamic = ExtractedPage(
        url="https://example.com/article",
        title="Rendered article",
        text=dynamic_text,
        method="javascript",
    )
    monkeypatch.setattr(extractor, "_validate_public_url", lambda url: None)
    monkeypatch.setattr(extractor, "_extract_static", lambda *args: static)
    monkeypatch.setattr(extractor, "_extract_dynamic", lambda *args: dynamic)

    result = extract_webpage("https://example.com/article", dynamic_min_words=40)

    assert result.method == "javascript"
    assert result.title == "Rendered article"


def test_readable_static_content_is_kept_when_dynamic_page_is_empty(monkeypatch):
    static = ExtractedPage(
        url="https://example.com/post",
        title="Product post",
        text=" ".join(["Readable post content"] * 10),
    )
    monkeypatch.setattr(extractor, "_validate_public_url", lambda url: None)
    monkeypatch.setattr(extractor, "_extract_static", lambda *args: static)
    monkeypatch.setattr(
        extractor,
        "_extract_dynamic",
        lambda *args: ExtractedPage(
            url="https://example.com/post",
            title="example.com",
            text="",
            method="javascript",
        ),
    )

    result = extract_webpage("https://example.com/post", dynamic_min_words=40)

    assert result is static


def test_readable_static_content_is_kept_when_dynamic_extraction_fails(monkeypatch, caplog):
    static = ExtractedPage(
        url="https://example.com/post",
        title="Product post",
        text=" ".join(["Readable post content"] * 10),
    )
    monkeypatch.setattr(extractor, "_validate_public_url", lambda url: None)
    monkeypatch.setattr(extractor, "_extract_static", lambda *args: static)

    def fail_dynamic(*args):
        raise ExtractionError("Browser rendering failed.")

    monkeypatch.setattr(extractor, "_extract_dynamic", fail_dynamic)

    result = extract_webpage("https://example.com/post", dynamic_min_words=40)

    assert result is static
    assert "retaining readable static content" in caplog.text


@pytest.mark.parametrize(
    "title,text",
    [
        (
            "GSMArena Turnstile check",
            "One quick check before you continue...",
        ),
        (
            "www.reddit.com",
            "You've been blocked by network security. If you think you've been blocked by mistake, file a ticket.",
        ),
    ],
)
def test_access_interstitials_are_not_returned_as_page_content(monkeypatch, title, text):
    page = ExtractedPage(
        url="https://example.com/page",
        title=title,
        text=text,
    )
    monkeypatch.setattr(extractor, "_validate_public_url", lambda url: None)
    monkeypatch.setattr(extractor, "_extract_static", lambda *args: page)

    with pytest.raises(ExtractionError, match="access or verification check"):
        extract_webpage("https://example.com/page", dynamic_enabled=False)


def test_dynamic_fallback_can_recover_from_static_http_errors(monkeypatch):
    dynamic = ExtractedPage(
        url="https://example.com/article",
        title="Rendered article",
        text=" ".join(["Rendered content is available after scripts load"] * 8),
        method="javascript",
    )
    monkeypatch.setattr(extractor, "_validate_public_url", lambda url: None)

    def fail_static(*args):
        raise ExtractionError("The webpage returned an error (HTTP 403).")

    monkeypatch.setattr(extractor, "_extract_static", fail_static)
    monkeypatch.setattr(extractor, "_extract_dynamic", lambda *args: dynamic)

    assert extract_webpage("https://example.com/article").method == "javascript"


def test_dynamic_access_interstitial_is_not_returned_as_page_content(monkeypatch):
    dynamic = ExtractedPage(
        url="https://example.com/page",
        title="www.reddit.com",
        text=(
            "You've been blocked by network security. If you think you've been blocked "
            "by mistake, file a ticket below and we'll look into it."
        ),
        method="javascript",
    )
    monkeypatch.setattr(extractor, "_validate_public_url", lambda url: None)

    def fail_static(*args):
        raise ExtractionError("The webpage returned an error (HTTP 403).")

    monkeypatch.setattr(extractor, "_extract_static", fail_static)
    monkeypatch.setattr(extractor, "_extract_dynamic", lambda *args: dynamic)

    with pytest.raises(ExtractionError, match="access or verification check"):
        extract_webpage("https://example.com/page")


def test_static_extraction_does_not_fall_back_when_dynamic_rendering_is_disabled(monkeypatch):
    monkeypatch.setattr(extractor, "_validate_public_url", lambda url: None)

    def fail_static(*args):
        raise ExtractionError("The webpage returned an error (HTTP 403).")

    def unexpected_browser(*args):
        raise AssertionError("Dynamic extraction should be disabled.")

    monkeypatch.setattr(extractor, "_extract_static", fail_static)
    monkeypatch.setattr(extractor, "_extract_dynamic", unexpected_browser)

    with pytest.raises(ExtractionError, match="HTTP 403"):
        extract_webpage("https://example.com/article", dynamic_enabled=False)


def test_browser_request_guard_blocks_local_and_nonstandard_targets(monkeypatch):
    def reject_url(url):
        if "127.0.0.1" in url or ":8080" in url:
            raise ExtractionError("Private or local webpages cannot be fetched.")

    monkeypatch.setattr(extractor, "_validate_public_url", reject_url)

    assert not extractor._browser_request_is_public("http://127.0.0.1/private")
    assert not extractor._browser_request_is_public("https://example.com:8080/")
    assert extractor._browser_request_is_public("https://example.com/")
