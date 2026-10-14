(() => {
  "use strict";

  const apiBase = (window.CLOUDPOINT_CONFIG?.apiBaseUrl || "/api").replace(/\/$/, "");
  const byId = (id) => document.getElementById(id);

  function announce(element, message, success = false) {
    element.textContent = message;
    element.classList.toggle("success", success);
  }

  async function request(path, options = {}) {
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      credentials: "omit",
      headers: { Accept: "application/json", ...(options.headers || {}) }
    });
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error("The server returned an unreadable response. Please try again.");
    }
    if (!response.ok) {
      const details = result?.error?.details;
      const fieldMessage = details ? Object.values(details).join(" ") : "";
      throw new Error(fieldMessage || result?.error?.message || "The request could not be completed.");
    }
    return result;
  }

  byId("complaint-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = byId("submit-button");
    const form = event.currentTarget;
    const message = byId("submit-message");
    const confirmation = byId("submission-confirmation");
    confirmation.hidden = true;
    announce(message, "");
    form.setAttribute("aria-busy", "true");
    button.disabled = true;
    button.textContent = "Sending...";
    const fields = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      const response = await request("/complaints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields)
      });
      byId("new-complaint-id").textContent = response.complaint_id;
      byId("tracking-id").value = response.complaint_id;
      confirmation.hidden = false;
      announce(message, "Your complaint was submitted.", true);
      confirmation.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      announce(message, error.message || "Unable to submit right now. Please try again.");
    } finally {
      form.setAttribute("aria-busy", "false");
      button.disabled = false;
      button.textContent = "Send complaint";
    }
  });

  byId("tracking-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = byId("track-button");
    const form = event.currentTarget;
    const message = byId("tracking-message");
    const resultPanel = byId("tracking-result");
    resultPanel.hidden = true;
    announce(message, "");
    form.setAttribute("aria-busy", "true");
    button.disabled = true;
    button.textContent = "Checking...";
    const complaintId = byId("tracking-id").value.trim();
    try {
      const record = await request(`/complaints/${encodeURIComponent(complaintId)}`);
      byId("result-title").textContent = record.title;
      byId("result-status").textContent = record.status;
      byId("result-id").textContent = record.complaint_id;
      byId("result-category").textContent = record.category;
      byId("result-location").textContent = record.location;
      byId("result-created").textContent = formatTimestamp(record.created_at);
      byId("result-description").textContent = record.description;
      const isRejected = record.status === "Rejected" && Boolean(record.rejection_reason);
      byId("rejection-row").hidden = !isRejected;
      byId("result-rejection").textContent = isRejected ? record.rejection_reason : "";
      resultPanel.hidden = false;
      resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      announce(message, error.message || "Unable to retrieve this complaint. Please try again.");
    } finally {
      form.setAttribute("aria-busy", "false");
      button.disabled = false;
      button.textContent = "Track";
    }
  });

  function formatTimestamp(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium", timeStyle: "short"
    }).format(date);
  }
})();
