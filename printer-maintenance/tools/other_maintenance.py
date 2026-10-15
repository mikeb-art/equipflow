"""Other maintenance status (Monti, Vutek, Klieverik sign-offs on the Machine Maintenance page) for the daily Printing post.

Used by build.py. The machine and task lists come from the Machine Maintenance page (maintenance/index.html),
read with node so this stays in step with what operators check off. Sign-offs come from the Maintenance Log rows
build.py already has.

A recurring task is up to date when it has a Completed sign-off within its window, counted back from the post's
morning (daily windows skip weekends). Overdue: signed off before, but not within the window. No record: never
signed off in the log; those are listed separately and left out of the percentage.
Daily & every-shift tasks (windows counted in workdays) and weekly & longer tasks are reported separately.
"""
import collections, datetime as dt, json, re, subprocess

SITE = "https://equipflow-lemon.vercel.app"
PLANTS = ("CA", "PA", "MX")
WINDOWS = {"shift": ("wd", 1), "daily": ("wd", 1), "d2": ("wd", 2), "wd3": ("wd", 3), "week": ("cd", 7),
           "biweek": ("cd", 14), "wd15": ("cd", 21), "month": ("cd", 31), "wd45": ("cd", 63), "qtr": ("cd", 92),
           "half": ("cd", 183), "year": ("cd", 366)}   # use / req / purge: not counted
# The post shows short-interval tasks (counted in workdays: every shift, daily, every 2-3 workdays) apart from weekly and
# longer ones, so a missed day of daily sign-offs does not look like the longer-interval maintenance slipped.
GROUPS = (("daily", "Daily & every shift"), ("long", "Weekly & longer"))
def group_of(iv):
    return "daily" if WINDOWS[iv][0] == "wd" else "long"


def _tot(items):
    t = {k: sum(x[k] for x in items) for k in ("ok", "over", "never")}
    t["pct"] = round(100 * t["ok"] / (t["ok"] + t["over"])) if t["ok"] + t["over"] else None
    return t

_NODE = r'''
const fs=require("fs");const s=fs.readFileSync(process.argv[1],"utf8");
const a=s.indexOf("const CHIPS"),b=s.indexOf("function save()");
if(a<0||b<0)throw new Error("CHIPS/LOCS block not found");
const f=new Function(s.slice(a,b)+";return {chips:CHIPS,locs:LOCS,t:T};");const o=f();
const out={chips:o.chips,locs:o.locs,t:{}};
for(const l in o.locs)for(const m of o.locs[l].machines)if(m.t)out.t[m.t]=o.t[m.t];
process.stdout.write(JSON.stringify(out));
'''


def load_spec(maint_html):
    r = subprocess.run(["node", "-e", _NODE, maint_html], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(f"could not read the Machine Maintenance task list: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def _since(today, iv):
    kind, n = WINDOWS[iv]
    if kind == "cd":
        return today - dt.timedelta(n)
    d, k = today, 0
    while k < n:
        d -= dt.timedelta(1)
        if d.weekday() < 5:
            k += 1
    return d


def status(spec, log_rows, today):
    """log_rows: Log rows without the header. today: the post's date (sign-offs from today are ignored)."""
    last = {}
    for r in log_rows:
        if len(r) < 8:
            continue
        try:
            d = dt.datetime.strptime(r[0].split(",")[0].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        if d >= today:
            continue
        key = (r[4].strip(), r[5].strip())
        if r[7] == "Completed":
            if key not in last or d > last[key]:
                last[key] = d
        elif r[7].startswith("Unchecked") and last.get(key) == d:
            del last[key]
    out = {"asof": today.isoformat(), "plants": {}}
    for plant in PLANTS:
        L = spec["locs"].get(plant)
        if not L:
            continue
        machines = []
        for m in L["machines"]:
            if not m.get("t") or m["t"] not in spec["t"]:
                continue
            c = collections.Counter(); g = {k: collections.Counter() for k, _ in GROUPS}; over, never = [], []
            for t in spec["t"][m["t"]]:
                iv = t[1]
                if iv not in WINDOWS:
                    continue
                gk = group_of(iv)
                ld = last.get((m["s"], t[0]))
                if ld and ld >= _since(today, iv):
                    k = "ok"
                elif ld:
                    k = "over"; over.append([t[0], spec["chips"][iv][0], ld.isoformat()])
                else:
                    k = "never"; never.append([t[0], spec["chips"][iv][0]])
                c[k] += 1; g[gk][k] += 1
            machines.append({"name": m.get("d") or m["n"], "serial": m["s"], "ok": c["ok"], "over": c["over"], "never": c["never"],
                             "groups": {k: {x: g[k][x] for x in ("ok", "over", "never")} for k, _ in GROUPS},
                             "overdue": over, "no_record": never})
        groups = {k: _tot([x["groups"][k] for x in machines]) for k, _ in GROUPS}
        out["plants"][plant] = {"name": L.get("full", plant), "machines": machines, **_tot(machines), "groups": groups}
    return out


def chart(st, png_path):
    """Two panels (daily & every shift / weekly & longer), stacked bars per plant: up to date / overdue (the percentage
    base). No-record tasks are noted at the right."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    OK, OVER, INK, MUTED, GRID = "#199e70", "#d97a16", "#1f2733", "#6b7688", "#e3e7ee"
    def has(p, gk):
        g = st["plants"][p]["groups"][gk]
        return g["ok"] + g["over"] + g["never"] > 0
    panels = [(gk, gl, [p for p in PLANTS if p in st["plants"] and has(p, gk)]) for gk, gl in GROUPS]
    panels = [x for x in panels if x[2]]   # a group no plant has is left out (e.g. CA and PA have no daily tasks)
    rows = [len(x[2]) for x in panels]
    fig, axes = plt.subplots(len(panels), 1, figsize=(6.4, 0.62 * sum(rows) + 0.75 * len(panels) + 0.35), dpi=200,
                             gridspec_kw={"height_ratios": rows}, squeeze=False)
    fig.patch.set_facecolor("white")
    for ax, (gk, glabel, plants) in zip(axes[:, 0], panels):
        for i, p in enumerate(plants):
            s = st["plants"][p]["groups"][gk]; n = s["ok"] + s["over"]; y = len(plants) - 1 - i
            a = 100 * s["ok"] / n if n else 0
            ax.barh(y, a, color=OK, height=0.56)
            ax.barh(y, 100 - a if n else 0, left=a, color=OVER, height=0.56)
            lab = f"{s['pct']}%" if s["pct"] is not None else "–"
            ax.text(102, y + 0.08, lab, va="center", ha="left", fontsize=11, fontweight="bold", color=INK)
            sub = (f"{s['ok']}/{n} up to date" if n else "no tasks") + (f" · {s['never']} no record" if s["never"] else "")
            ax.text(102, y - 0.25, sub, va="center", ha="left", fontsize=7.5, color=MUTED)
        ax.set_ylim(-0.6, len(plants) - 0.4)   # same bar thickness in every panel
        ax.set_title(glabel, loc="left", fontsize=9.5, fontweight="bold", color=INK, pad=4)
        ax.set_yticks(range(len(plants)), list(reversed(plants)), fontsize=11, fontweight="bold", color=INK)
        ax.set_xlim(0, 100); ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"], fontsize=7.5, color=MUTED)
        ax.tick_params(length=0)
        ax.grid(axis="x", color=GRID, linewidth=0.8); ax.set_axisbelow(True)
        for sp in ax.spines.values():
            sp.set_visible(False)
    fig.legend(handles=[Patch(color=OK, label="Up to date"), Patch(color=OVER, label="Overdue")], loc="lower left",
               bbox_to_anchor=(0.06, 0.0), ncol=2, frameon=False, fontsize=8, labelcolor=INK)
    H = fig.get_figheight()
    fig.subplots_adjust(left=0.07, right=0.72, top=1 - 0.28 / H, bottom=0.42 / H, hspace=0.75 * len(panels) / sum(rows))
    fig.savefig(png_path, facecolor="white")
    plt.close(fig)


def _group_text(s, bold):
    """'Daily & every shift 59% (17 of 29), 12 overdue · Weekly & longer 100% (53 of 53)' for one plant."""
    parts = []
    for gk, glabel in GROUPS:
        g = s["groups"][gk]; n = g["ok"] + g["over"]
        if not n:
            continue
        t = f"{glabel} {g['pct']}% ({g['ok']} of {n})"
        if g["over"]:
            t += f", {g['over']} overdue"
        parts.append(t)
    return " · ".join(parts) if parts else "no recurring tasks"


def text_lines(st):
    """Plain-text version for reminder.txt (also the fallback post)."""
    out = ["", "*Other maintenance status this morning* (Monti, Vutek, Klieverik sign-offs)"]
    for p in PLANTS:
        s = st["plants"].get(p)
        if not s:
            continue
        line = f"• {p}: " + _group_text(s, False)
        if s["never"]:
            line += f"; {s['never']} never signed off"
        out.append(line + f" · {SITE}/maintenance/#{p}")
    return out


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def card(title, printer_lines, st, image_url):
    """Google Chat cardsV2 message. printer_lines: {plant: [line, ...]}."""
    sections = []
    for p in PLANTS:
        lines = printer_lines.get(p) or ["Nothing put off or open"]
        sections.append({"header": f"{p} printers",
                         "widgets": [{"textParagraph": {"text": "<br>".join("• " + _esc(x) for x in lines)}}]})
    w = []
    if image_url:
        w.append({"image": {"imageUrl": image_url, "altText": "Other maintenance up to date by location: " + ", ".join(
            f"{p} " + ", ".join(f"{gl.lower()} {st['plants'][p]['groups'][gk]['pct']}%" for gk, gl in GROUPS
                                if st['plants'][p]['groups'][gk]['pct'] is not None)
            for p in PLANTS if p in st["plants"])}})
    summary = []
    for p in PLANTS:
        s = st["plants"].get(p)
        if not s:
            continue
        summary.append(f"<b>{p}</b>: " + _esc(_group_text(s, True)).replace(" · ", "<br>&nbsp;&nbsp;&nbsp;"))
    w.append({"textParagraph": {"text": "<br>".join(summary)}})
    nr = []
    for p in PLANTS:
        s = st["plants"].get(p)
        if s and s["never"]:
            per = ", ".join(f"{m['name']}: {m['never']}" for m in s["machines"] if m["never"])
            nr.append(f"<b>{p}</b>: {s['never']} ({_esc(per)})")
    if nr:
        w.append({"textParagraph": {"text": "<font color=\"#6b7688\">Tasks never signed off in the log (not in the %):</font><br>" + "<br>".join(nr)}})
    w.append({"buttonList": {"buttons": [{"text": f"{p} other maintenance", "onClick": {"openLink": {"url": f"{SITE}/maintenance/#{p}"}}}
                                         for p in PLANTS]}})
    w.append({"buttonList": {"buttons": [{"text": f"{p} printers", "onClick": {"openLink": {"url": f"{SITE}/printer-maintenance/#{p}"}}}
                                         for p in PLANTS]}})
    sections.append({"header": "Other maintenance status this morning", "widgets": w})
    return {"cardsV2": [{"cardId": "printer-maintenance-daily", "card": {
        "header": {"title": title, "subtitle": "From Durst Analytics and the Maintenance Log"}, "sections": sections}}]}
