# InsightLens

InsightLens analyzes public webpages or pasted text. It classifies the content and switches between review-oriented aspect sentiment and general content summaries. The project is a working, heuristic MVP; the included evaluation set is a small, manually labelled regression baseline, not a claim of production-grade NLP accuracy.

## Capabilities

- Classify product/service reviews, blog posts, news, Bible commentary, research articles, and forum discussions.
- Analyze review aspects, polarity, example evidence, strengths, and weaknesses.
- Summarize informational content and extract recurring topics.
- Extract static HTML and optionally render JavaScript-heavy pages with Playwright/Chromium.
- Analyze uploaded UTF-8 text, CSV review exports, and `.docx` Word documents without retaining the original file.
- Capture visible page text in Chrome with the optional local browser extension, including sites that do not expose readable content to the server-side scraper.
- Store analysis history in SQLite by default, with PostgreSQL available for multi-worker deployments.
- Provide private anonymous browser workspaces without login, plus individual and bulk manual deletion.
- Apply CSRF checks, response security headers, request limits, outbound URL guards, and shared rate limiting.

### Anonymous workspace and privacy model

There is no account or login. A high-entropy workspace identifier is stored in Flask's signed, HTTP-only browser session cookie. Analyses and history are only returned to the browser that created them. If a visitor clears the cookie, changes to another browser/device, or the server's `SECRET_KEY` changes, they cannot recover that workspace. Users can delete individual analyses or all analyses in the current workspace; records are otherwise kept until deleted.

This is browser-scoped access control, not user authentication. Anyone who obtains a visitor's session cookie can access that visitor's workspace. Use HTTPS, keep the `SECRET_KEY` private and stable, and do not run a public service without the shared rate-limit backend. Add full accounts if recovery or cross-device access is required.

### Analysis limitations

The classification, sentiment, and summary components are deterministic lexical/extractive heuristics. Their scores are useful for triage and comparison, not calibrated probabilities or reliable business decisions. The evaluation fixtures cover representative cases but are not scraped or independently audited target-site data. Browser rendering and the optional Chrome extension can read only text available to the browser; neither bypasses logins, CAPTCHAs, paywalls, or site restrictions.

### Upload review files

Choose one `.txt`, `.csv`, or `.docx` file in the analysis form. Uploads are limited to 1 MB and the extracted text to 100,000 characters. CSV files with a `review`, `text`, `content`, `comment`, `feedback`, or similar column analyze those cells; when there is no recognized text column, non-empty row cells are combined. Text and CSV uploads must be UTF-8. Legacy `.doc` files, spreadsheets, and PDFs are not supported. The original file is read in memory for analysis and is not written to disk; the generated analysis report is saved to the current browser workspace as usual.

### Chrome extension for live demos

For pages visible in Chrome that the server-side fetcher cannot read, load the unpacked extension in `chrome-extension/` (see its [installation guide](./chrome-extension/README.md)). Clicking **Analyze this page** captures visible text from the current tab, opens the local InsightLens page, and submits through the normal CSRF-protected form. The extension is limited to the local app at `127.0.0.1:5000` or `localhost:5000`; it does not send page text to a third-party service. It asks for access to the active tab only when clicked. Chrome-restricted pages may not allow capture.

## Run locally (Windows PowerShell)

Python 3.10 or newer is recommended.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
$env:SECRET_KEY = (python -c "import secrets; print(secrets.token_urlsafe(48))")
flask --app app db upgrade
python app.py
```

Open http://127.0.0.1:5000. The application requires database migrations before the first run. `instance/analyses.db` is used by default for local development.

If Chromium is not installed, set `$env:DYNAMIC_EXTRACTION_ENABLED = "false"` to use static HTML extraction only. The browser fallback is used when static extraction fails or finds fewer than 40 readable words.

## Tests and evaluation

```powershell
python -m pytest
python evaluate.py
python evaluate.py --live
```

`evaluate.py` reports exact-match classification accuracy, aspect-sentiment accuracy, and key-term coverage for the labelled fixtures in `tests/data/`. These small regression sets guard against known cases; expand them with reviewed, representative examples from the actual target sites before relying on the metrics.
The optional `--live` check also fetches the public JavaScript-rendered Quotes to Scrape demo to smoke-test the Chromium fallback; it is not a substitute for validating target review websites.

## Database migrations

Apply migrations with:

```powershell
flask --app app db upgrade
```

Create a new migration after changing a model:

```powershell
flask --app app db migrate -m "describe schema change"
flask --app app db upgrade
```

Review generated migrations before applying them, back up the database first, and commit migration scripts with model changes. Do not use `db.create_all()` as a production schema-management strategy.

### Existing pre-migration database

The first migration is a baseline that creates the original schema on a fresh database. For an existing InsightLens SQLite database whose schema was created by the earlier MVP, stamp that baseline once before applying later migrations:

```powershell
flask --app app db stamp <baseline-revision>
flask --app app db upgrade
```

Replace `<baseline-revision>` with the revision identifier documented in `migrations/versions/`. Stamping records the existing schema version; it does not modify or delete existing analysis rows. Legacy rows without an anonymous workspace remain preserved in the database but are not exposed to browser workspaces.

## Production deployment

1. Use a managed PostgreSQL database and Redis-compatible shared rate-limit store. Configure `DATABASE_URL` and `RATELIMIT_STORAGE_URI` as shown in `.env.example`.
2. Set `APP_ENV=production`, a stable random `SECRET_KEY` of at least 32 characters, and `COOKIE_SECURE=true`. Production startup refuses a missing/short key or in-memory rate limiting.
3. Install the OS packages required by Playwright and run `python -m playwright install chromium` as part of image provisioning. Keep the application process unprivileged and apply outbound network/firewall controls. The scraper rejects private addresses and validates browser subrequests; host-level egress restrictions provide defense in depth against DNS rebinding.
4. Back up the database, then run `flask --app app db upgrade` as a release step.
5. Serve `wsgi:app` with Waitress behind a TLS-terminating reverse proxy. Trust forwarded proxy headers only when the configured proxy is controlled by you; set `TRUSTED_PROXY_COUNT` to its exact trusted hop count. Do not expose the Waitress port directly to the Internet.

Example environment setup:

```powershell
$env:APP_ENV = "production"
$env:SECRET_KEY = "<stable-secret-from-your-secret-manager>"
$env:DATABASE_URL = "postgresql+psycopg://user:password@db-host:5432/insightlens"
$env:RATELIMIT_STORAGE_URI = "redis://redis-host:6379/0"
$env:COOKIE_SECURE = "true"
$env:TRUSTED_PROXY_COUNT = "1"
flask --app app db upgrade
waitress-serve --listen=127.0.0.1:8000 wsgi:app
```

For local use of the production WSGI server, `waitress-serve --listen=127.0.0.1:8000 wsgi:app` is also available. The built-in `python app.py` server is for development only.

### Deploy a free demo on Render

The root-level `render.yaml` defines a free Render web service, PostgreSQL database, and private Key Value store. Its current resource names use the `insightlens-demo2` prefix so they can be deployed as a separate Blueprint from an older InsightLens deployment. To create it:

1. Put this project in a GitHub repository. Do not upload `.env`, `.venv`, or local database files.
2. In the [Render Dashboard](https://dashboard.render.com), choose **New > Blueprint**, connect the repository, and select **Deploy Blueprint** to create the new resources.
3. Wait for the first deploy to finish, then open the `onrender.com` URL shown for the `insightlens-demo2` web service. The service applies database migrations during startup.

This creates a fresh database and does not restore data from any previous Render deployment. This is for demos, not durable production use. Render's free web service sleeps after 15 minutes without traffic, and its filesystem is temporary. The Blueprint uses Render's free PostgreSQL, which expires 30 days after creation; after its 14-day upgrade grace period Render deletes it and its data. The free Key Value store is in-memory and can lose its rate-limit counters when it restarts. Upgrade the database before it expires if you need to keep data. Dynamic browser rendering is disabled on this free setup; static webpage extraction and pasted-text analysis remain available.

## Project layout

```text
app.py                         Flask application factory and routes
config.py                      Environment-based settings
database.py                    SQLAlchemy and migration extensions
models.py                      Analysis and aspect data models
migrations/                    Reviewed Alembic schema migrations
services/classifier.py         Page-type classification
services/sentiment.py          Aspect extraction and sentiment heuristics
services/summarizer.py         Extractive summaries and topics
services/extractor.py          Safe static and browser-based extraction
services/analytics.py          Sentiment metrics
templates/                     Jinja pages
static/                        Responsive UI
chrome-extension/              Optional Chrome page-capture extension
tests/                         Application, quality, and security regressions
tests/data/                    Hand-labelled evaluation fixtures
wsgi.py                        Production WSGI entry point
```
