document.addEventListener("DOMContentLoaded", () => {
  const targetUrlInput = document.getElementById("targetUrl");
  const saveBtn = document.getElementById("saveBtn");
  const statusText = document.getElementById("statusText");

  // Load existing configuration
  chrome.storage.local.get(["targetUrl"], (result) => {
    const url = result.targetUrl || "http://localhost:4500";
    targetUrlInput.value = url;
    statusText.textContent = `Monitoring: ${url}`;
  });

  // Save new configuration
  saveBtn.addEventListener("click", () => {
    let url = targetUrlInput.value.trim();
    if (!url) {
      statusText.textContent = "Please enter a valid URL prefix!";
      return;
    }
    // Remove trailing slash to ensure robust prefix matching
    if (url.endsWith("/")) {
      url = url.slice(0, -1);
    }
    chrome.storage.local.set({ targetUrl: url }, () => {
      statusText.textContent = `Saved! Monitoring: ${url}`;
      
      // Notify active tabs to update their target URL immediately
      chrome.tabs.query({}, (tabs) => {
        for (const tab of tabs) {
          if (tab.id) {
            chrome.tabs.sendMessage(tab.id, { action: "update_target", targetUrl: url }).catch(() => {
              // Ignore tabs where content script isn't loaded
            });
          }
        }
      });
    });
  });
});
