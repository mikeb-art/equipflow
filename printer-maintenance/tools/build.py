#!/usr/bin/env python3
"""Rebuild Printer Maintenance data from a Durst pull + the Machine Maintenance Log.

usage: build.py DUMP.txt LOG.json [--html printer-maintenance/index.html] [--reminder printer-maintenance/data/reminder.txt]

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

# How often each Durst-prompted task is due, in days, from the maintenance schedules (schedules.html).
# The printer keeps its own due dates; these are the manual's intervals, used to flag overdue tasks.
_P5 = {"Maintenance Purge": 1, "Inspect Print Plane": 1, "Roller Inspect": 1,
       "Guiding Rail Oiling": 7, "Water Level Cooling Unit Inspect": 7}
EVERY = {
    "Rhotex 325": {"Maintenance Purge": 1, "Stretch Roller Inspect": 1, "Inspect Print Plane": 1,
                   "Guiding Rail Oiling": 7, "Roller Inspect": 7, "Dust/Air Filter Inspect": 7,
                   "Water Level Cooling Unit Inspect": 7, "Change lubricating plates": 182},
    "P5 350": {**_P5, "Dust/Air Filter Inspect": 2, "Refill Bearings": 182},
    "P5 Tex": {**_P5, "Stretch Roller Inspect": 1, "Aerosol Filter Inspect": 2, "Dust/Air Filter Inspect": 7},
}


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


KEEP_DAYS = 91


def serialize(d0, d1, pulled, events, purges):
    """Inverse of parse_dump (task names re-indexed)."""
    tasks = []
    def ti(t):
        if t not in tasks:
            tasks.append(t)
        return tasks.index(t)
    lines = []
    for sysn, (pid, days) in events.items():
        parts = []
        for day in sorted(days):
            items = ".".join(f"{ti(t)}{k}{c}" for (t, k), c in days[day].items())
            if items:
                parts.append(f"{day}:{items}")
        lines.append(f"P{pid}|{sysn}=" + " ".join(parts))
    pcs = [f"PC{pid}=" + " ".join(f"{d}:{n}" for d, n in sorted(v.items())) for pid, v in purges.items()]
    return "\n".join([f"D={d0}|{d1}|{pulled}", "T=" + ";".join(tasks)] + lines + pcs) + "\n"


def merge_history(hist_text, new):
    """Replace every day the new pull covers, keep older history, trim to KEEP_DAYS."""
    nd0, nd1, npulled, _, nev, npc = new
    if not hist_text:
        hd0, hev, hpc = nd0, {}, {}
    else:
        hd0, _, _, _, hev, hpc = parse_dump(hist_text)
    end = dt.date.fromisoformat(nd1)
    start = max(dt.date.fromisoformat(min(hd0, nd0)), end - dt.timedelta(days=KEEP_DAYS - 1))
    keep = lambda d: start.isoformat() <= d <= nd1
    ev = {}
    for sysn in set(hev) | set(nev):
        pid = (nev.get(sysn) or hev.get(sysn))[0]
        days = {d: m for d, m in (hev.get(sysn, (pid, {}))[1]).items() if d < nd0 and keep(d)}
        days.update({d: m for d, m in (nev.get(sysn, (pid, {}))[1]).items() if keep(d)})
        ev[sysn] = (pid, days)
    pc = {}
    for pid in set(hpc) | set(npc):
        v = {d: n for d, n in hpc.get(pid, {}).items() if d < nd0 and keep(d)}
        v.update({d: n for d, n in npc.get(pid, {}).items() if keep(d)})
        pc[pid] = v
    return start.isoformat(), nd1, npulled, ev, pc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump"); ap.add_argument("log")
    ap.add_argument("--html", default="printer-maintenance/index.html")
    ap.add_argument("--reminder", default="printer-maintenance/data/reminder.txt")
    ap.add_argument("--history", default="printer-maintenance/data/history.txt",
                    help="stored rolling history; the new pull is merged into it and it is rewritten")
    a = ap.parse_args()

    new = parse_dump(open(a.dump).read())
    import os
    hist = open(a.history).read() if a.history and os.path.exists(a.history) else ""
    d0, d1, pulled, events, purges = merge_history(hist, new)
    merged_text = serialize(d0, d1, pulled, events, purges)
    if a.history:
        os.makedirs(os.path.dirname(a.history) or ".", exist_ok=True)
        open(a.history, "w").write(merged_text)
    _, _, _, tasks, events, purges = parse_dump(merged_text)
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
                # Rhotex 325 logs "done" / "Remind later"; P5 logs the prompt and, for Execute, a "done" ID (see pull.js).
                elif dn:
                    t[str(i)] = [S["done"], w + lt]
                elif lt or w:
                    t[str(i)] = [S["off"], w + lt]
            sig = so[sysn].get(k, [])
            rows.append([t, p, tp, len(sig), [si(x) for x in sorted(set(sig))]])
            pi = str(TASKS.index(PURGE)) if PURGE in TASKS else None
            if d.weekday() >= 5:   # plants don't usually work weekends: weekend days stay in the data but not in the counts
                continue
            if pi in t:
                st["purge_days"] += 1
                if t[pi][0] == "d": st["purge_done"] += 1
                elif sig: st["skip_signed"] += 1
            for kk, (s_, n) in t.items():
                if s_ == "o" and kk != pi: offt[TASKS[int(kk)]] += 1
            if t or p or tp: st["active"] += 1
            if tp: st["tp_days"] += 1
            if p: st["purge_cycle_days"] += 1
        # last day each task was done (purge: a purge cycle also counts), and how overdue it is
        last = {}
        for i, name_t in enumerate(TASKS):
            ld = None
            for k, r in zip(days, rows):
                v = r[0].get(str(i))
                if (v and v[0] == "d") or (name_t == PURGE and r[1]):
                    ld = k
            iv = EVERY.get(model, {}).get(name_t)
            seen = any(str(i) in r[0] for r in rows)   # skip tasks this printer's software never raises
            if seen:
                last[str(i)] = [ld.isoformat() if ld else None, iv]
        out["printers"].append({"id": int(pid), "plant": plant, "name": name, "model": model,
                                "serial": ser, "sys": sysn, "d": rows, "last": last})
        stats.append((name, plant, st, offt))

    # findings (whole window)
    tot_skip = sum(s["purge_days"] - s["purge_done"] for _, _, s, _ in stats)
    tot_signed = sum(s["skip_signed"] for _, _, s, _ in stats)
    rate = lambda s: s["purge_done"] / s["purge_days"] if s["purge_days"] else None
    ranked = sorted([x for x in stats if x[2]["purge_days"] >= 10], key=lambda x: rate(x[2]))
    find = [f"<b>Maintenance Purge put off on {tot_skip} weekday printer-days.</b> The printer asked for a purge, it was put off "
            f"(Remind later, or the prompt kept repeating), and no purge cycle ran that day."]
    if ranked:
        best, worst = ranked[-1], ranked[:2]
        never = [x[0] for x in stats if x[2]["purge_days"] == 0 and x[2]["purge_cycle_days"]]
        s = (f"<b>Best:</b> {best[0]} ran a purge on {best[2]['purge_done']} of {best[2]['purge_days']} weekday prompt days. "
             + "<b>Worst:</b> " + "; ".join(f"{w[0]} on {w[2]['purge_done']} of {w[2]['purge_days']}" for w in worst) + ".")
        if never:
            s += " " + ", ".join(never) + (" purges often enough that the prompt never fired." if len(never) == 1 else " purge often enough that the prompt never fired.")
        find.append(s)
    other = sorted(((n, t, c) for n, _, _, o in stats for t, c in o.items()), key=lambda x: -x[2])[:2]
    if other and other[0][2] >= 10:
        find.append("<b>Other prompts put off most:</b> " + "; ".join(f"{t} on {n}, {c} days" for n, t, c in other) + ".")
    low_tp = [x for x in stats if x[2]["active"] >= 20 and x[2]["tp_days"] < 0.3 * x[2]["active"]]
    for n, _, s_, _ in low_tp[:2]:
        find.append(f"<b>{n} printed a nozzle test on only {s_['tp_days']} of {s_['active']} weekdays with activity.</b>")
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
            off = [TASKS[int(k)] for k, v in t.items() if v[0] == "o"]
            parts = []
            if PURGE in off: parts.append("Purge put off, no purge ran")
            rest = [x for x in off if x != PURGE]
            if rest: parts.append("Put off: " + ", ".join(rest))
            # weekly-and-longer tasks past their interval, as of the pull date
            late = []
            for k, (ld, iv) in p["last"].items():
                if not iv or iv < 7 or TASKS[int(k)] in off: continue
                if not ld: late.append(f"{TASKS[int(k)]} (none in {len(days)} days)")
                elif (end - dt.date.fromisoformat(ld)).days > iv:
                    late.append(f"{TASKS[int(k)]} (last {dt.date.fromisoformat(ld).strftime('%b %-d')})")
            if late: parts.append("Overdue: " + ", ".join(late))
            if parts:
                lines.append(f"• {p['name']}: " + "; ".join(parts))
        msg.append(f"\n*{plant}*")
        msg.extend(lines or ["• Nothing put off or overdue"])
    msg.append("\nDetails and close-out: https://equipflow-lemon.vercel.app/printer-maintenance/")
    open(a.reminder, "w").write("\n".join(msg) + "\n")
    print(f"ok: {len(out['printers'])} printers, {d0}..{d1}, reminder for {ydate}")


if __name__ == "__main__":
    sys.exit(main())
