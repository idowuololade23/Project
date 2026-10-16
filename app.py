import hmac
import secrets
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from database import db, migrate
from models import Analysis, AspectMention
from services.analytics import build_review_analytics
from services.classifier import classify_content
from services.extractor import ExtractionError, extract_webpage
from services.sentiment import analyze_aspects
from services.summarizer import summarize_content
from services.uploads import UploadError, extract_uploaded_text


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    if not app.config["SECRET_KEY"]:
        if not app.testing and app.config.get("APP_ENV") == "production":
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production.")
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning("No SECRET_KEY set; using an ephemeral development key.")
    if app.config.get("APP_ENV") == "production":
        if len(app.config["SECRET_KEY"]) < 32:
            raise RuntimeError("Production SECRET_KEY must contain at least 32 characters.")
        if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
            raise RuntimeError(
                "Production requires a shared database. Set DATABASE_URL to PostgreSQL."
            )
        if not app.config["SESSION_COOKIE_SECURE"]:
            raise RuntimeError(
                "Production requires COOKIE_SECURE=true and HTTPS termination."
            )
        if app.config["TRUSTED_PROXY_COUNT"] < 1:
            raise RuntimeError(
                "Production requires TRUSTED_PROXY_COUNT for the TLS reverse proxy."
            )
        if app.config["RATELIMIT_STORAGE_URI"].startswith("memory://"):
            raise RuntimeError(
                "Production requires a shared rate-limit store. Set RATELIMIT_STORAGE_URI."
            )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[],
        storage_uri=app.config["RATELIMIT_STORAGE_URI"],
        headers_enabled=app.config["RATELIMIT_HEADERS_ENABLED"],
        key_prefix="insightlens",
    )
    limiter.init_app(app)
    if app.config.get("TRUSTED_PROXY_COUNT", 0) > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=app.config["TRUSTED_PROXY_COUNT"],
            x_proto=1,
            x_host=1,
        )

    @app.before_request
    def initialize_anonymous_workspace():
        if not session.get("workspace_id"):
            session["workspace_id"] = secrets.token_urlsafe(32)
        session.permanent = True
        return None

    @app.before_request
    def protect_post_requests():
        if request.method != "POST":
            return None
        submitted = request.form.get("_csrf_token", "")
        expected = session.get("_csrf_token", "")
        if not expected or not hmac.compare_digest(submitted, expected):
            abort(400, description="Your form session expired. Refresh the page and try again.")
        return None

    @app.context_processor
    def inject_csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["_csrf_token"]}

    @app.after_request
    def protect_browser_responses(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'"
        )
        if app.config.get("APP_ENV") == "production" and request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.get("/")
    def index():
        recent = (
            Analysis.query.filter_by(workspace_id=session["workspace_id"])
            .order_by(Analysis.created_at.desc())
            .limit(5)
            .all()
        )
        return render_template("index.html", recent=recent)

    @app.post("/analyze")
    @limiter.limit(lambda: app.config["ANALYSIS_RATE_LIMIT"])
    def analyze():
        submitted_url = request.form.get("url", "").strip()
        submitted_text = request.form.get("text", "").strip()
        uploaded_file = request.files.get("file")
        has_upload = bool(uploaded_file and uploaded_file.filename)
        captured_url = request.form.get("captured_url", "").strip()
        captured_title = request.form.get("captured_title", "").strip()
        if sum(bool(value) for value in (submitted_url, submitted_text, has_upload)) != 1:
            flash("Choose a webpage URL, pasted text, or one review file.", "error")
            return redirect(url_for("index"))
        if (captured_url or captured_title) and not submitted_text:
            flash("Browser page details must be sent together with captured text.", "error")
            return redirect(url_for("index"))
        if submitted_text and len(submitted_text) > app.config["MAX_TEXT_LENGTH"]:
            flash(
                f"The text is too long. Please keep it under "
                f"{app.config['MAX_TEXT_LENGTH']:,} characters.",
                "error",
            )
            return redirect(url_for("index"))

        try:
            if submitted_url:
                parsed = urlparse(submitted_url)
                if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                    raise ExtractionError("Enter a complete webpage URL beginning with http:// or https://.")
                page = extract_webpage(
                    submitted_url,
                    timeout=app.config["REQUEST_TIMEOUT"],
                    max_redirects=app.config["MAX_REDIRECTS"],
                    max_length=app.config["MAX_EXTRACTED_LENGTH"],
                    dynamic_enabled=app.config["DYNAMIC_EXTRACTION_ENABLED"],
                    dynamic_min_words=app.config["DYNAMIC_EXTRACTION_MIN_WORDS"],
                    dynamic_timeout_ms=app.config["DYNAMIC_EXTRACTION_TIMEOUT_MS"],
                )
                text, title, canonical_url = page.text, page.title, page.url
                extraction_method = page.method
            elif has_upload:
                filename = uploaded_file.filename
                text = extract_uploaded_text(
                    filename,
                    uploaded_file.stream.read(),
                    max_length=app.config["MAX_TEXT_LENGTH"],
                )
                title = f"Uploaded: {Path(filename).name}"[:500]
                canonical_url = None
                extension = Path(filename).suffix.lower().lstrip(".")
                extraction_method = f"upload_{extension}"
            else:
                text = submitted_text
                title = captured_title[:500] if captured_title else "Pasted text"
                canonical_url = None
                extraction_method = "pasted"
                if captured_url:
                    parsed = urlparse(captured_url)
                    if (
                        parsed.scheme.lower() not in {"http", "https"}
                        or not parsed.hostname
                        or parsed.username
                        or parsed.password
                        or len(captured_url) > 2048
                    ):
                        raise UploadError("The browser extension supplied an invalid source URL.")
                    try:
                        parsed.port
                    except ValueError:
                        raise UploadError("The browser extension supplied an invalid source URL.") from None
                    canonical_url = captured_url
                    extraction_method = "browser_extension"
        except (ExtractionError, UploadError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("index"))

        if len(text.split()) < 8:
            flash("There is not enough readable text to analyze. Try a longer page or passage.", "error")
            return redirect(url_for("index"))

        classification = classify_content(text, title)
        review_mode = classification["is_review"]
        aspects = analyze_aspects(text) if review_mode else []
        analytics = build_review_analytics(aspects) if review_mode else {}
        summary = summarize_content(text, aspects, review_mode)

        analysis = Analysis(
            workspace_id=session["workspace_id"],
            source_url=canonical_url,
            extraction_method=extraction_method,
            page_title=title[:500] if title else None,
            content_type=classification["content_type"],
            confidence=classification["confidence"],
            is_review=review_mode,
            extracted_text=text[: app.config["MAX_EXTRACTED_LENGTH"]],
            summary=summary["executive_summary"],
            strengths=summary["strengths"],
            weaknesses=summary["weaknesses"],
            recommendation=summary["recommendation"],
            business_insight=summary["business_insight"],
            topics=summary["topics"],
            positive_percent=analytics.get("positive_percent"),
            neutral_percent=analytics.get("neutral_percent"),
            negative_percent=analytics.get("negative_percent"),
        )
        analysis.aspects = [
            AspectMention(
                aspect=item["aspect"],
                sentiment=item["sentiment"],
                score=item["score"],
                mention_count=item["mention_count"],
                evidence=item["evidence"],
            )
            for item in aspects
        ]
        try:
            db.session.add(analysis)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Could not save analysis")
            flash("The analysis could not be saved. Please try again.", "error")
            return redirect(url_for("index"))

        return redirect(url_for("analysis_detail", analysis_id=analysis.id))

    @app.get("/analysis/<int:analysis_id>")
    def analysis_detail(analysis_id):
        analysis = db.first_or_404(
            db.select(Analysis).where(
                Analysis.id == analysis_id,
                Analysis.workspace_id == session["workspace_id"],
            )
        )
        aspects = [aspect.to_dict() for aspect in analysis.aspects]
        analytics = build_review_analytics(aspects) if analysis.is_review else {}
        return render_template(
            "analysis.html", analysis=analysis, aspects=aspects, analytics=analytics
        )

    @app.get("/history")
    def history():
        analyses = (
            Analysis.query.filter_by(workspace_id=session["workspace_id"])
            .order_by(Analysis.created_at.desc())
            .all()
        )
        return render_template("history.html", analyses=analyses)

    @app.post("/analysis/<int:analysis_id>/delete")
    def delete_analysis(analysis_id):
        analysis = Analysis.query.filter_by(
            id=analysis_id, workspace_id=session["workspace_id"]
        ).first_or_404()
        try:
            db.session.delete(analysis)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Could not delete analysis %s", analysis_id)
            flash("The analysis could not be deleted. Please try again.", "error")
            return redirect(url_for("analysis_detail", analysis_id=analysis_id))
        flash("Analysis deleted.", "success")
        return redirect(url_for("history"))

    @app.post("/history/delete-all")
    def delete_all_analyses():
        analyses = Analysis.query.filter_by(workspace_id=session["workspace_id"]).all()
        try:
            for analysis in analyses:
                db.session.delete(analysis)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Could not delete workspace analyses")
            flash("Saved analyses could not be deleted. Please try again.", "error")
            return redirect(url_for("history"))
        flash(f"Deleted {len(analyses)} saved analysis(es).", "success")
        return redirect(url_for("history"))

    @app.get("/health")
    def health():
        try:
            db.session.execute(db.select(Analysis.id).limit(1))
        except SQLAlchemyError:
            app.logger.exception("Health check database query failed")
            return {"status": "unhealthy"}, 503
        try:
            if not limiter.storage.check():
                app.logger.error("Health check rate-limit storage is unavailable")
                return {"status": "unhealthy"}, 503
        except RedisError:
            app.logger.exception("Health check rate-limit storage query failed")
            return {"status": "unhealthy"}, 503
        return {"status": "ok"}, 200

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", code=400, message=error.description), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, message="We couldn't find that page."), 404

    @app.errorhandler(429)
    def rate_limited(error):
        return (
            render_template(
                "error.html",
                code=429,
                message="Too many requests. Please wait a while before trying again.",
            ),
            429,
        )

    @app.errorhandler(413)
    def request_too_large(error):
        return (
            render_template(
                "error.html",
                code=413,
                message="That upload is too large. Please keep files under 1 MB.",
            ),
            413,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run()
