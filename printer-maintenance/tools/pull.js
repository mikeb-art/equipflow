/* Run in a Chrome tab on the Durst Analytics+ UI (http://50.232.157.54:8090/ui/), signed in.
   Pulls the last 91 days of messages for every active printer, compacts them, and shows the
   result as the page's only <article> so get_page_text can read it.
   Result value: {ok, len, hash, printers, error}. */
(async () => {
  let tok = null;
  for (const st of [localStorage, sessionStorage]) for (let i = 0; i < st.length; i++) {
    const k = st.key(i), v = st.getItem(k);
    if (/token|auth/i.test(k)) { try { const j = JSON.parse(v); tok = typeof j === "string" ? j : (j.token || j.xAuthToken || j.accessToken || tok); } catch (e) { tok = v; } }
  }
  if (!tok) return { ok: false, error: "Not signed in to Durst Analytics" };
  const H = { "Content-Type": "application/json", "x-auth-token": tok };
  const post = async (url, body) => {
    for (let t = 0; t < 5; t++) {
      const r = await fetch(url, { method: "POST", headers: H, body: JSON.stringify(body) });
      if (r.status === 200) return r.json();
      if (r.status === 401 || r.status === 403) throw new Error("Durst Analytics sign-in expired (HTTP " + r.status + ")");
      await new Promise(s => setTimeout(s, 2000));
    }
    throw new Error("Durst Analytics kept failing: " + url);
  };
  try {
    let printers = [];
    for (const page of [0, 1, 2]) { const j = await post("/frontend-api/printer/list", { page, limit: 10, filterTerms: [] }); printers.push(...(j.entities || [])); }
    const seen = new Set(); printers = printers.filter(p => p.active && !seen.has(p.id) && seen.add(p.id));
    const today = new Date(), from = new Date(today); from.setDate(from.getDate() - 90);
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
})();
