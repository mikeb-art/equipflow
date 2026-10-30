"""Builds durst-pull.user.js (the Tampermonkey script installed in Mike's Chrome) from pull.js.
Run after any change to pull.js:  python3 printer-maintenance/tools/make_userscript.py"""
import pathlib
here = pathlib.Path(__file__).parent
src = (here / "pull.js").read_text()
body = src[src.index("(async () => {"):].rstrip().rstrip(";")
head = """// ==UserScript==
// @name         EquipFlow: Durst daily pull
// @namespace    https://equipflow-lemon.vercel.app/
// @version      1.3
// @description  Runs the Printer Maintenance pull only when the Durst page is opened with ?pull=N (N = days). Signs in again by itself with the sign-in saved via ?pullsetup=1. Generated from pull.js by make_userscript.py; do not edit by hand.
// @match        http://50.232.157.54:8090/ui/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_deleteValue
// @grant        GM_registerMenuCommand
// @run-at       document-start
// @downloadURL  https://raw.githubusercontent.com/mikeb-art/equipflow/main/printer-maintenance/tools/durst-pull.user.js
// @updateURL    https://raw.githubusercontent.com/mikeb-art/equipflow/main/printer-maintenance/tools/durst-pull.user.js
// ==/UserScript==
(async () => {
  // Runs at document-start: read ?pull=N / ?pullsetup=1 before the Durst app can redirect to its login screen
  // (it does that at once when the session has expired, e.g. after the Durst PC restarts) and drop them from the address.
  // They are remembered for this tab (pull: 10 minutes, setup: 2 minutes), so the rest can wait for the page to load.
  {
    const q = location.search, now = Date.now();
    const m0 = q.match(/[?&]pull=(\\d+)/);
    if (m0 && Number(m0[1])) sessionStorage.setItem("__pullPending", JSON.stringify({ days: Number(m0[1]), t: now }));
    if (/[?&]pullsetup=1/.test(q)) sessionStorage.setItem("__pullSetupPending", String(now));
  }
  if (document.readyState === "loading") await new Promise(r => document.addEventListener("DOMContentLoaded", r, { once: true }));
  await new Promise(r => setTimeout(r, 1500));   // let the Durst app put up its first screen
  // The Durst sign-in is kept only in Tampermonkey's own storage in this Chrome profile (never in the repo or the page).
  const showSetup = () => {
    if (document.getElementById("__pullSetup")) return;
    const d = document.createElement("div");
    d.id = "__pullSetup";
    d.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;font:14px system-ui,sans-serif";
    d.innerHTML = '<form style="background:#fff;color:#111;padding:24px;border-radius:10px;width:340px;box-shadow:0 10px 40px rgba(0,0,0,.4)">' +
      '<h3 style="margin:0 0 6px">Daily pull: Durst sign-in</h3>' +
      '<p style="margin:0 0 14px;color:#555">Saved only in Tampermonkey on this computer. Used to sign in again when the session expires.</p>' +
      '<label>Username<br><input name="u" autocomplete="off" style="width:100%;padding:6px;margin:4px 0 10px;box-sizing:border-box"></label>' +
      '<label>Password<br><input name="p" type="password" autocomplete="new-password" style="width:100%;padding:6px;margin:4px 0 14px;box-sizing:border-box"></label>' +
      '<div id="__pullSetupMsg" style="min-height:18px;margin-bottom:10px;color:#b00"></div>' +
      '<button type="submit" style="padding:7px 14px">Test and save</button> ' +
      '<button type="button" id="__pullSetupForget" style="padding:7px 14px">Forget saved</button> ' +
      '<button type="button" id="__pullSetupClose" style="padding:7px 14px">Close</button></form>';
    document.body.appendChild(d);
    const f = d.querySelector("form"), msg = d.querySelector("#__pullSetupMsg");
    f.u.value = GM_getValue("durstUser", "");
    d.querySelector("#__pullSetupClose").onclick = () => d.remove();
    d.querySelector("#__pullSetupForget").onclick = () => { GM_deleteValue("durstUser"); GM_deleteValue("durstPass"); msg.style.color = "#060"; msg.textContent = "Saved sign-in removed."; };
    f.onsubmit = async ev => {
      ev.preventDefault(); msg.style.color = "#555"; msg.textContent = "Testing…";
      try {
        await signIn(f.u.value.trim(), f.p.value);
        GM_setValue("durstUser", f.u.value.trim()); GM_setValue("durstPass", f.p.value); f.p.value = "";
        msg.style.color = "#060"; msg.textContent = "Signed in and saved. The daily pull will use it.";
      } catch (e) { msg.style.color = "#b00"; msg.textContent = String(e.message || e) + " (not saved)"; }
    };
  };
  const signIn = async (username, password) => {
    if (!username || !password) throw new Error("Durst auto sign-in: no sign-in saved (open the Durst page with ?pullsetup=1 to save one)");
    const r = await fetch("/frontend-api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
    if (r.status !== 200) throw new Error("Durst auto sign-in failed (HTTP " + r.status + ")");
    let tok = r.headers.get("x-auth-token");
    if (!tok) r.headers.forEach((v, k) => { if (!tok && /token|auth/i.test(k)) tok = v; });
    if (!tok) throw new Error("Durst auto sign-in: no token in the login reply");
    // Keep the Durst app itself signed in too, under the key it already uses.
    let key = null;
    for (let i = 0; i < localStorage.length; i++) if (/token|auth/i.test(localStorage.key(i))) key = localStorage.key(i);
    localStorage.setItem(key || "x-auth-token", tok);
    return tok;
  };
  GM_registerMenuCommand("Durst sign-in for the daily pull…", showSetup);
  { const sp = Number(sessionStorage.getItem("__pullSetupPending") || 0);
    if (sp && Date.now() - sp < 120000) { sessionStorage.removeItem("__pullSetupPending"); showSetup(); return; } }
  window.__durstLogin = async () => { const t = await signIn(GM_getValue("durstUser", ""), GM_getValue("durstPass", "")); window.__pullSignedIn = true; return t; };

  // The request was saved at document-start above (or by an earlier load of this tab within 10 minutes).
  let days = 0;
  try { const p = JSON.parse(sessionStorage.getItem("__pullPending") || "null"); if (p && Date.now() - p.t < 600000) days = p.days; } catch (e) {}
  if (!days) return;                    // normal use of Durst Analytics is untouched
  window.__pullDays = days;
  // Show at once that a pull is running, so the page never looks like a plain Durst screen (e.g. its login page) meanwhile.
  const started = new Date().toLocaleTimeString();
  const banner = () => {
    let b = document.getElementById("__pullRunning");
    if (!b) { b = document.createElement("div"); b.id = "__pullRunning"; b.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#1565c0;color:#fff;padding:10px 16px;font:15px system-ui,sans-serif"; document.body.appendChild(b); }
    b.textContent = "PULL running: " + days + " days, started " + started + (window.__pullSignedIn ? ", signed in again automatically" : "") + ". Leave this tab open.";
  };
  banner();
  const keep = setInterval(banner, 2000);   // the Durst app can re-render; put the banner back if it goes
  await new Promise(r => setTimeout(r, 3000));   // let the app finish starting
  let res;
  try { res = await __PULL_BODY__; } catch (e) { res = { ok: false, error: String(e.message || e) }; }
  clearInterval(keep);
  sessionStorage.removeItem("__pullPending");
  const show = t => { document.body.innerHTML = '<article><pre id="__dump"></pre></article>'; document.getElementById("__dump").textContent = t; };
  if (res && res.ok) show("PULL ok len=" + res.len + " hash=" + res.hash + " printers=" + res.printers + " signin=" + (window.__pullSignedIn ? "auto" : "session") + "\\n---\\n" + window.__dump);
  else show("PULL FAILED: " + ((res && res.error) || "unknown error") + (window.__pullSignedIn ? " (after auto sign-in)" : ""));
})();
"""
(here / "durst-pull.user.js").write_text(head.replace("__PULL_BODY__", body))
print("wrote durst-pull.user.js")
