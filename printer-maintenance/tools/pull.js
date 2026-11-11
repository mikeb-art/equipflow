/* Run in a Chrome tab on the Durst Analytics+ UI (http://50.232.157.54:8090/ui/), signed in.
   Pulls the last 3 days (or window.__pullDays) of messages for every active printer, compacts them, and shows the
   result as the page's only <article> so get_page_text can read it.
   Result value: {ok, len, hash, printers, error}. */
(async () => {
  // window.__durstLogin (set by the Tampermonkey script) signs in again with the saved Durst sign-in and returns a fresh token.
  const relogin = typeof window.__durstLogin === "function" ? window.__durstLogin : null;
  // The Durst app keeps its token as plain text under "@Analytics|Server|Token"; the scan below is only a fallback.
  let tok = localStorage.getItem("@Analytics|Server|Token");
  if (!tok) for (const st of [localStorage, sessionStorage]) for (let i = 0; i < st.length; i++) {
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
    // printer-local HHMM, for the per-shift purge check (purge at the start of each shift)
    const hmOf = (d, tz) => new Date(d).toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).replace(":", "");
    const norm = t => {
      const m = t.replace(/^[\d\-: ]+(?=Maint)/, "");
      const w = m.match(/^Maintenance warning: (.+?)( (done|Remind later|remind later))?$/i);
      if (w && !/Purge cycle started/.test(m)) return { task: w[1].trim(), kind: w[3] ? (w[3].toLowerCase() === "done" ? "d" : "l") : "w" };
      if (/Purge cycle finished/.test(m)) return { task: "Purge cycle run", kind: "a" };
      if (/Testpattern/i.test(m)) return { task: "Test pattern printed", kind: "a" };
      return null;
    };
    const tasks = [], ti = t => { let i = tasks.indexOf(t); if (i < 0) { tasks.push(t); i = tasks.length - 1; } return i; };
    const lines = [], pc = [], pt = [], ph = [], pn = [], pw = [], pj = [];
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
      // Print jobs (Printer Jobs list). Order jobs = printing; test-pattern / other non-order jobs = head tests.
      let jobs = [];
      page = 0;
      while (true) {
        const j = await post("/frontend-api/job-overview/list", { page, limit: 1000, filterTerms: [
          { property: "TC_PRINTER_IDS", operator: "EQUAL", value: [p.id] },
          { property: "TC_DATE_FROM", operator: "EQUAL", value: FROM },
          { property: "TC_DATE_TO", operator: "EQUAL", value: TO },
          { property: "TC_TIME_ZONE_TYPE", operator: "EQUAL", value: "PRINTER" },
          { property: "TC_TIME_ZONE", operator: "EQUAL", value: p.timeZone }] });
        const e = j.entities || []; jobs.push(...e);
        if (!e.length || jobs.length >= ((j.meta && j.meta.totalCount) || 0) || page > 40) break; page++;
      }
      const days = {}, purge = {}, ptimes = {}, hours = {}, ntimes = {};
      // Work hours (v1.7): when someone is actually working the printer, so a stray message (a maintenance prompt
      // answered at night, a pressure warning in standby) is not taken for a startup.
      //   jh = hours with an order job printing (start to end); wh = jh + head tests (test-pattern jobs and messages)
      //   + loading media (clamp rollers opened, media detect / load / position / roll-end messages).
      const jh = {}, wh = {};
      const mark = (o, d, h) => { o[d] = (o[d] || 0) | (1 << h); };
      const markSpan = (o, a, b) => {
        const t0 = Date.parse(a), t1 = Math.min(Math.max(Date.parse(b || a) || t0, t0), t0 + 12 * 3600e3);
        for (let t = t0; ; t = Math.min(t + 3600e3, t1)) {
          mark(o, dayOf(t, p.timeZone), Number(hmOf(t, p.timeZone).slice(0, 2)));
          if (t >= t1) break;
        }
      };
      for (const r of jobs) {
        if (!r.startTime || !(r.numberOfPrintsDone > 0 || r.jobState === "Done")) continue;   // held / never printed
        // test-pattern jobs ("Test pattern type 9 Nozzle Check" …) are head tests; other Order (category 1) jobs are printing.
        // Some printers send order jobs with job ID 0 (Rhotex 325-2 MX), so the ID is not used.
        const isTest = r.jobCategoryId !== 1 || /test ?pattern|nozzle/i.test(r.jobTitle || "");
        if (!isTest) markSpan(jh, r.startTime, r.endTime);
        markSpan(wh, r.startTime, r.endTime);
        // test-pattern jobs are nozzle checks too (some printers log no test-pattern message for them)
        if (/test ?pattern|nozzle/i.test(r.jobTitle || ""))
          (ntimes[dayOf(r.startTime, p.timeZone)] = ntimes[dayOf(r.startTime, p.timeZone)] || []).push(hmOf(r.startTime, p.timeZone));
      }
      const LOAD = /^(6604|6602|9035|8320|9029|9030|29028)$/;
      for (const r of all) {
        const d = dayOf(r.datetime, p.timeZone), hm = hmOf(r.datetime, p.timeZone);
        hours[d] = (hours[d] || 0) | (1 << Number(hm.slice(0, 2)));   // hours of the day the printer logged anything
        const isP5Purge = String(r.errorNr).split("|")[0] === "41002";
        if (isP5Purge) purge[d] = (purge[d] || 0) + 1;   // P5 purge cycle
        const n = norm(r.errorText);
        const c0 = String(r.errorNr).split("|")[0];
        if ((n && n.task === "Test pattern printed") || /^(21000|41000|41010|10200)$/.test(c0) || LOAD.test(c0) || /Roll end detected/i.test(r.errorText))
          mark(wh, d, Number(hm.slice(0, 2)));
        // purge times: "c" = P5 purge cycle (41002), "t" = Rhotex "Purge cycle finished"
        if (isP5Purge || (n && n.task === "Purge cycle run")) (ptimes[d] = ptimes[d] || []).push(hm + (isP5Purge ? "c" : "t"));
        // nozzle check (test pattern) times, printer-local HHMM: checked before work starts at each startup
        if (n && n.task === "Test pattern printed") (ntimes[d] = ntimes[d] || []).push(hm);
        if (!n) continue;
        // P5: the same "Maintenance warning: X" text is sent for the on-screen prompt and for the operator's Execute.
        // Execute carries a zero-padded second ID (…|00000000000003089282); prompts carry a different one. Found Oct 1, 2026.
        const [code, sub] = String(r.errorNr).split("|");
        if (n.kind === "w" && /^50\d\d\d$/.test(code) && /^0{10}/.test(sub || "")) n.kind = "d";
        const k = ti(n.task) + n.kind; (days[d] = days[d] || {})[k] = (days[d][k] || 0) + 1;
      }
      lines.push("P" + p.id + "|" + p.systemNumber + "=" + Object.keys(days).sort().map(d => d + ":" + Object.entries(days[d]).map(([k, c]) => k + c).join(".")).join(" "));
      pc.push("PC" + p.id + "=" + Object.keys(purge).sort().map(d => d + ":" + purge[d]).join(" "));
      pt.push("PT" + p.id + "=" + Object.keys(ptimes).sort().map(d => d + ":" + [...new Set(ptimes[d])].sort().join(".")).join(" "));
      // every active day gets a PN entry (empty = no nozzle check that day), so "none" differs from "not pulled"
      const nd = [...new Set([...Object.keys(hours), ...Object.keys(ntimes)])].filter(d => d >= FROM && d <= TO).sort();
      pn.push("PN" + p.id + "=" + nd.map(d => d + ":" + [...new Set(ntimes[d] || [])].sort().join(".")).join(" "));
      ph.push("PH" + p.id + "=" + Object.keys(hours).sort().map(d => d + ":" + hours[d].toString(16)).join(" "));
      // every pulled day gets a PW / PJ entry (0 = no work that day), so "no work" differs from "pulled before v1.7"
      const wd = [...new Set([...Object.keys(hours), ...Object.keys(wh)])].filter(d => d >= FROM && d <= TO).sort();
      pw.push("PW" + p.id + "=" + wd.map(d => d + ":" + (wh[d] || 0).toString(16)).join(" "));
      pj.push("PJ" + p.id + "=" + wd.map(d => d + ":" + (jh[d] || 0).toString(16)).join(" "));
    }
    const s = "D=" + FROM + "|" + TO + "|" + new Date().toISOString() + "\nT=" + tasks.join(";") + "\n" + lines.join("\n") + "\n" + pc.join("\n")
      + "\n" + pt.join("\n") + "\n" + ph.join("\n") + "\n" + pn.join("\n") + "\n" + pw.join("\n") + "\n" + pj.join("\n");
    let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 2147483647;
    window.__dump = s;
    document.body.innerHTML = '<article><pre id="__dump"></pre></article>';
    document.getElementById("__dump").textContent = s;
    return { ok: true, len: s.length, hash: h, printers: printers.length };
  } catch (e) { return { ok: false, error: String(e.message || e) }; }
})();
