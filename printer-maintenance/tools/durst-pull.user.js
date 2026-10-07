// ==UserScript==
// @name         EquipFlow: Durst daily pull
// @namespace    https://equipflow-lemon.vercel.app/
// @version      1.1
// @description  Runs the Printer Maintenance pull only when the Durst page is opened with ?pull=N (N = days). Signs in again by itself with the sign-in saved via ?pullsetup=1. Generated from pull.js by make_userscript.py; do not edit by hand.
// @match        http://50.232.157.54:8090/ui/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_deleteValue
// @grant        GM_registerMenuCommand
// @run-at       document-idle
// @downloadURL  https://raw.githubusercontent.com/mikeb-art/equipflow/main/printer-maintenance/tools/durst-pull.user.js
// @updateURL    https://raw.githubusercontent.com/mikeb-art/equipflow/main/printer-maintenance/tools/durst-pull.user.js
// ==/UserScript==
(async () => {
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
  if (/[?&]pullsetup=1/.test(location.search)) { showSetup(); return; }
  window.__durstLogin = () => signIn(GM_getValue("durstUser", ""), GM_getValue("durstPass", ""));

  // The Durst app can reload itself and drop ?pull=N from the address, so remember the request for this tab for 10 minutes.
  const m = location.search.match(/[?&]pull=(\d+)/);
  let days = m ? Number(m[1]) : 0;
  if (days) sessionStorage.setItem("__pullPending", JSON.stringify({ days, t: Date.now() }));
  else { try { const p = JSON.parse(sessionStorage.getItem("__pullPending") || "null"); if (p && Date.now() - p.t < 600000) days = p.days; } catch (e) {} }
  if (!days) return;                    // normal use of Durst Analytics is untouched
  window.__pullDays = days;
  await new Promise(r => setTimeout(r, 3000));   // let the app finish starting
  let res;
  try { res = await (async () => {
  // window.__durstLogin (set by the Tampermonkey script) signs in again with the saved Durst sign-in and returns a fresh token.
  const relogin = typeof window.__durstLogin === "function" ? window.__durstLogin : null;
  let tok = null;
  for (const st of [localStorage, sessionStorage]) for (let i = 0; i < st.length; i++) {
    const k = st.key(i), v = st.getItem(k);
    if (/token|auth/i.test(k)) { try { const j = JSON.parse(v); tok = typeof j === "string" ? j : (j.token || j.xAuthToken || j.accessToken || tok); } catch (e) { tok = v; } }
  }
  try { if (!tok && relogin) tok = await relogin(); } catch (e) { return { ok: false, error: String(e.message || e) }; }
  if (!tok) return { ok: false, error: "Not signed in to Durst Analytics" };
  const H = { "Content-Type": "application/json", "x-auth-token": tok };
  let reloggedIn = false;
  const post = async (url, body) => {
    for (let t = 0; t < 5; t++) {
      const r = await fetch(url, { method: "POST", headers: H, body: JSON.stringify(body) });
      if (r.status === 200) return r.json();
      if (r.status === 401 || r.status === 403) {
        if (relogin && !reloggedIn) { reloggedIn = true; H["x-auth-token"] = await relogin(); t--; continue; }
        throw new Error("Durst Analytics sign-in expired (HTTP " + r.status + ")" + (relogin ? " even after auto sign-in" : ""));
      }
      await new Promise(s => setTimeout(s, 2000));
    }
    throw new Error("Durst Analytics kept failing: " + url);
  };
  try {
    let printers = [];
    for (const page of [0, 1, 2]) { const j = await post("/frontend-api/printer/list", { page, limit: 10, filterTerms: [] }); printers.push(...(j.entities || [])); }
    const seen = new Set(); printers = printers.filter(p => p.active && !seen.has(p.id) && seen.add(p.id));
    const DAYS = Number(window.__pullDays) || 3;   // set window.__pullDays = 90 first for a full refresh
    const today = new Date(), from = new Date(today); from.setDate(from.getDate() - DAYS);
    const iso = d => d.toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
    const FROM = iso(from), TO = iso(today);
    const dayOf = (d, tz) => new Date(d).toLocaleDateString("en-CA", { timeZone: tz });
    const norm = t => {
      const m = t.replace(/^[\d\-: ]+(?=Maint)/, "");
      const w = m.match(/^Maintenance warning: (.+?)( (done|Remind later|remind later))?$/i);
      if (w && !/Purge cycle started/.test(m)) return { task: w[1].trim(), kind: w[3] ? (w[3].toLowerCase() === "done" ? "d" : "l") : "w" };
      if (/Purge cycle finished/.test(m)) return { task: "Purge cycle run", kind: "a" };
      if (/Testpattern/i.test(m)) return { task: "Test pattern printed", kind: "a" };
      return null;
    };
    const tasks = [], ti = t => { let i = tasks.indexOf(t); if (i < 0) { tasks.push(t); i = tasks.length - 1; } return i; };
    const lines = [], pc = [];
    for (const p of printers) {
      let all = [], page = 0, total = null;
      while (true) {
        const j = await post("/frontend-api/error/list", { page, limit: 1000, filterTerms: [
          { property: "TC_PRINTER_IDS", operator: "EQUAL", value: [p.id] },
          { property: "TC_DATE_FROM", operator: "EQUAL", value: FROM },
          { property: "TC_DATE_TO", operator: "EQUAL", value: TO },
          { property: "TC_TIME_ZONE_TYPE", operator: "EQUAL", value: "PRINTER" },
          { property: "TC_TIME_ZONE", operator: "EQUAL", value: p.timeZone }] });
        const e = j.entities || []; total = j.meta && j.meta.totalCount; all.push(...e);
        if (!e.length || all.length >= total || page > 80) break; page++;
      }
      const days = {}, purge = {};
      for (const r of all) {
        const d = dayOf(r.datetime, p.timeZone);
        if (String(r.errorNr).split("|")[0] === "41002") purge[d] = (purge[d] || 0) + 1;   // P5 purge cycle
        const n = norm(r.errorText); if (!n) continue;
        // P5: the same "Maintenance warning: X" text is sent for the on-screen prompt and for the operator's Execute.
        // Execute carries a zero-padded second ID (…|00000000000003089282); prompts carry a different one. Found Oct 1, 2026.
        const [code, sub] = String(r.errorNr).split("|");
        if (n.kind === "w" && /^50\d\d\d$/.test(code) && /^0{10}/.test(sub || "")) n.kind = "d";
        const k = ti(n.task) + n.kind; (days[d] = days[d] || {})[k] = (days[d][k] || 0) + 1;
      }
      lines.push("P" + p.id + "|" + p.systemNumber + "=" + Object.keys(days).sort().map(d => d + ":" + Object.entries(days[d]).map(([k, c]) => k + c).join(".")).join(" "));
      pc.push("PC" + p.id + "=" + Object.keys(purge).sort().map(d => d + ":" + purge[d]).join(" "));
    }
    const s = "D=" + FROM + "|" + TO + "|" + new Date().toISOString() + "\nT=" + tasks.join(";") + "\n" + lines.join("\n") + "\n" + pc.join("\n");
    let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 2147483647;
    window.__dump = s;
    document.body.innerHTML = '<article><pre id="__dump"></pre></article>';
    document.getElementById("__dump").textContent = s;
    return { ok: true, len: s.length, hash: h, printers: printers.length };
  } catch (e) { return { ok: false, error: String(e.message || e) }; }
})(); } catch (e) { res = { ok: false, error: String(e.message || e) }; }
  sessionStorage.removeItem("__pullPending");
  const show = t => { document.body.innerHTML = '<article><pre id="__dump"></pre></article>'; document.getElementById("__dump").textContent = t; };
  if (res && res.ok) show("PULL ok len=" + res.len + " hash=" + res.hash + " printers=" + res.printers + "\n---\n" + window.__dump);
  else show("PULL FAILED: " + ((res && res.error) || "unknown error"));
})();
