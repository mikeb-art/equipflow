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

# WS Display purge and nozzle-check policy (Nov 2026). Times are printer-local; activity is known by the hour (PH mask),
# purges and nozzle checks (test patterns) to the minute.
#  - Nozzle check before work: at every startup (first activity after IDLE_H+ hours with nothing logged: overnight,
#    weekend, downtime) a nozzle check must be printed before work. Late when the printer was active in an hour before
#    (check hour - GRACE_H); the grace covers power-on, initializing and ink heating.
#  - Purge every 24 hours, all plants: late when the printer worked more than 24 hours after its last purge, not
#    counting the GRACE_H hour(s) before the next purge. Idle time doesn't count until the printer works again.
# For reference, the Durst manuals (Rhotex 325 §H.14.2.1, P5 Tex §H.17.2.1, P5 350 §H.15.2.1) ask for a purge cycle "daily before starting
# work (once every 24 hours in case of 24-hour operation)" followed by a test image.
GRACE_H = 1
IDLE_H = 4

# Due dates come from the printer itself: a task counts as open when Durst asked for it (prompt or Remind later)
# and it hasn't been logged done since. No fixed intervals.


def parse_dump(text):
    lines = [l for l in text.strip().splitlines() if l.strip()]
    d0, d1, pulled = lines[0][2:].split("|")
    tasks = lines[1][2:].split(";")
    events, purges = {}, {}
    ptimes, phours, ntimes = {}, {}, {}
    for l in lines[2:]:
        key, val = l.split("=", 1)
        if key.startswith("PT"):   # purge cycle times, HHMM + c|t, printer-local
            ptimes[key[2:]] = {x.split(":")[0]: x.split(":")[1].split(".") for x in val.split()}
        elif key.startswith("PN"):   # nozzle check (test pattern) times, HHMM, printer-local; empty = none that day
            ntimes[key[2:]] = {x.split(":")[0]: [t for t in x.split(":")[1].split(".") if t] for x in val.split()}
        elif key.startswith("PH"):   # hex mask of the hours the printer logged anything
            phours[key[2:]] = {x.split(":")[0]: int(x.split(":")[1], 16) for x in val.split()}
        elif key.startswith("PC"):
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
    return d0, d1, pulled, tasks, events, purges, ptimes, phours, ntimes


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


def serialize(d0, d1, pulled, events, purges, ptimes=None, phours=None, ntimes=None):
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
    pts = [f"PT{pid}=" + " ".join(f"{d}:{'.'.join(t)}" for d, t in sorted(v.items()) if t) for pid, v in (ptimes or {}).items()]
    phs = [f"PH{pid}=" + " ".join(f"{d}:{m:x}" for d, m in sorted(v.items())) for pid, v in (phours or {}).items()]
    pns = [f"PN{pid}=" + " ".join(f"{d}:{'.'.join(t)}" for d, t in sorted(v.items())) for pid, v in (ntimes or {}).items()]
    return "\n".join([f"D={d0}|{d1}|{pulled}", "T=" + ";".join(tasks)] + lines + pcs + pts + phs + pns) + "\n"


def merge_history(hist_text, new):
    """Replace every day the new pull covers, keep older history, trim to KEEP_DAYS."""
    nd0, nd1, npulled, _, nev, npc, npt, nph, npn = new
    if not hist_text:
        hd0, hev, hpc, hpt, hph, hpn = nd0, {}, {}, {}, {}, {}
    else:
        hd0, _, _, _, hev, hpc, hpt, hph, hpn = parse_dump(hist_text)
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
    def mergeby(h, n):
        out = {}
        for pid in set(h) | set(n):
            v = {d: x for d, x in h.get(pid, {}).items() if d < nd0 and keep(d)}
            v.update({d: x for d, x in n.get(pid, {}).items() if keep(d)})
            out[pid] = v
        return out
    # Days before the per-shift pull existed have no PH entry: those shifts show as "no data", not as missed.
    return start.isoformat(), nd1, npulled, ev, pc, mergeby(hpt, npt), mergeby(hph, nph), mergeby(hpn, npn)


def hm(s):
    return int(s[:2]) * 60 + int(s[2:4]) if s[2:3] != ":" else int(s[:2]) * 60 + int(s[3:5])


def _active_hours(hours):
    """Absolute printer-local hours (days since 2000-01-01 * 24 + hour) with logged activity."""
    base = dt.date(2000, 1, 1)
    out = []
    for d, m in hours.items():
        o = (dt.date.fromisoformat(d) - base).days * 24
        out += [o + h for h in range(24) if m >> h & 1]
    return sorted(out)


def _abs_min(d, t):
    return (dt.date.fromisoformat(d) - dt.date(2000, 1, 1)).days * 1440 + hm(t)


def _fmt_min(m):
    d = dt.date(2000, 1, 1) + dt.timedelta(m // 1440)
    return f"{d.strftime('%b %-d')} {m % 1440 // 60:02d}:{m % 60:02d}"


def purge_status(days, times, hours):
    """Purge every 24 hours. One entry per day: [code, text]. code: g = on time, l = purged, but more than 24 hrs
    after the last one, m = printer worked over 24 hrs past its last purge and no purge that day, n = no activity,
    u = no data (before purge times were pulled).
    text: short explanation for the page tooltip and the Chat reminder."""
    act = _active_hours(hours)
    purges = sorted(_abs_min(d, t) for d, ts in times.items() for t in ts)
    first_data = min(hours) if hours else None
    out = []
    for day in days:
        k = day.isoformat()
        if first_data is None or k < first_data or k not in hours:
            out.append(["u", ""]); continue
        o = (day - dt.date(2000, 1, 1)).days
        day_act = [h for h in act if o * 24 <= h < o * 24 + 24]
        day_p = [x for x in purges if o * 1440 <= x < o * 1440 + 1440]
        if not day_act:
            out.append(["n", ""]); continue
        # rolling 24 hours: walk the purge gaps that touch this day
        prev = [x for x in purges if x < o * 1440]
        lastp = prev[-1] if prev else (dt.date.fromisoformat(first_data) - dt.date(2000, 1, 1)).days * 1440
        known = bool(prev)
        later = [x for x in purges if x >= (o + 1) * 1440]
        late, missing = [], None
        for nxt in day_p + [None]:
            due = lastp + 1440
            qh = (nxt // 60) if nxt is not None else (later[0] // 60 if later else 10 ** 9)
            over = [h for h in day_act if h * 60 + 60 > due and h < qh - GRACE_H]
            if over:
                since = f"last one {_fmt_min(lastp)}" if known else f"none since {_fmt_min(lastp)[:-6]}"
                if nxt is None:
                    missing = f"Over 24 hrs without a purge ({since})"
                else:
                    late.append(f"Purged {_fmt_min(nxt)[-5:]}, {round((nxt - lastp) / 60)} hrs after the last one"
                                if known else f"Purged {_fmt_min(nxt)[-5:]}, first since {_fmt_min(lastp)[:-6]}")
            if nxt is None:
                break
            lastp, known = nxt, True
        if missing and not day_p:
            out.append(["m", missing])
        elif not known and not day_p:
            out.append(["u", ""])   # first days of purge-time data: last purge unknown
        elif late or missing:
            out.append(["l", "; ".join(late + ([missing] if missing else []))])
        else:
            out.append(["g", f"Purged {_fmt_min(day_p[0])[-5:]}" + (f" (+{len(day_p) - 1} more)" if len(day_p) > 1 else "") if day_p
                        else f"Within 24 hrs of the last purge ({_fmt_min(lastp)})"])
    return out


def _starts(act):
    """Startup hours: first activity after IDLE_H+ hours with nothing logged."""
    aset = set(act)
    return [h for h in act if not any(h - k in aset for k in range(1, IDLE_H + 1))]


def purge_start_warning(days, times, hours, pcodes):
    """Warning only (doesn't change the 24-hour purge code): the Durst manuals ask for the purge daily before starting
    work. Checks the first startup of each day. Returns one text per day, "" when fine or not applicable (no startup,
    no purge-time data, or already flagged as over 24 hrs without a purge)."""
    act = _active_hours(hours)
    starts = _starts(act)
    purges = sorted(_abs_min(d, t) for d, ts in times.items() for t in ts)
    first_data = min(hours) if hours else None
    out = []
    for day, pc in zip(days, pcodes):
        k = day.isoformat()
        o = (day - dt.date(2000, 1, 1)).days
        st_ = [h for h in starts if o * 24 <= h < o * 24 + 24]
        if first_data is None or k < first_data or k not in hours or not st_ or pc in "mnu":
            out.append(""); continue
        s0 = st_[0]
        if any(o * 1440 <= x < s0 * 60 - 60 for x in purges):   # already purged earlier that day (e.g. a run from overnight)
            out.append(""); continue
        nxt_start = next((h for h in starts if h > s0), 10 ** 9)
        hh = f"{s0 % 24:02d}:00"
        c = next((x for x in purges if s0 * 60 - 60 <= x < nxt_start * 60), None)
        if c is None:
            later = [x for x in purges if s0 * 60 <= x < (o + 1) * 1440]
            out.append(f"No purge before work at {hh}" + (f" (purged {_fmt_min(later[0])[-5:]})" if later else ""))
        elif any(h < c // 60 - GRACE_H for h in act if s0 <= h < nxt_start):
            out.append(f"Purge {_fmt_min(c)[-5:]}, after work started at {hh}")
        else:
            out.append("")
    return out


def nozzle_status(days, ntimes, hours):
    """Nozzle check before work at each startup. One entry per day: [code, text]. code: g = every startup that day
    had its nozzle check before work, l = a check ran, but after work started, m = no check after a startup,
    n = no startup that day (printer idle, or still running from the day before), u = no nozzle-check data yet."""
    act = _active_hours(hours)
    aset = set(act)
    checks = sorted(_abs_min(d, t) for d, ts in ntimes.items() for t in ts)
    first_data = min(ntimes) if ntimes else None
    starts = [h for h in act if not any(h - k in aset for k in range(1, IDLE_H + 1))]
    out = []
    for day in days:
        k = day.isoformat()
        if first_data is None or k < first_data or (k in hours and k not in ntimes):
            out.append(["u", ""]); continue
        o = (day - dt.date(2000, 1, 1)).days
        st_ = [h for h in starts if o * 24 <= h < o * 24 + 24]
        if not st_:
            out.append(["n", ""]); continue
        worst, txt = "g", []
        for s0 in st_:
            nxt_start = next((h for h in starts if h > s0), 10 ** 9)
            c = next((x for x in checks if s0 * 60 - 60 <= x < nxt_start * 60), None)   # check in this run (or the hour before)
            hh = f"{s0 % 24:02d}:00"
            if c is None:
                worst = "m"; txt.append(f"No nozzle check after startup at {hh}")
            elif any(h < c // 60 - GRACE_H for h in act if s0 <= h < nxt_start):
                worst = worst if worst == "m" else "l"
                txt.append(f"Nozzle check {_fmt_min(c)[-5:]}, after work started at {hh}")
            else:
                txt.append(f"Nozzle check {_fmt_min(c)[-5:]} at startup ({hh})")
        out.append([worst, "; ".join(txt)])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump"); ap.add_argument("log")
    ap.add_argument("--html", default="printer-maintenance/index.html")
    ap.add_argument("--reminder", default="printer-maintenance/data/reminder.txt")
    ap.add_argument("--history", default="printer-maintenance/data/history.txt",
                    help="stored rolling history; the new pull is merged into it and it is rewritten")
    ap.add_argument("--maint-html", default="maintenance/index.html",
                    help="Machine Maintenance page: machine and task list for the Other maintenance status")
    ap.add_argument("--card", default="printer-maintenance/data/card.json", help="Google Chat card message")
    ap.add_argument("--charts", default="printer-maintenance/data/charts", help="Folder for the dated Other maintenance charts")
    ap.add_argument("--other", default="printer-maintenance/data/other.json", help="Other maintenance status")
    a = ap.parse_args()

    new = parse_dump(open(a.dump).read())
    import os
    hist = open(a.history).read() if a.history and os.path.exists(a.history) else ""
    d0, d1, pulled, events, purges, ptimes, phours, ntimes = merge_history(hist, new)
    merged_text = serialize(d0, d1, pulled, events, purges, ptimes, phours, ntimes)
    if a.history:
        os.makedirs(os.path.dirname(a.history) or ".", exist_ok=True)
        open(a.history, "w").write(merged_text)
    _, _, _, tasks, events, purges, ptimes, phours, ntimes = parse_dump(merged_text)
    start, end = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)
    days = [start + dt.timedelta(i) for i in range((end - start).days + 1)]
    TASKS = [t for t in tasks if t not in ACT]

    # floor sign-offs per system number per day
    so = collections.defaultdict(lambda: collections.defaultdict(list))
    log_rows = load_log(a.log)[1:]
    for r in log_rows:
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
           "meta": {"pulled": pulled, "from": d0, "to": d1, "grace_h": GRACE_H, "idle_h": IDLE_H}}
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
        # per task: last day done (purge: a purge cycle also counts), last day Durst asked, and since when it's open
        # (asked after the last done and not done since)
        last = {}
        for i, name_t in enumerate(TASKS):
            ld = la = od = None
            for k, r in zip(days, rows):
                v = r[0].get(str(i))
                if not v and not (name_t == PURGE and r[1]):
                    continue
                if v: la = k
                if (v and v[0] == "d") or (name_t == PURGE and r[1]):
                    ld, od = k, None
                elif od is None:
                    od = k
            if la or ld:   # skip tasks this printer's software never raises
                last[str(i)] = [ld.isoformat() if ld else None, la.isoformat() if la else None, od.isoformat() if od else None]
        rec = {"id": int(pid), "plant": plant, "name": name, "model": model,
               "serial": ser, "sys": sysn, "d": rows, "last": last}
        # rec["sh"][day] = [purge code + nozzle-check code, [purge text, nozzle text]] (see purge_status, nozzle_status)
        ps = purge_status(days, ptimes.get(pid, {}), phours.get(pid, {}))
        ns = nozzle_status(days, ntimes.get(pid, {}), phours.get(pid, {}))
        pw = purge_start_warning(days, ptimes.get(pid, {}), phours.get(pid, {}), [x[0] for x in ps])
        # third element (only when set): warning that the purge didn't come before work at the day's first startup
        rec["sh"] = [[a_[0] + b_[0], [a_[1], b_[1]]] + ([w_] if w_ else []) for a_, b_, w_ in zip(ps, ns, pw)]
        for d, (code, *_) in zip(days, rec["sh"]):
            if d.weekday() < 5:
                st["sh_active"] += code[0] in "glm"; st["sh_ok"] += code[0] == "g"
                st["nz_active"] += code[1] in "glm"; st["nz_ok"] += code[1] == "g"
        out["printers"].append(rec)
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
    for ka, ko, label in (("sh_active", "sh_ok", "Purge every 24 hours"), ("nz_active", "nz_ok", "Nozzle check before work")):
        n_ = sum(s[ka] for _, _, s, _ in stats)
        if n_ < 10:
            continue
        by = []
        for pl in ("MX", "PA", "CA"):
            a_ = sum(s[ka] for _, p_, s, _ in stats if p_ == pl); o_ = sum(s[ko] for _, p_, s, _ in stats if p_ == pl)
            if a_: by.append(f"{pl} {round(o_ / a_ * 100)}%")
        find.append(f"<b>{label}:</b> on time on {sum(s[ko] for _, _, s, _ in stats)} of {n_} weekday printer-days "
                    f"({', '.join(by)}).")
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
    msg = [f"*Previous 24 hrs maintenance: {ydate.strftime('%a %b %-d')}* (from Durst Analytics)"]
    printer_lines = {}
    for plant in ("CA", "PA", "MX"):
        lines = []
        for p in out["printers"]:
            if p["plant"] != plant: continue
            t, pc, tp, sc, _ = p["d"][yi]
            off = [TASKS[int(k)] for k, v in t.items() if v[0] == "o"]
            parts = []
            code, txt = p["sh"][yi][:2]
            parts += [t for c, t in zip(code, txt) if c in "lm"]
            if len(p["sh"][yi]) > 2:
                parts.insert(1 if code[0] in "lm" else 0, p["sh"][yi][2])
            if PURGE in off: parts.append("Purge put off, no purge ran")
            rest = [x for x in off if x != PURGE]
            if rest: parts.append("Put off: " + ", ".join(rest))
            # tasks Durst asked for earlier that still haven't been logged done (yesterday's put-offs are listed above)
            late = []
            for k, (ld, la, od) in p["last"].items():
                if not od or TASKS[int(k)] in off or int(k) == TASKS.index(PURGE): continue
                if od >= out["days"][yi]: continue
                late.append(f"{TASKS[int(k)]} (asked since {dt.date.fromisoformat(od).strftime('%b %-d')})")
            if late: parts.append("Still open: " + ", ".join(late))
            if parts:
                lines.append(f"• {p['name']}: " + "; ".join(parts))
        printer_lines[plant] = [x[2:] for x in lines]
        msg.append(f"\n*{plant}*")
        msg.extend(lines or ["• Nothing put off or open"])
    msg.append("\nDetails and close-out: https://equipflow-lemon.vercel.app/printer-maintenance/")

    # Other maintenance (Monti, Vutek, Klieverik sign-offs) as of the post's morning, plus the Chat card
    import other_maintenance as om
    today = dt.datetime.fromisoformat(pulled.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles")).date()
    ost = om.status(om.load_spec(a.maint_html), log_rows, today)
    json.dump(ost, open(a.other, "w"), indent=1)
    msg.extend(om.text_lines(ost))
    open(a.reminder, "w").write("\n".join(msg) + "\n")
    # Each post gets its own chart file: Google Chat fetches the picture again when an old post is viewed, so a file
    # overwritten every day made old posts show today's chart. Charts older than 120 days are removed.
    ver = re.sub(r"\D", "", pulled)[:14]
    os.makedirs(a.charts, exist_ok=True)
    name = f"other-{ver}.png"
    om.chart(ost, os.path.join(a.charts, name))
    import printer_grid as pg
    grid = pg.rows_for_day(out, TASKS, yi, PURGE)
    gname = f"printers-{ver}.png"
    pg.chart(grid, f"Printers yesterday: {ydate.strftime('%a %b %-d')}", os.path.join(a.charts, gname))
    cutoff = (today - dt.timedelta(120)).strftime("%Y%m%d")
    for f in os.listdir(a.charts):
        m = re.fullmatch(r"(?:other|printers)-(\d{8})\d*\.png", f)
        if m and m.group(1) < cutoff:
            os.remove(os.path.join(a.charts, f))
    img = f"{om.SITE}/printer-maintenance/data/{os.path.basename(a.charts)}/{name}"
    gimg = f"{om.SITE}/printer-maintenance/data/{os.path.basename(a.charts)}/{gname}"
    title = f"Previous 24 hrs maintenance: {ydate.strftime('%a %b %-d')}"
    json.dump(om.card(title, printer_lines, ost, img, gimg), open(a.card, "w"), indent=1)
    print(f"ok: {len(out['printers'])} printers, {d0}..{d1}, reminder for {ydate}, other maintenance as of {today}: "
          + ", ".join(f"{p} {v['pct']}%" for p, v in ost["plants"].items()))


if __name__ == "__main__":
    sys.exit(main())
