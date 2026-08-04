let targetUrl = "http://localhost:4500";
let active = false;

// Cooldown state
let lastClickTime = 0;
let lastKeypressTime = 0;
const COOLDOWNS = {
  click: 2000,
  keypress: 5000
};

// Check if current URL matches the target URL, toggling activity monitoring
function checkAndSetup() {
  const currentUrl = window.location.href;
  const wasActive = active;
  active = currentUrl.startsWith(targetUrl);

  if (active && !wasActive) {
    console.log("[Activity Tracker] Monitoring started for this tab:", currentUrl);
    // Send immediate navigation screenshot when matched
    sendCapture("navigation");
  } else if (!active && wasActive) {
    console.log("[Activity Tracker] Monitoring stopped (navigated out of target domain):", currentUrl);
  }
}

function sendCapture(eventType) {
  if (!active) return;
  
  chrome.runtime.sendMessage({
    action: "capture",
    url: window.location.href,
    title: document.title,
    event: eventType
  }).catch(err => {
    // Silence error for context invalidation (e.g. when extension reloaded)
  });
}

// Listen for target URL updates from popup.js
chrome.runtime.onMessage.addListener((message) => {
  if (message.action === "update_target") {
    targetUrl = message.targetUrl;
    checkAndSetup();
  }
});

// Load storage setting and start
chrome.storage.local.get(["targetUrl"], (result) => {
  if (result.targetUrl) {
    targetUrl = result.targetUrl;
  }
  checkAndSetup();
});

// Listeners
document.addEventListener("click", () => {
  if (!active) return;
  const now = Date.now();
  if (now - lastClickTime > COOLDOWNS.click) {
    lastClickTime = now;
    // Minor delay (250ms) to capture the post-click visual state (e.g., opened menus, modal overlays)
    setTimeout(() => sendCapture("click"), 250);
  }
});

document.addEventListener("keypress", () => {
  if (!active) return;
  const now = Date.now();
  if (now - lastKeypressTime > COOLDOWNS.keypress) {
    lastKeypressTime = now;
    setTimeout(() => sendCapture("keypress"), 250);
  }
});

// Poller to detect dynamic SPA navigation changes (e.g. Next.js / React Router routes)
let lastUrl = window.location.href;
setInterval(() => {
  if (window.location.href !== lastUrl) {
    lastUrl = window.location.href;
    checkAndSetup();
  }
}, 500);
