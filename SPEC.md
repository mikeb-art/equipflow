# EquipFlow module conversion spec

Unified app "EquipFlow" (sibling branding to the company's PSUFlow production
tracker). Four legacy single-file dashboards (light theme, GitHub Pages) are
being converted into modules of one dark-navy PSUFlow-styled app, deployed on
Vercel as a static multi-page site.

Repo layout (site root = repo root):
```
/index.html            overview (built separately — not your job)
/maintenance/          Machine Maintenance (index.html + dashboard-charts.js + kpi-daily.js + pdf)
/barbieri/             Barbieri DOC monitoring
/rulers/               Ruler verification tracker
/temp-humidity/        Temp & Humidity (index.html + data.json)
/assets/theme.css      shared tokens + shell components (already written — read it)
/assets/auth.js        shared token cache (already written — read it)
```

## Hard rules

- DO NOT change any data logic: CONFIG values, sheet IDs, parsing functions,
  thresholds, schedule math, view-switching logic, element IDs used by JS,
  data-view/data-loc attributes, onclick handlers. The rulers parser especially
  is battle-tested against messy sheet data — leave every parsing branch alone.
- Purely visual + navigational + auth-cache changes only.
- The page must fully work signed-out (gate card / dashboard skeleton renders,
  no console errors besides expected 401-ish data absence).

## 1. Document shell

Wrap the page in the shared layout:

```html
<body>
<div class="eqf-app">
  <aside class="eqf-side">
    <div class="eqf-brand">
      <div class="dot"></div>
      <div>
        <div class="nm">Equip<b>Flow</b></div>
        <div class="sub">Equipment · Environment</div>
        <div class="ver">v2026.08.06</div>
      </div>
    </div>
    <div class="eqf-navlabel">Modules</div>
    <a class="eqf-navitem mod" href="/">▦&nbsp;Overview</a>
    <a class="eqf-navitem mod" href="/maintenance/">🛠&nbsp;Maintenance</a>
    <a class="eqf-navitem mod" href="/barbieri/">🎯&nbsp;Barbieri DOC</a>
    <a class="eqf-navitem mod" href="/rulers/">📏&nbsp;Rulers</a>
    <a class="eqf-navitem mod" href="/temp-humidity/">🌡&nbsp;Temp &amp; Humidity</a>
    <!-- then the module's ORIGINAL nav sections (Views / Locations / System etc.)
         with every id/data-attribute/onclick preserved; restyle classes may stay
         (.nav-item etc. are themed by theme.css). -->
    <!-- DELETE the old "Other Dashboards" external links + old logo header. -->
    <!-- keep the module's auth card / side-foot if present -->
  </aside>
  <div class="eqf-main">
    ...original topbar + content...
  </div>
</div>
```

Mark the module's own entry in the Modules list with class `active`.
All internal links root-relative (`/maintenance/` etc.).
`<title>` → `"<Module name> · EquipFlow"`.

## 2. Theme conversion (light → dark navy)

Add AFTER the module's `<style>` block:
```html
<link rel="stylesheet" href="/assets/theme.css">
```

Then convert the module's own CSS to tokens (edit values in place; keep all
layout/spacing/grid rules untouched):

| legacy light value (approx) | replace with |
|---|---|
| page bg `#f2f5fa` / `#f5f7fb` etc. | `var(--bg)` |
| white cards `#fff` | `var(--card)` |
| light section bg `#f8fafd` etc. | `var(--inset)` |
| primary text `#1c2b4a` `#222` etc. | `var(--ink)` |
| secondary text `#5a7bb0` `#666` | `var(--ink-2)` |
| faint text `#8ea3c8` `#999` | `var(--muted)` |
| borders `#e3eaf5` `#dde` etc. | `var(--border)` |
| link/accent blues `#1f6fd6` etc. (UI chrome only, not chart series) | `var(--accent)` |
| shadows | `var(--shadow)` or none |
| green status | `var(--good)` (soft bg: `var(--good-soft)`) |
| amber/yellow status | `var(--warn)` / `var(--warn-soft)` |
| orange "serious" status | `var(--serious)` / `var(--serious-soft)` |
| red status | `var(--crit)` / `var(--crit-soft)` |

Delete the module's own topbar/sidebar/nav-item CSS rules where theme.css now
provides them (or leave them only if they carry layout the theme lacks — when in
doubt keep the rule but convert its colors). Status meaning must never be
color-alone — the pages already pair colors with text labels; keep those labels.

## 3. Chart.js re-skin (keep all data/config logic)

Near the top of the module script (after Chart.js loads):
```js
if (window.Chart) {
  Chart.defaults.color = "#9db0d5";
  Chart.defaults.borderColor = "#243352";
  Chart.defaults.font.family = 'system-ui,-apple-system,"Segoe UI",sans-serif';
}
```
Replace categorical series color arrays with (fixed order, never cycled):
`["#3987e5","#d95926","#199e70","#c98500","#d55181","#008300","#9085e9","#e66767"]`
(barbieri: the `PALETTE` const). If more series than 8 exist, repeat is NOT
allowed — fold extras to `#64789f` gray "Other". Keep tooltips/legends enabled
as they are. Threshold/status colors inside chart annotations: use the status
hexes above. Keep axis titles/labels; grid lines should use `#243352`.

## 4. Shared auth cache (modules with Google sign-in)

`<script src="/assets/auth.js"></script>` before the module script. Then:
- In the token client callback, first line: `EQF.saveToken(resp, <SCOPES string>);`
- On page init (where GIS is initialized): first check
  `const c = EQF.cachedToken(<SCOPES string>); if (c) { accessToken = c.access_token; ...proceed with userinfo fetch + data load as if just signed in... }`
  else attempt the silent `tokenClient.requestAccessToken({prompt:""})` the page
  already has (maintenance lacks it — add the same silent attempt after GIS init,
  guarded so it does not open a popup: silent attempts use `prompt:""` only).
- In sign-out handlers: `EQF.clearToken();` alongside the existing revoke.

## 5. Module-specific notes

- **maintenance/**: also re-skin `dashboard-charts.js` and `kpi-daily.js`
  (colors only). Keep the write paths (log submit, feedback, offline queue)
  byte-identical in behavior. Scope string is the full
  `openid email profile https://www.googleapis.com/auth/spreadsheets`.
- **barbieri/**, **rulers/**: readonly scope string as in their code.
- **temp-humidity/**: no auth. Change `fetch('data.json')` to try
  `https://mikeb-art.github.io/temp-humidity/data.json` first (the nightly
  refresh job commits there) and fall back to local `./data.json` on failure.
  Keep the local copy as the fallback.

## 6. Self-verification (required)

From the repo root run `python3 -m http.server 8123`, then with Playwright
(chromium at `/opt/pw-browsers/chromium`, use `executablePath`) load
`http://localhost:8123/<module>/`, capture a full-page screenshot, and check:
- dark navy shell renders, sidebar Modules block present, module nav intact
- no horizontal overflow, no unreadable dark-on-dark text
- console shows no errors other than expected unauthenticated data failures
  (Google scripts may not load offline — that's fine, note it and move on)
Look at your screenshot before declaring done. Fix what looks broken.
