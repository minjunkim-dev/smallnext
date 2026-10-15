"use strict";

// Only the first result belongs to this page. Tokens never enter URLs, storage or logs.
(() => {
  const parameters = new URLSearchParams(window.location.search);
  const nonce = parameters.get("nonce");
  const sitekey = parameters.get("sitekey");
  let finished = false;
  const valid = window.top === window.self && window.location.protocol === "https:" &&
    window.location.pathname === "/auth/captcha/" && /^[a-f0-9-]{36}$/.test(nonce || "") &&
    /^[A-Za-z0-9_-]{1,256}$/.test(sitekey || "");

  function finish(type, token = "") {
    if (finished) return;
    finished = true;
    document.getElementById("status").textContent = type === "success" ? "확인을 완료했습니다." : "확인을 완료하지 못했습니다. 앱에서 취소한 뒤 다시 시도하십시오.";
    const bridge = window.webkit?.messageHandlers?.turnstile;
    if (valid && bridge) bridge.postMessage({ type, token, nonce, origin: window.location.origin });
  }

  window.smallnextTurnstileReady = () => {
    if (!valid || !window.webkit?.messageHandlers?.turnstile) { finish("error"); return; }
    try {
      window.turnstile.render("#challenge", {
        sitekey, theme: "auto", language: "ko", retry: "never",
        "refresh-expired": "never", "refresh-timeout": "never",
        callback: token => finish("success", token),
        "error-callback": () => { finish("error"); return true; },
        "expired-callback": () => finish("error"),
        "timeout-callback": () => finish("error"),
        "unsupported-callback": () => finish("error")
      });
    } catch { finish("error"); }
  };
})();
