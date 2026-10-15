const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../../../infra/production/captcha/bridge.js"), "utf8");
const nonce = "00000000-0000-4000-8000-000000000001";

function page(address = `https://captcha.example.invalid/auth/captcha/?sitekey=synthetic-site&nonce=${nonce}`, mainFrame = true) {
  const messages = [];
  const status = { textContent: "" };
  let widget;
  const window = {
    location: new URL(address),
    webkit: { messageHandlers: { turnstile: { postMessage: value => messages.push(value) } } },
    turnstile: { render: (_, options) => { widget = options; } }
  };
  window.self = window;
  window.top = mainFrame ? window : {};
  vm.runInNewContext(source, { window, URLSearchParams, document: { getElementById: () => status } });
  window.smallnextTurnstileReady();
  return { window, messages, widget, status };
}

test("main-frame HTTPS result includes the same exact origin and nonce that native checks", () => {
  const p = page();
  assert.ok(p.widget);
  assert.equal(p.widget.retry, "never");
  assert.equal(p.widget["refresh-expired"], "never");
  p.widget.callback("synthetic-captcha");
  p.widget.callback("must-not-be-replayed");
  assert.equal(p.messages.length, 1);
  assert.equal(p.messages[0].origin, "https://captcha.example.invalid");
  assert.equal(p.messages[0].nonce, nonce);
  assert.equal(p.messages[0].token, "synthetic-captcha");
  assert.equal(p.messages[0].type, "success");
  assert.equal(p.window.location.search.includes("synthetic-captcha"), false);
});

test("subframes, HTTP, wrong paths and missing configuration never render or send a token", () => {
  for (const p of [page(undefined, false), page(`http://captcha.example.invalid/auth/captcha/?sitekey=synthetic&nonce=${nonce}`),
    page(`https://captcha.example.invalid/other/?sitekey=synthetic&nonce=${nonce}`),
    page("https://captcha.example.invalid/auth/captcha/?sitekey=synthetic")]) {
    assert.equal(p.widget, undefined);
    assert.equal(p.messages.length, 0);
  }
});

test("expiry, challenge errors, timeout and unsupported browsers produce one fixed failure", () => {
  for (const callback of ["error-callback", "expired-callback", "timeout-callback", "unsupported-callback"]) {
    const p = page();
    p.widget[callback]("must-not-be-exposed");
    p.widget.callback("too-late");
    assert.equal(p.messages.length, 1);
    assert.equal(p.messages[0].type, "error");
    assert.equal(p.messages[0].token, "");
    assert.equal(JSON.stringify(p.messages).includes("must-not-be-exposed"), false);
  }
});
