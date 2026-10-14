const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.listeners = {};
    this.children = [];
    this.attributes = {};
    this.classList = { toggle() {} };
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.value = "";
  }
  set innerHTML(_value) { throw new Error("unsafe innerHTML rendering attempted"); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  scrollIntoView() {}
  async dispatch(name, event = {}) {
    const callback = this.listeners[name];
    assert.ok(callback, `missing ${name} handler for ${this.id}`);
    await callback({ preventDefault() {}, currentTarget: this, ...event });
  }
}

class FakeDocument {
  constructor() { this.elements = new Map(); }
  getElementById(id) {
    if (!this.elements.has(id)) this.elements.set(id, new FakeElement(id));
    return this.elements.get(id);
  }
}

function makeFormData() {
  return class FormData {
    constructor(form) { this.form = form; }
    entries() { return Object.entries(this.form.fields || {}); }
  };
}

function setup(fetchImpl) {
  const document = new FakeDocument();
  const window = { document, fetch: fetchImpl, CLOUDPOINT_CONFIG: { apiBaseUrl: "/api" } };
  const source = fs.readFileSync(path.join(__dirname, "../frontend/static/app.js"), "utf8");
  vm.runInNewContext(source, {
    window,
    document,
    fetch: fetchImpl,
    FormData: makeFormData(),
    Intl,
    Date,
    encodeURIComponent,
    Object
  });
  return document;
}

function jsonResponse(value, status = 200) {
  return { ok: status >= 200 && status < 300, status, async json() { return value; } };
}

const sampleComplaint = {
  student_name: "Example Student",
  registration_number: "REG-1001",
  title: "<script>untrusted</script> Broken light",
  category: "Infrastructure",
  description: "<img src=x onerror=alert(1)>",
  location: "North Block"
};

test("student submission confirms only after API success and safely renders the generated ID", async () => {
  const requests = [];
  const document = setup(async (url, options) => {
    requests.push({ url, options });
    return jsonResponse({ complaint_id: "CP-abcdefghijklmnop", message: "Complaint submitted successfully." }, 201);
  });
  const form = document.getElementById("complaint-form");
  form.fields = sampleComplaint;
  const pending = form.dispatch("submit");
  assert.equal(form.attributes["aria-busy"], "true");
  assert.equal(document.getElementById("submit-button").disabled, true);
  await pending;

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/complaints");
  assert.equal(requests[0].options.method, "POST");
  assert.deepEqual(JSON.parse(requests[0].options.body), sampleComplaint);
  assert.equal(document.getElementById("submission-confirmation").hidden, false);
  assert.equal(document.getElementById("new-complaint-id").textContent, "CP-abcdefghijklmnop");
  assert.equal(document.getElementById("tracking-id").value, "CP-abcdefghijklmnop");
  assert.equal(document.getElementById("submit-message").textContent, "Your complaint was submitted.");
  assert.equal(form.attributes["aria-busy"], "false");
});

test("submission failure is announced and never displays a success confirmation", async () => {
  const document = setup(async () => jsonResponse({ error: { message: "The request could not be completed." } }, 500));
  const form = document.getElementById("complaint-form");
  form.fields = sampleComplaint;
  await form.dispatch("submit");
  assert.equal(document.getElementById("submission-confirmation").hidden, true);
  assert.equal(document.getElementById("submit-message").textContent, "The request could not be completed.");
  assert.equal(document.getElementById("submit-button").disabled, false);
  assert.equal(form.attributes["aria-busy"], "false");
});

test("tracking safely renders current state and avoids exposing fields not returned by tracking API", async () => {
  const document = setup(async () => jsonResponse({
    complaint_id: "CP-abcdefghijklmnop",
    title: "<script>untrusted</script> Broken light",
    category: "Infrastructure",
    description: "<img src=x onerror=alert(1)>",
    location: "North Block",
    status: "Rejected",
    created_at: "2026-10-09T10:00:00+00:00",
    rejection_reason: "<b>Reason text</b>"
  }));
  document.getElementById("tracking-id").value = "CP-abcdefghijklmnop";
  const form = document.getElementById("tracking-form");
  await form.dispatch("submit");
  assert.equal(document.getElementById("tracking-result").hidden, false);
  assert.equal(document.getElementById("result-title").textContent, "<script>untrusted</script> Broken light");
  assert.equal(document.getElementById("result-description").textContent, "<img src=x onerror=alert(1)>");
  assert.equal(document.getElementById("result-rejection").textContent, "<b>Reason text</b>");
  assert.equal(document.getElementById("result-status").textContent, "Rejected");
  assert.equal(form.attributes["aria-busy"], "false");
});

test("tracking error is announced, result stays hidden, and a retry remains possible", async () => {
  let calls = 0;
  const document = setup(async () => {
    calls += 1;
    return jsonResponse({ error: { message: "Complaint not found." } }, 404);
  });
  document.getElementById("tracking-id").value = "CP-abcdefghijklmnop";
  await document.getElementById("tracking-form").dispatch("submit");
  assert.equal(document.getElementById("tracking-result").hidden, true);
  assert.equal(document.getElementById("tracking-message").textContent, "Complaint not found.");
  await document.getElementById("tracking-form").dispatch("submit");
  assert.equal(calls, 2);
  assert.equal(document.getElementById("track-button").disabled, false);
});

test("student forms connect feedback to controls and provide live status regions", () => {
  const html = fs.readFileSync(path.join(__dirname, "../frontend/index.html"), "utf8");
  assert.match(html, /id="submit-message" role="status" aria-live="polite"/);
  assert.match(html, /id="tracking-message" role="status" aria-live="polite"/);
  assert.match(html, /name="student_name"[^>]*aria-describedby="submit-message"/);
  assert.match(html, /id="tracking-id"[^>]*aria-describedby="tracking-message"/);
  assert.match(html, /id="tracking-result"[^>]*aria-live="polite"/);
  const category = html.match(/<select name="category"[^>]*>([\s\S]*?)<\/select>/)?.[1] || "";
  assert.match(category, /<option>Cleanliness<\/option>/);
});
