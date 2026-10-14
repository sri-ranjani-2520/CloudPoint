const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createAdminUI } = require("../frontend/static/admin.js");

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.listeners = {};
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.classList = { toggle() {} };
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.textContent = "";
    this.fields = {};
  }
  set innerHTML(_value) { throw new Error("unsafe innerHTML rendering attempted"); }
  get innerHTML() { return undefined; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  scrollIntoView() {}
  focus() { this.focused = true; }
  reset() { this.fields = {}; }
  async dispatch(name, event = {}) {
    const callback = this.listeners[name];
    assert.ok(callback, `missing ${name} handler for ${this.id}`);
    await callback({ preventDefault() {}, ...event });
  }
}

class FakeDocument {
  constructor() { this.elements = new Map(); }
  getElementById(id) {
    if (!this.elements.has(id)) this.elements.set(id, new FakeElement(id));
    return this.elements.get(id);
  }
  createElement(name) { return new FakeElement(name); }
}

global.FormData = class {
  constructor(form) { this.form = form; }
  get(name) { return this.form.fields[name] || ""; }
};

function setup(fetchImpl) {
  const document = new FakeDocument();
  document.getElementById("admin-workspace").hidden = true;
  document.getElementById("complaint-detail").hidden = true;
  const ui = createAdminUI({ document, fetch: fetchImpl });
  ui.init();
  return document;
}

function jsonResponse(value, status = 200) {
  return { ok: status >= 200 && status < 300, status, async json() { return value; } };
}

const sampleListItem = {
  complaint_id: "CP-abcdefghijklmnop",
  title: "<img src=x onerror=alert(1)>",
  registration_number: "REG-7",
  category: "Infrastructure",
  status: "Submitted",
  created_at: "2026-10-09T10:00:00+00:00",
  modified_at: "2026-10-09T10:00:00+00:00"
};

const sampleDetail = {
  ...sampleListItem,
  student_name: "Example Student",
  description: "<script>alert('x')</script> Broken campus light",
  location: "North Block",
  modified_at: "2026-10-09T10:00:00+00:00",
  rejection_reason: null
};

test("search UI accepts 160 characters and blocks 161 before sending a request", async () => {
  const html = fs.readFileSync(path.join(__dirname, "../frontend/admin.html"), "utf8");
  assert.match(html, /id="complaint-search"[^>]*maxlength="160"/);

  const requests = [];
  const fetchImpl = async (url) => {
    requests.push(url);
    if (url.endsWith("/admin/login")) return jsonResponse({ access_token: "opaque-token", token_type: "Bearer", expires_in: 1800 });
    if (url.endsWith("/admin/dashboard")) return jsonResponse({ total: 0, Submitted: 0, "Under Review": 0, "In Progress": 0, Resolved: 0, Rejected: 0 });
    if (url.includes("/admin/complaints?")) return jsonResponse({ items: [], next_cursor: null });
    throw new Error(`unexpected request: ${url}`);
  };
  const document = setup(fetchImpl);
  const login = document.getElementById("admin-login-form");
  login.fields = { username: "admin", password: "test" };
  await login.dispatch("submit");

  const filters = document.getElementById("complaint-filters");
  filters.fields = { search: "x".repeat(160) };
  await filters.dispatch("submit");
  const searchRequest = requests.find((url) => url.includes("/admin/complaints?") && url.includes("search="));
  assert.ok(searchRequest);
  assert.equal(new URL(searchRequest, "https://local.test").searchParams.get("search").length, 160);

  const listingRequestsBeforeInvalidSearch = requests.filter((url) => url.includes("/admin/complaints?")).length;
  filters.fields = { search: "x".repeat(161) };
  await filters.dispatch("submit");
  const listingRequestsAfterInvalidSearch = requests.filter((url) => url.includes("/admin/complaints?")).length;
  assert.equal(listingRequestsAfterInvalidSearch, listingRequestsBeforeInvalidSearch);
  assert.match(document.getElementById("complaint-list-message").textContent, /at most 160 characters/i);
  assert.equal(document.getElementById("complaint-search").focused, true);
});

test("administrator feedback is associated with controls and busy/list states are announced", () => {
  const html = fs.readFileSync(path.join(__dirname, "../frontend/admin.html"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "../frontend/static/styles.css"), "utf8");
  assert.match(html, /id="admin-login-message" role="status" aria-live="polite"/);
  assert.match(html, /name="username"[^>]*aria-describedby="admin-login-message"/);
  assert.match(html, /name="password"[^>]*aria-describedby="admin-login-message"/);
  assert.match(html, /id="complaint-list-message" role="status" aria-live="polite"/);
  assert.match(html, /id="complaint-search"[^>]*aria-describedby="complaint-list-message"/);
  assert.match(html, /aria-busy="false" id="complaint-list-region"/);
  assert.match(html, /id="detail-message" role="status" aria-live="polite"/);
  assert.match(html, /id="status-select"[^>]*aria-describedby="detail-message"/);
  assert.match(html, /id="rejection-reason"[^>]*aria-describedby="detail-message"/);
  assert.match(css, /\.table-scroll\s*\{[^}]*overflow-x:\s*auto/);
  assert.match(css, /@media\s*\(max-width:\s*440px\)/);
  assert.match(css, /:focus-visible\s*\{[^}]*outline/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
});

test("administrator list exposes every supported status and category filter", () => {
  const html = fs.readFileSync(path.join(__dirname, "../frontend/admin.html"), "utf8");
  const filters = html.match(/<form id="complaint-filters"[\s\S]*?<\/form>/)?.[0] || "";
  assert.match(filters, /<select name="status">[\s\S]*?<option>Rejected<\/option>/);
  assert.match(filters, /<option>Cleanliness<\/option>/);
  assert.doesNotMatch(filters, /name="student_name"/);
});

test("login loads protected dashboard/list and renders complaint content as text", async () => {
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith("/admin/login")) return jsonResponse({ access_token: "opaque-token", token_type: "Bearer", expires_in: 1800 });
    if (url.endsWith("/admin/dashboard")) return jsonResponse({ total: 1, Submitted: 1, "Under Review": 0, "In Progress": 0, Resolved: 0, Rejected: 0 });
    if (url.includes("/admin/complaints?")) return jsonResponse({ items: [sampleListItem], next_cursor: null });
    throw new Error(`unexpected request: ${url}`);
  };
  const document = setup(fetchImpl);
  const login = document.getElementById("admin-login-form");
  login.fields = { username: "admin", password: "secret entered by test" };
  await login.dispatch("submit");

  assert.equal(document.getElementById("admin-workspace").hidden, false);
  assert.equal(document.getElementById("count-total").textContent, "1");
  assert.equal(document.getElementById("dashboard-title").focused, true);
  assert.equal(document.getElementById("complaint-rows").children.length, 1);
  const cells = document.getElementById("complaint-rows").children[0].children;
  assert.equal(cells[0].textContent, sampleListItem.complaint_id);
  assert.equal(cells[1].textContent, sampleListItem.title);
  assert.equal(cells[1].children.length, 0);
  assert.equal(requests[1].options.headers.Authorization, "Bearer opaque-token");
  assert.equal(requests[0].options.credentials, "omit");
  assert.equal(requests[0].url.includes("secret entered by test"), false);
});

test("filters, cursor pagination, detail rendering, and rejection validation use existing contracts", async () => {
  const requests = [];
  let listCall = 0;
  const fetchImpl = async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith("/admin/login")) return jsonResponse({ access_token: "opaque-token", token_type: "Bearer", expires_in: 1800 });
    if (url.endsWith("/admin/dashboard")) return jsonResponse({ total: 1, Submitted: 1, "Under Review": 0, "In Progress": 0, Resolved: 0, Rejected: 0 });
    if (url.includes("/admin/complaints?")) {
      listCall += 1;
      return listCall === 3
        ? jsonResponse({ items: [], next_cursor: "cursor-3" })
        : jsonResponse({ items: [sampleListItem], next_cursor: "cursor-2" });
    }
    if (url.endsWith("/admin/complaints/CP-abcdefghijklmnop")) return jsonResponse(sampleDetail);
    if (url.endsWith("/status")) return jsonResponse({ ...sampleDetail, status: "Rejected", rejection_reason: "Reason supplied" });
    throw new Error(`unexpected request: ${url}`);
  };
  const document = setup(fetchImpl);
  const login = document.getElementById("admin-login-form");
  login.fields = { username: "admin", password: "not retained" };
  await login.dispatch("submit");

  const filters = document.getElementById("complaint-filters");
  filters.fields = { search: "broken", category: "Infrastructure", status: "Submitted" };
  await filters.dispatch("submit");
  const filteredRequest = requests.find((item) => item.url.includes("search=broken"));
  assert.ok(filteredRequest);
  const filterUrl = new URL(filteredRequest.url, "https://local.test");
  assert.equal(filterUrl.searchParams.get("category"), "Infrastructure");
  assert.equal(filterUrl.searchParams.get("status"), "Submitted");

  await document.getElementById("page-next").dispatch("click");
  assert.ok(requests.some((item) => item.url.includes("cursor=cursor-2")));
  assert.equal(document.getElementById("page-next").disabled, false);
  assert.match(document.getElementById("complaint-list-message").textContent, /more results may follow/i);
  await document.getElementById("page-previous").dispatch("click");

  const detailButton = document.getElementById("complaint-rows").children[0].children[7].children[0];
  await detailButton.dispatch("click");
  assert.equal(document.getElementById("detail-heading").focused, true);
  assert.equal(document.getElementById("detail-description").textContent, sampleDetail.description);
  assert.equal(document.getElementById("detail-description").children.length, 0);
  await document.getElementById("detail-close").dispatch("click");
  assert.equal(detailButton.focused, true);
  await detailButton.dispatch("click");

  document.getElementById("status-select").value = "Not a status";
  await document.getElementById("status-update-form").dispatch("submit");
  assert.match(document.getElementById("detail-message").textContent, /supported complaint status/i);
  assert.equal(requests.some((item) => item.url.endsWith("/status")), false);

  document.getElementById("status-select").value = "Rejected";
  await document.getElementById("status-update-form").dispatch("submit");
  assert.match(document.getElementById("detail-message").textContent, /rejection reason/i);
  assert.equal(requests.some((item) => item.url.endsWith("/status")), false);

  document.getElementById("rejection-reason").value = "Reason supplied";
  await document.getElementById("status-update-form").dispatch("submit");
  const update = requests.find((item) => item.url.endsWith("/status"));
  assert.equal(update.options.method, "PATCH");
  assert.deepEqual(JSON.parse(update.options.body), { status: "Rejected", rejection_reason: "Reason supplied" });
});

test("invalid credentials and expired sessions remain explicit", async () => {
  let fetchImpl = async (url) => {
    if (url.endsWith("/admin/login")) return jsonResponse({ error: { message: "Invalid username or password." } }, 401);
    if (url.endsWith("/admin/dashboard")) return jsonResponse({ error: { message: "Administrator authentication is required." } }, 401);
    if (url.includes("/admin/complaints?")) return jsonResponse({ items: [], next_cursor: null });
    throw new Error(`unexpected request: ${url}`);
  };
  const document = setup(fetchImpl);
  const login = document.getElementById("admin-login-form");
  login.fields = { username: "admin", password: "bad password" };
  await login.dispatch("submit");
  assert.match(document.getElementById("admin-login-message").textContent, /Invalid username or password/);
  assert.equal(document.getElementById("admin-workspace").hidden, true);

  // A valid-looking login followed by a protected 401 must return to login.
  let protectedRequest = false;
  fetchImpl = async (url) => {
    if (url.endsWith("/admin/login")) return jsonResponse({ access_token: "token", token_type: "Bearer", expires_in: 1800 });
    if (url.endsWith("/admin/dashboard")) {
      protectedRequest = true;
      return jsonResponse({ error: { message: "Administrator authentication is required." } }, 401);
    }
    if (url.includes("/admin/complaints?")) return jsonResponse({ items: [], next_cursor: null });
    throw new Error(`unexpected request: ${url}`);
  };
  const expiredDocument = setup(fetchImpl);
  const expiredLogin = expiredDocument.getElementById("admin-login-form");
  expiredLogin.fields = { username: "admin", password: "test" };
  await expiredLogin.dispatch("submit");
  assert.equal(expiredDocument.getElementById("admin-workspace").hidden, true);
  assert.match(expiredDocument.getElementById("admin-login-message").textContent, /session has expired/i);
  assert.equal(protectedRequest, true);
});

test("logout sends revocation request and returns to the login screen only after confirmation", async () => {
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith("/admin/login")) return jsonResponse({ access_token: "opaque-token", token_type: "Bearer", expires_in: 1800 });
    if (url.endsWith("/admin/dashboard")) return jsonResponse({ total: 0, Submitted: 0, "Under Review": 0, "In Progress": 0, Resolved: 0, Rejected: 0 });
    if (url.includes("/admin/complaints?")) return jsonResponse({ items: [], next_cursor: null });
    if (url.endsWith("/admin/logout")) return jsonResponse({ message: "Logged out successfully." });
    throw new Error(`unexpected request: ${url}`);
  };
  const document = setup(fetchImpl);
  const login = document.getElementById("admin-login-form");
  login.fields = { username: "admin", password: "test" };
  await login.dispatch("submit");
  await document.getElementById("admin-logout-button").dispatch("click");
  const logout = requests.find((item) => item.url.endsWith("/admin/logout"));
  assert.equal(logout.options.method, "POST");
  assert.equal(logout.options.headers.Authorization, "Bearer opaque-token");
  assert.equal(document.getElementById("admin-workspace").hidden, true);
  assert.match(document.getElementById("admin-login-message").textContent, /signed out/i);
});

test("API failures stay visible and an unconfirmed logout is not reported as success", async () => {
  const fetchImpl = async (url) => {
    if (url.endsWith("/admin/login")) return jsonResponse({ access_token: "opaque-token", token_type: "Bearer", expires_in: 1800 });
    if (url.endsWith("/admin/dashboard")) return jsonResponse({ total: 0, Submitted: 0, "Under Review": 0, "In Progress": 0, Resolved: 0, Rejected: 0 });
    if (url.includes("/admin/complaints?")) return jsonResponse({ error: { message: "The request could not be completed." } }, 500);
    if (url.endsWith("/admin/logout")) return jsonResponse({ error: { message: "The request could not be completed." } }, 500);
    throw new Error(`unexpected request: ${url}`);
  };
  const document = setup(fetchImpl);
  const login = document.getElementById("admin-login-form");
  login.fields = { username: "admin", password: "test" };
  await login.dispatch("submit");
  assert.match(document.getElementById("complaint-list-message").textContent, /could not be completed/i);
  assert.equal(document.getElementById("admin-workspace").hidden, false);

  await document.getElementById("admin-logout-button").dispatch("click");
  assert.equal(document.getElementById("admin-workspace").hidden, false);
  assert.match(document.getElementById("admin-workspace-message").textContent, /could not be completed/i);
  assert.doesNotMatch(document.getElementById("admin-workspace-message").textContent, /signed out/i);
});

test("a terminal empty result has a clear empty state and disables pagination", async () => {
  const fetchImpl = async (url) => {
    if (url.endsWith("/admin/login")) return jsonResponse({ access_token: "opaque-token", token_type: "Bearer", expires_in: 1800 });
    if (url.endsWith("/admin/dashboard")) return jsonResponse({ total: 0, Submitted: 0, "Under Review": 0, "In Progress": 0, Resolved: 0, Rejected: 0 });
    if (url.includes("/admin/complaints?")) return jsonResponse({ items: [], next_cursor: null });
    throw new Error(`unexpected request: ${url}`);
  };
  const document = setup(fetchImpl);
  const login = document.getElementById("admin-login-form");
  login.fields = { username: "admin", password: "test" };
  await login.dispatch("submit");
  const row = document.getElementById("complaint-rows").children[0];
  assert.match(row.children[0].textContent, /No complaints match/i);
  assert.equal(row.children[0].colSpan, 8);
  assert.equal(document.getElementById("page-next").disabled, true);
});
