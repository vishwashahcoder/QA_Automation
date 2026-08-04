chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "capture") {
    // Capture the visible viewport of the active tab in the current window
    chrome.tabs.captureVisibleTab(null, { format: "png" }, (dataUrl) => {
      if (chrome.runtime.lastError || !dataUrl) {
        console.warn("[Activity Tracker] Capture error:", chrome.runtime.lastError?.message || "No data URL returned.");
        return;
      }
      
      // POST the metadata and image base64 data to our local Python server
      fetch("http://localhost:8000/capture", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          url: request.url,
          title: request.title,
          event: request.event,
          screenshot: dataUrl
        })
      })
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        console.log("[Activity Tracker] Successfully logged activity to local server:", data);
      })
      .catch(err => {
        console.warn("[Activity Tracker] Failed to contact Python server (ensure python server is running):", err.message);
      });
    });
  }
});
