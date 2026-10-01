#!/usr/bin/env python3
"""Rebuild Printer Maintenance data from a Durst pull + the Machine Maintenance Log.

usage: build.py DUMP.txt LOG.json [--html printer-maintenance/index.html] [--reminder reminder.txt]

DUMP.txt  text produced by tools/pull.js (read from the page with get_page_text)
LOG.json  Google Sheets values for 'Log'!A1:H of the Machine Maintenance Log
          ({"values": [[Timestamp, User, Loc, Machine, Serial, Task, Interval, Action], ...]})
Rewrites the `const DATA=` line in index.html and writes the Printing-space reminder text.
"""
import argparse, collections, datetime as dt, json, re, sys
from zoneinfo import ZoneInfo

# Analytics+ system number -> (plant, page name, model, serial). Matches the Maintenance Log.
PRINTERS = {
    "142718": ("CA", "Rhotex 325 - CA", "Rhotex 325", "AD28-042"),
    "298127": ("CA", "P5-350 - CA", "P5 350", "AK26-117"),
    "298155": ("CA", "P5 Tex - CA", "P5 Tex", "AE28-019"),
    "105857": ("PA", "Rhotex 325-1 - PA", "Rhotex 325", "AD-28-031"),
    "202921": ("PA", "Rhotex 325-2 - PA", "Rhotex 325", "AD28-069"),
    "294130": ("PA", "P5-350 - PA", "P5 350", "AK26-116"),
    "400579": ("PA", "P5 Tex - PA", "P5 Tex", "AE28-064"),
    "154652": ("MX", "Rhotex 325-1 - MX", "Rhotex 325", "AD20-049"),
    "152619": ("MX", "Rhotex 325-2 - MX", "Rhotex 325", "AD28-047"),
    "298128": ("MX", "P5-350 - MX", "P5 350", "AK26-118"),
    "298183": ("MX", "P5 Tex-1 - MX", "P5 Tex", "AE28-020"),
    "405629": ("MX", "P5 Tex-2 - MX", "P5 Tex", "AE28-069"),
}
ORDER = list(PRINTERS)
ACT = ("Test pattern printed", "Purge cycle run")
PURGE = "Maintenance Purge"


def parse_dump(text):
    lines = [l for l in text.strip().splitlines() if l.strip()]
    d0, d1, pulled = lines[0][2:].split("|")
    tasks = lines[1][2:].split(";")
    events, purges = {}, {}
    for l in lines[2:]:
        key, val = l.split("=", 1)
        if key.startswith("PC"):
            pid = key[2:]
            purges[pid] = {x.split(":")[0]: int(x.split(":")[1]) for x in val.split()}
        else:
            pid, sysn = key[1:].split("|")
            days = {}
            for part in val.split():
                day, items = part.split(":", 1)
                m = {}
                for it in items.split("."):
                    a, kind, c = re.match(r"(\d+)([wdla])(\d+)$", it).groups()
                    m[(tasks[int(a)], kind)] = int(c)
                days[day] = m
            events[sysn] = (pid, days)
    return d0, d1, pulled, tasks, events, purges


def load_log(path):
    """Accepts Sheets values JSON ({"values": [...]}), a Drive read_file_content result
    ({"fileContent": "...csv..."}), or a plain CSV export of the Log tab."""
    import csv, io
    raw = open(path, encoding="utf-8").read()
    try:
        j = json.loads(raw)
        if isinstance(j, dict) and "values" in j:
            return j["values"]
        if isinstance(j, dict) and "fileContent" in j:
            raw = j["fileContent"]
    except ValueError:
        pass
    m = re.search(r"```[^\n]*\n(.*?)```", raw, re.S)   # Drive wraps each tab in a fenced block
    if m:
        raw = m.group(1)
    rows = list(csv.reader(io.StringIO(raw.strip())))
    start = next((i for i, r in enumerate(rows) if r and r[0].strip() == "Timestamp"), 0)
    return rows[start:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump"); ap.add_argument("log")
    ap.add_argument("--html", default="printer-maintenance/index.html")
    ap.add_argument("--reminder", default="reminder.txt")
    a = ap.parse_args()

    d0, d1, pulled, tasks, events, purges = parse_dump(open(a.dump).read())
    start, end = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)
    days = [start + dt.timedelta(i) for i in range((end - start).days + 1)]
    TASKS = [t for t in tasks if t not in ACT]

    # floor sign-offs per system number per day
    so = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in load_log(a.log)[1:]:
        if len(r) < 8 or r[7] != "Completed":
            continue
        m = re.search(r"Sys # (\d+)", r[4])
        if not m:
            continue
        try:
            d = dt.datetime.strptime(r[0].split(",")[0].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        so[m.group(1)][d.isoformat()].append(r[5])

    sotl = []
    def si(t):
        if t not in sotl:
            sotl.append(t)
        return sotl.index(t)

    out = {"days": [d.isoformat() for d in days], "tasks": TASKS, "so": sotl, "printers": [],
           "meta": {"pulled": pulled, "from": d0, "to": d1}}
    S = {"done": "d", "off": "o", "open": "p"}
    stats = []
    for sysn in ORDER:
        if sysn not in events:
            continue
        plant, name, model, ser = PRINTERS[sysn]
        pid, ev = events[sysn]
        is325 = model.startswith("Rhotex")
        rows = []
        st = collections.Counter(); offt = collections.Counter()
        for d in days:
            k = d.isoformat(); m = ev.get(k, {})
            p = m.get(("Purge cycle run", "a"), 0) if is325 else purges.get(pid, {}).get(k, 0)
            p = 1 if p >= 1000 else min(p, 99)  # one logging glitch showed 1,106 cycles in a day
            tp = m.get(("Test pattern printed", "a"), 0)
            t = {}
            for i, name_t in enumerate(TASKS):
                w, dn, lt = (m.get((name_t, x), 0) for x in "wdl")
                if name_t == PURGE:
                    if w or lt or dn:
                        t[str(i)] = [S["done" if (p > 0 or dn) else "off"], w + lt]
                elif is325:
                    if dn: t[str(i)] = [S["done"], lt]
                    elif lt: t[str(i)] = [S["off"], lt]
                elif w:
                    t[str(i)] = [S["open"], w]
            sig = so[sysn].get(k, [])
            rows.append([t, p, tp, len(sig), [si(x) for x in sorted(set(sig))]])
            pi = str(TASKS.index(PURGE)) if PURGE in TASKS else None
            if pi in t:
                st["purge_days"] += 1
                if t[pi][0] == "d": st["purge_done"] += 1
                elif sig: st["skip_signed"] += 1
            for kk, (s_, n) in t.items():
                if s_ == "o" and kk != pi: offt[TASKS[int(kk)]] += 1
            if t or p or tp: st["active"] += 1
            if tp: st["tp_days"] += 1
            if p: st["purge_cycle_days"] += 1
        out["printers"].append({"id": int(pid), "plant": plant, "name": name, "model": model,
                                "serial": ser, "sys": sysn, "d": rows})
        stats.append((name, plant, st, offt))

    # findings (whole window)
    tot_skip = sum(s["purge_days"] - s["purge_done"] for _, _, s, _ in stats)
    tot_signed = sum(s["skip_signed"] for _, _, s, _ in stats)
    rate = lambda s: s["purge_done"] / s["purge_days"] if s["purge_days"] else None
    ranked = sorted([x for x in stats if x[2]["purge_days"] >= 10], key=lambda x: rate(x[2]))
    find = [f"<b>Maintenance Purge put off on {tot_skip} printer-days.</b> The printer asked for a purge, it was put off "
            f"(Remind later, or the prompt kept repeating), and no purge cycle ran that day."]
    if ranked:
        best, worst = ranked[-1], ranked[:2]
        never = [x[0] for x in stats if x[2]["purge_days"] == 0 and x[2]["purge_cycle_days"]]
        s = (f"<b>Best:</b> {best[0]} ran a purge on {best[2]['purge_done']} of {best[2]['purge_days']} prompt days. "
             + "<b>Worst:</b> " + "; ".join(f"{w[0]} on {w[2]['purge_done']} of {w[2]['purge_days']}" for w in worst) + ".")
        if never:
            s += " " + ", ".join(never) + (" purges often enough that the prompt never fired." if len(never) == 1 else " purge often enough that the prompt never fired.")
        find.append(s)
    other = sorted(((n, t, c) for n, _, _, o in stats for t, c in o.items()), key=lambda x: -x[2])[:2]
    if other and other[0][2] >= 10:
        find.append("<b>Other prompts put off most:</b> " + "; ".join(f"{t} on {n}, {c} days" for n, t, c in other) + ".")
    low_tp = [x for x in stats if x[2]["active"] >= 20 and x[2]["tp_days"] < 0.3 * x[2]["active"]]
    for n, _, s_, _ in low_tp[:2]:
        find.append(f"<b>{n} printed a nozzle test on only {s_['tp_days']} of {s_['active']} days with activity.</b>")
    find.append(f"<b>The floor sign-off sheet doesn't catch it.</b> On {tot_signed} of those {tot_skip} days, operators still "
                f"signed off tasks for that printer in the Machine Maintenance Log.")
    out["meta"]["find"] = find

    # inject into page
    html = open(a.html).read()
    i = html.index("const DATA=") + len("const DATA=")
    j = html.index(";\n(function(){", i)
    html = html[:i] + json.dumps(out, separators=(",", ":")) + html[j:]
    open(a.html, "w").write(html)

    # reminder: yesterday (Pacific), per plant
    y = (dt.datetime.fromisoformat(pulled.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles")).date()
         - dt.timedelta(days=1)).isoformat()
    yi = out["days"].index(y) if y in out["days"] else len(days) - 2
    ydate = dt.date.fromisoformat(out["days"][yi])
    msg = [f"*Printer maintenance: {ydate.strftime('%a %b %-d')}* (from Durst Analytics)"]
    for plant in ("CA", "PA", "MX"):
        lines = []
        for p in out["printers"]:
            if p["plant"] != plant: continue
            t, pc, tp, sc, _ = p["d"][yi]
            if not t and not pc and not tp: continue
            off = [TASKS[int(k)] for k, v in t.items() if v[0] == "o"]
            if off:
                note = "Purge put off, no purge ran" if PURGE in off else ""
                rest = [x for x in off if x != PURGE]
                parts = [x for x in [note, ("Put off: " + ", ".join(rest)) if rest else ""] if x]
                lines.append(f"• {p['name']} ({p['sys']}): " + "; ".join(parts) + f". Floor sign-offs: {sc}")
        msg.append(f"\n*{plant}*")
        msg.extend(lines or ["• Nothing put off"])
    msg.append("\nDetails and close-out: https://equipflow-lemon.vercel.app/printer-maintenance/")
    open(a.reminder, "w").write("\n".join(msg) + "\n")
    print(f"ok: {len(out['printers'])} printers, {d0}..{d1}, reminder for {ydate}")


if __name__ == "__main__":
    sys.exit(main())
