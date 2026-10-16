const APP_URL = "http://127.0.0.1:5000/";
const MAX_TEXT_LENGTH = 100000;
const button = document.getElementById("analyze");
const status = document.getElementById("status");

function waitForTab(tabId) {
  return new Promise((resolve, reject) => {
    let timeoutId;
    const cleanup = () => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      clearTimeout(timeoutId);
    };
    const onUpdated = (updatedTabId, changeInfo) => {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        cleanup();
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(onUpdated);
    timeoutId = setTimeout(() => {
      cleanup();
      reject(new Error("InsightLens did not finish loading. Make sure it is running on port 5000."));
    }, 15000);
    chrome.tabs.get(tabId, tab => {
      if (chrome.runtime.lastError) {
        cleanup();
        reject(new Error(chrome.runtime.lastError.message));
      } else if (tab.status === "complete") {
        cleanup();
        resolve();
      }
    });
  });
}

button.addEventListener("click", async () => {
  button.disabled = true;
  status.classList.remove("error");
  status.textContent = "Reading the current page…";
  let appTab;
  try {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!activeTab?.id) {
      throw new Error("No active browser tab was found.");
    }
    const [captured] = await chrome.scripting.executeScript({
      target: { tabId: activeTab.id },
      func: maxLength => {
        const originalText = document.body?.innerText?.trim() || "";
        return {
          title: document.title || location.hostname,
          url: location.href,
          text: originalText.slice(0, maxLength),
          truncated: originalText.length > maxLength
        };
      },
      args: [MAX_TEXT_LENGTH]
    });
    if (!captured?.result?.text) {
      throw new Error("No readable page text was found. Open a page with visible text and try again.");
    }
    status.textContent = captured.result.truncated
      ? "Text captured (limited to 100,000 characters); opening InsightLens…"
      : "Text captured; opening InsightLens…";
    appTab = await chrome.tabs.create({ url: APP_URL, active: false });
    await waitForTab(appTab.id);
    const [submission] = await chrome.scripting.executeScript({
      target: { tabId: appTab.id },
      func: page => {
        const form = document.querySelector("#analysis-form");
        const text = document.querySelector("#text");
        const sourceUrl = document.querySelector("#captured-url");
        const title = document.querySelector("#captured-title");
        if (!form || !text || !sourceUrl || !title) {
          return { error: "The open app does not have the page-capture form. Reload InsightLens and try again." };
        }
        text.value = page.text;
        text.dispatchEvent(new Event("input", { bubbles: true }));
        sourceUrl.value = page.url;
        title.value = page.title;
        form.requestSubmit();
        return { submitted: true };
      },
      args: [captured.result]
    });
    if (submission?.result?.error) {
      throw new Error(submission.result.error);
    }
    await chrome.tabs.update(appTab.id, { active: true });
    status.textContent = "Sent. InsightLens is preparing the analysis.";
  } catch (error) {
    if (appTab?.id) {
      await chrome.tabs.remove(appTab.id).catch(() => {});
    }
    status.classList.add("error");
    status.textContent = error.message || "Could not send this page to InsightLens.";
    button.disabled = false;
  }
});
