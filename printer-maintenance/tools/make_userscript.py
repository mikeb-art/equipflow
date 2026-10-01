"""Builds durst-pull.user.js (the Tampermonkey script installed in Mike's Chrome) from pull.js.
Run after any change to pull.js:  python3 printer-maintenance/tools/make_userscript.py"""
import pathlib
here = pathlib.Path(__file__).parent
src = (here / "pull.js").read_text()
body = src[src.index("(async () => {"):].rstrip().rstrip(";")
head = """// ==UserScript==
// @name         EquipFlow: Durst daily pull
// @namespace    https://equipflow-lemon.vercel.app/
// @version      1.0
// @description  Runs the Printer Maintenance pull only when the Durst page is opened with ?pull=N (N = days). Generated from pull.js by make_userscript.py; do not edit by hand.
// @match        http://50.232.157.54:8090/ui/*
// @grant        none
// @run-at       document-idle
// @downloadURL  https://raw.githubusercontent.com/mikeb-art/equipflow/main/printer-maintenance/tools/durst-pull.user.js
// @updateURL    https://raw.githubusercontent.com/mikeb-art/equipflow/main/printer-maintenance/tools/durst-pull.user.js
// ==/UserScript==
(async () => {
  const m = location.search.match(/[?&]pull=(\\d+)/);
  if (!m) return;                       // normal use of Durst Analytics is untouched
  window.__pullDays = Number(m[1]);
  await new Promise(r => setTimeout(r, 3000));   // let the app finish signing in
  let res;
  try { res = await __PULL_BODY__; } catch (e) { res = { ok: false, error: String(e.message || e) }; }
  const show = t => { document.body.innerHTML = '<article><pre id="__dump"></pre></article>'; document.getElementById("__dump").textContent = t; };
  if (res && res.ok) show("PULL ok len=" + res.len + " hash=" + res.hash + " printers=" + res.printers + "\\n---\\n" + window.__dump);
  else show("PULL FAILED: " + ((res && res.error) || "unknown error"));
})();
"""
(here / "durst-pull.user.js").write_text(head.replace("__PULL_BODY__", body))
print("wrote durst-pull.user.js")
