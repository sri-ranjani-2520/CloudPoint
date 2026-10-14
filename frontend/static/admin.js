(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root && root.document) {
    const start = () => api.createAdminUI({ document: root.document, fetch: root.fetch.bind(root) }).init();
    if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", start, { once: true });
    else start();
  }
})(typeof window === "undefined" ? null : window, function () {
  "use strict";

  const STATUSES = ["Submitted", "Under Review", "In Progress", "Resolved", "Rejected"];
  const MAX_SEARCH_LENGTH = 160;
  const STATUS_COUNT_IDS = {
    Submitted: "count-submitted",
    "Under Review": "count-under-review",
    "In Progress": "count-in-progress",
    Resolved: "count-resolved",
    Rejected: "count-rejected"
  };

  function createAdminUI({ document, fetch: fetchImpl, apiBase = "/api" }) {
    let token = null;
    let currentCursor = null;
    let cursorHistory = [];
    let nextCursor = null;
    let activeComplaintId = null;
    let detailReturnFocus = null;
    const base = apiBase.replace(/\/$/, "");
    const byId = (id) => document.getElementById(id);

    function announce(id, message, success = false) {
      const element = byId(id);
      element.textContent = message;
      element.classList.toggle("success", success);
    }

    async function request(path, { auth = false, ...options } = {}) {
      const headers = { Accept: "application/json", ...(options.headers || {}) };
      if (auth && token) headers.Authorization = `Bearer ${token}`;
      let response;
      try {
        response = await fetchImpl(`${base}${path}`, {
          ...options,
          credentials: "omit",
          headers
        });
      } catch {
        throw new Error("The service could not be reached. Check the connection and try again.");
      }
      let body;
      try {
        body = await response.json();
      } catch {
        throw new Error("The service returned an unreadable response. Please try again.");
      }
      if (!response.ok) {
        const details = body?.error?.details;
        const message = details ? Object.values(details).join(" ") : body?.error?.message;
        const error = new Error(message || "The request could not be completed.");
        error.status = response.status;
        throw error;
      }
      return body;
    }

    function showLogin(message = "") {
      token = null;
      activeComplaintId = null;
      byId("admin-workspace").hidden = true;
      byId("admin-login-panel").hidden = false;
      byId("complaint-detail").hidden = true;
      byId("complaint-rows").replaceChildren();
      announce("admin-login-message", message);
      byId("login-title").focus();
      byId("admin-login-panel").scrollIntoView?.({ behavior: "smooth", block: "start" });
    }

    function expireSession() {
      showLogin("Your session has expired. Sign in again to continue.");
    }

    function protectedError(error, targetId) {
      if (error && error.status === 401) {
        expireSession();
      } else {
        announce(targetId, error?.message || "The request could not be completed.");
      }
    }

    function setBusy(id, busy) {
      byId(id).setAttribute("aria-busy", String(busy));
    }

    async function loadDashboard() {
      setBusy("admin-stats", true);
      announce("admin-workspace-message", "Loading dashboard…");
      byId("count-total").textContent = "—";
      for (const id of Object.values(STATUS_COUNT_IDS)) byId(id).textContent = "—";
      try {
        const counts = await request("/admin/dashboard", { auth: true });
        byId("count-total").textContent = String(counts.total);
        for (const [status, id] of Object.entries(STATUS_COUNT_IDS)) {
          byId(id).textContent = String(counts[status]);
        }
        announce("admin-workspace-message", "Dashboard updated.", true);
      } catch (error) {
        protectedError(error, "admin-workspace-message");
      } finally {
        setBusy("admin-stats", false);
      }
    }

    function queryString() {
      const data = new FormData(byId("complaint-filters"));
      const query = new URLSearchParams();
      for (const key of ["search", "category", "status"]) {
        const value = String(data.get(key) || "").trim();
        if (value) query.set(key, value);
      }
      query.set("limit", "25");
      if (currentCursor) query.set("cursor", currentCursor);
      return query.toString();
    }

    function cell(row, value, className = "") {
      const item = document.createElement("td");
      if (className) item.className = className;
      item.textContent = value == null ? "" : String(value);
      row.appendChild(item);
      return item;
    }

    function formatTimestamp(value) {
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? String(value || "—") : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium", timeStyle: "short"
      }).format(date);
    }

    function renderComplaints(items, hasMore) {
      const rows = byId("complaint-rows");
      rows.replaceChildren();
      if (!items.length) {
        const row = document.createElement("tr");
        const emptyMessage = hasMore ? "No complaints on this page. Continue to the next page." : "No complaints match these filters.";
        const empty = cell(row, emptyMessage, "table-empty");
        empty.colSpan = 8;
        rows.appendChild(row);
        return;
      }
      for (const complaint of items) {
        const row = document.createElement("tr");
        cell(row, complaint.complaint_id, "complaint-id-cell");
        cell(row, complaint.title, "complaint-title-cell");
        cell(row, complaint.registration_number);
        cell(row, complaint.category);
        const status = cell(row, complaint.status, "status-cell");
        status.dataset.status = complaint.status;
        cell(row, formatTimestamp(complaint.created_at));
        cell(row, formatTimestamp(complaint.modified_at));
        const action = cell(row, "");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "text-button";
        button.textContent = "View details";
        button.setAttribute("aria-label", `View complaint ${complaint.complaint_id}`);
        button.addEventListener("click", () => {
          detailReturnFocus = button;
          return loadDetail(complaint.complaint_id);
        });
        action.appendChild(button);
        rows.appendChild(row);
      }
    }

    async function loadComplaints() {
      setBusy("complaint-list-region", true);
      byId("filter-submit").disabled = true;
      byId("complaint-rows").replaceChildren();
      byId("page-next").disabled = true;
      byId("page-previous").disabled = true;
      announce("complaint-list-message", "Loading complaints…");
      try {
        const page = await request(`/admin/complaints?${queryString()}`, { auth: true });
        renderComplaints(page.items, Boolean(page.next_cursor));
        nextCursor = page.next_cursor;
        byId("page-label").textContent = `Page ${cursorHistory.length + 1}`;
        byId("page-previous").disabled = cursorHistory.length === 0;
        byId("page-next").disabled = !nextCursor;
        const resultMessage = page.items.length
          ? `${page.items.length} complaint(s) shown.`
          : page.next_cursor
            ? "No matches on this page; more results may follow."
            : "No complaints match the current search or filters.";
        announce("complaint-list-message", resultMessage, true);
      } catch (error) {
        protectedError(error, "complaint-list-message");
      } finally {
        setBusy("complaint-list-region", false);
        byId("filter-submit").disabled = false;
      }
    }

    function setDetail(record) {
      activeComplaintId = record.complaint_id;
      const values = {
        "detail-id": record.complaint_id,
        "detail-student": record.student_name,
        "detail-registration": record.registration_number,
        "detail-category": record.category,
        "detail-location": record.location,
        "detail-created": formatTimestamp(record.created_at),
        "detail-modified": formatTimestamp(record.modified_at),
        "detail-title": record.title,
        "detail-description": record.description,
        "detail-rejection": record.rejection_reason || ""
      };
      for (const [id, value] of Object.entries(values)) byId(id).textContent = String(value || "");
      byId("detail-rejection-view").hidden = record.status !== "Rejected";
      byId("status-select").value = record.status;
      byId("rejection-reason").value = record.status === "Rejected" ? record.rejection_reason || "" : "";
      syncRejectionField();
      byId("complaint-detail").hidden = false;
      byId("detail-heading").focus();
    }

    async function loadDetail(complaintId) {
      activeComplaintId = complaintId;
      byId("complaint-detail").hidden = false;
      for (const id of ["detail-id", "detail-student", "detail-registration", "detail-category", "detail-location", "detail-created", "detail-modified", "detail-title", "detail-description", "detail-rejection"]) {
        byId(id).textContent = "";
      }
      byId("detail-rejection-view").hidden = true;
      announce("detail-message", "Loading complaint details…");
      try {
        const record = await request(`/admin/complaints/${encodeURIComponent(complaintId)}`, { auth: true });
        setDetail(record);
        announce("detail-message", "Complaint details loaded.", true);
        byId("complaint-detail").scrollIntoView?.({ behavior: "smooth", block: "start" });
      } catch (error) {
        protectedError(error, "detail-message");
      }
    }

    function syncRejectionField() {
      const required = byId("status-select").value === "Rejected";
      byId("rejection-reason-field").hidden = !required;
      byId("rejection-reason").required = required;
    }

    async function updateStatus(event) {
      event.preventDefault();
      if (!activeComplaintId) return;
      const status = byId("status-select").value;
      const rejectionReason = byId("rejection-reason").value.trim();
      if (!STATUSES.includes(status)) {
        announce("detail-message", "Choose a supported complaint status.");
        return;
      }
      if (status === "Rejected" && !rejectionReason) {
        announce("detail-message", "Enter a rejection reason before rejecting this complaint.");
        byId("rejection-reason").focus();
        return;
      }
      const button = byId("status-update-button");
      button.disabled = true;
      announce("detail-message", "Saving status…");
      const body = { status };
      if (status === "Rejected") body.rejection_reason = rejectionReason;
      try {
        const updated = await request(`/admin/complaints/${encodeURIComponent(activeComplaintId)}/status`, {
          auth: true,
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
        setDetail(updated);
        announce("detail-message", "Complaint status updated.", true);
        await Promise.all([loadDashboard(), loadComplaints()]);
      } catch (error) {
        protectedError(error, "detail-message");
      } finally {
        button.disabled = false;
      }
    }

    async function login(event) {
      event.preventDefault();
      const form = byId("admin-login-form");
      const button = byId("admin-login-button");
      const data = new FormData(form);
      button.disabled = true;
      announce("admin-login-message", "Signing in…");
      try {
        const session = await request("/admin/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: data.get("username"), password: data.get("password") })
        });
        if (typeof session.access_token !== "string" || session.token_type !== "Bearer") {
          throw new Error("The server returned an invalid session response.");
        }
        token = session.access_token;
        form.reset();
        byId("admin-login-panel").hidden = true;
        byId("admin-workspace").hidden = false;
        byId("dashboard-title").focus();
        cursorHistory = [];
        currentCursor = null;
        await Promise.all([loadDashboard(), loadComplaints()]);
      } catch (error) {
        announce("admin-login-message", error?.message || "Sign in failed. Check your credentials and try again.");
      } finally {
        button.disabled = false;
        button.textContent = "Sign in";
      }
    }

    async function logout() {
      const button = byId("admin-logout-button");
      button.disabled = true;
      announce("admin-workspace-message", "Signing out…");
      try {
        await request("/admin/logout", { auth: true, method: "POST" });
        showLogin("You have signed out.");
      } catch (error) {
        if (error && error.status === 401) expireSession();
        else announce("admin-workspace-message", error?.message || "Sign out could not be confirmed. Please retry.");
      } finally {
        button.disabled = false;
      }
    }

    function init() {
      byId("admin-login-form").addEventListener("submit", login);
      byId("admin-logout-button").addEventListener("click", logout);
      byId("complaint-filters").addEventListener("submit", (event) => {
        event.preventDefault();
        const search = String(new FormData(byId("complaint-filters")).get("search") || "").trim();
        if (search.length > MAX_SEARCH_LENGTH) {
          announce("complaint-list-message", "Search text must be at most 160 characters.");
          byId("complaint-search").focus();
          return;
        }
        cursorHistory = [];
        currentCursor = null;
        return loadComplaints();
      });
      byId("filter-clear").addEventListener("click", () => {
        byId("complaint-filters").reset();
        cursorHistory = [];
        currentCursor = null;
        return loadComplaints();
      });
      byId("page-next").addEventListener("click", () => {
        if (!nextCursor) return;
        cursorHistory.push(currentCursor);
        currentCursor = nextCursor;
        return loadComplaints();
      });
      byId("page-previous").addEventListener("click", () => {
        if (!cursorHistory.length) return;
        currentCursor = cursorHistory.pop();
        return loadComplaints();
      });
      byId("status-select").addEventListener("change", syncRejectionField);
      byId("status-update-form").addEventListener("submit", updateStatus);
      byId("detail-close").addEventListener("click", () => {
        activeComplaintId = null;
        byId("complaint-detail").hidden = true;
        if (detailReturnFocus && detailReturnFocus.isConnected !== false) detailReturnFocus.focus();
        else byId("complaints-title").focus();
      });
      syncRejectionField();
    }

    return { init };
  }

  return { createAdminUI };
});
