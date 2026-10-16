# InsightLens Chrome page capture

This unpacked Manifest V3 extension captures visible text from the active tab only after you click **Analyze this page**. It opens the local InsightLens app and submits the captured text through the normal CSRF-protected form; it does not contact a separate API or upload the page elsewhere.

## Install in Chrome

1. Start InsightLens locally with `python app.py` and confirm `http://127.0.0.1:5000` opens.
2. In Chrome, open `chrome://extensions`.
3. Turn on **Developer mode**, choose **Load unpacked**, and select this `chrome-extension` folder.
4. Open a page with readable text, select the InsightLens Page Capture icon, and click **Analyze this page**.

The extension requires the `activeTab` and `scripting` permissions to read the page after your click. Its host access is limited to the local InsightLens app at `127.0.0.1:5000` or `localhost:5000`. Pages Chrome marks as restricted may not be readable. The extension does not bypass sign-in, paywalls, CAPTCHAs, site restrictions, or browser security controls.

Captured text is limited to 100,000 characters and is submitted to the InsightLens instance running on the same computer. The app applies its existing analysis rate limit, CSRF protection, workspace privacy, and manual deletion controls. Loading this unpacked extension is intended for local demos; publish and review it separately before wider distribution.
