"""Printer status grid for the daily Printing post: one row per printer, one colored cell per check (purge, nozzle check,
put-off / open tasks), so the post can be read at a glance. Used by build.py; the long text stays in reminder.txt and in
the card's collapsed details section.

Cell levels: ok (green), warn (amber), bad (red), idle (grey: printer didn't work that day), na (no data yet).
"""
import datetime as dt, re

PLANTS = ("CA", "PA", "MX")
SHORT = {   # Durst task names -> short labels for the grid
    "Maintenance Purge": "Purge", "Inspect Print Plane": "Print plane", "Guiding Rail Oiling": "Rail oiling",
    "Dust/Air Filter Inspect": "Dust filter", "Aerosol Filter Inspect": "Aerosol filter", "Roller Inspect": "Rollers",
    "Stretch Roller Inspect": "Stretch roller", "Water Level Cooling Unit Inspect": "Cooling water",
    "Change Stretch Rollers": "Change stretch rollers", "Refill Bearings": "Bearings",
    "Change lubricating plates": "Lube plates", "Maintenance Service Call": "Service call",
}


def _short_name(name):
    """'Rhotex 325-2 - MX' -> 'Rhotex 325-2' (the plant is the group label)."""
    return re.sub(r"\s+-\s+(CA|PA|MX)$", "", name)


def _times(txt):
    return re.findall(r"\b\d\d:\d\d\b", txt)


def purge_cell(code, txt, warn):
    """code/txt from purge_status, warn from purge_start_warning."""
    if code == "n":
        return "idle", "Idle"
    if code == "u":
        return "na", "–"
    if code == "m":
        m = re.search(r"last one (\w+ \d+)", txt) or re.search(r"since (\w+ \d+)", txt)
        return "bad", "None since " + m.group(1) if m else "None in 24 hrs"
    if code == "l":
        m = re.search(r"Purged (\d\d:\d\d), (\d+) hrs", txt)
        t = f"{m.group(1)} · {m.group(2)} hrs gap" if m else "Late"
        if "Over 24 hrs" in txt:
            return "bad", t + ", then over 24 hrs"
        return "warn", t
    # on time; the before-work warning still makes it amber
    if warn:
        if warn.startswith("No purge before work"):
            later = re.search(r"purged (\d\d:\d\d)", warn)
            return "warn", (later.group(1) + " · " if later else "") + "not before work"
        t = _times(warn)
        return "warn", (t[0] + " · " if t else "") + "after work started"
    t = _times(txt)
    return "ok", ("✓ " + t[0]) if t and txt.startswith("Purged") else "✓ within 24 hrs"


def nozzle_cell(code, txt):
    if code == "n":
        return "idle", "No startup"
    if code == "u":
        return "na", "–"
    parts = [x for x in txt.split("; ") if x]
    missed = [_times(x)[0] for x in parts if x.startswith("No nozzle check")]
    late = [x for x in parts if "after work started" in x]
    if missed:
        n = len(parts)
        return "bad", (f"Missed {len(missed)} of {n} startups" if n > 1 else f"Missed (start {missed[0]})")
    if late:
        return "warn", f"{_times(late[0])[0]} · after work started"
    t = [_times(x)[0] for x in parts if _times(x)]
    return "ok", "✓ " + ", ".join(t[:2]) if t else "✓"


def tasks_cell(off, still_open):
    """off: task names put off that day; still_open: names asked for earlier and still not done."""
    if not off and not still_open:
        return "ok", "✓ None"
    names = sorted((SHORT.get(x, x) for x in off), key=lambda n: (n != "Purge", n))
    txt = ", ".join(names)
    if still_open:
        txt += (" + " if txt else "") + f"{len(still_open)} older open"
    return ("bad" if "Maintenance Purge" in off else "warn"), txt


def rows_for_day(out, tasks, yi, purge_name):
    """One row per printer for day index yi of the page data (build.py's `out`)."""
    rows = []
    for plant in PLANTS:
        for p in out["printers"]:
            if p["plant"] != plant:
                continue
            t = p["d"][yi][0]
            off = [tasks[int(k)] for k, v in t.items() if v[0] == "o"]
            still = [tasks[int(k)] for k, (ld, la, od) in p["last"].items()
                     if od and od < out["days"][yi] and tasks[int(k)] not in off and tasks[int(k)] != purge_name]
            code, (ptxt, ntxt) = p["sh"][yi][0], p["sh"][yi][1]
            warn = p["sh"][yi][2] if len(p["sh"][yi]) > 2 else ""
            rows.append({"plant": plant, "name": _short_name(p["name"]),
                         "cells": [purge_cell(code[0], ptxt, warn), nozzle_cell(code[1], ntxt), tasks_cell(off, still)]})
    return rows


COLS = ("Purge", "Nozzle check", "Put off / still open")
FILL = {"ok": "#e3f4ec", "warn": "#fdefd9", "bad": "#fde2e0", "idle": "#f1f3f6", "na": "#f1f3f6"}
DOT = {"ok": "#199e70", "warn": "#d97a16", "bad": "#d1352b", "idle": "#a9b1bd", "na": "#a9b1bd"}
INK, MUTED = "#1f2733", "#6b7688"


def chart(rows, title, png_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Circle

    plants = [pl for pl in PLANTS if any(r["plant"] == pl for r in rows)]
    RH, GAP, HEAD, TOP = 0.42, 0.34, 0.42, 0.62      # inches: row height, plant gap, column header, title
    W = 9.0
    x0 = [0.18, 2.05, 4.35, 6.35]                    # name, purge, nozzle, tasks (left edges, inches)
    cw = [x0[2] - x0[1] - 0.08, x0[3] - x0[2] - 0.08, W - 0.18 - x0[3]]
    H = TOP + HEAD + len(rows) * RH + len(plants) * GAP + 0.45
    fig = plt.figure(figsize=(W, H), dpi=200)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")

    ax.text(x0[0], 0.36, title, fontsize=13, fontweight="bold", color=INK, va="center")
    y = TOP
    for i, c in enumerate(COLS):
        ax.text(x0[i + 1] + 0.28, y + HEAD / 2, c, fontsize=9, fontweight="bold", color=MUTED, va="center")
    y += HEAD
    for pl in plants:
        y += GAP * 0.15
        ax.text(x0[0], y + GAP * 0.45, pl, fontsize=10.5, fontweight="bold", color=INK, va="center")
        ax.plot([x0[0] + 0.42, W - 0.18], [y + GAP * 0.45] * 2, color="#e3e7ee", lw=1)
        y += GAP * 0.85
        for r in [r for r in rows if r["plant"] == pl]:
            ax.text(x0[0] + 0.1, y + RH / 2, r["name"], fontsize=9.5, color=INK, va="center")
            for i, (lvl, txt) in enumerate(r["cells"]):
                bx = x0[i + 1]
                ax.add_patch(FancyBboxPatch((bx, y + 0.05), cw[i], RH - 0.1, boxstyle="round,pad=0,rounding_size=0.07",
                                            fc=FILL[lvl], ec="none"))
                ax.add_patch(Circle((bx + 0.15, y + RH / 2), 0.05, color=DOT[lvl]))
                fs = 8.6 if len(txt) <= 30 else 7.6
                ax.text(bx + 0.28, y + RH / 2, txt, fontsize=fs, color=INK if lvl not in ("idle", "na") else MUTED,
                        va="center", fontweight="bold" if lvl == "bad" else "normal", clip_on=True)
            y += RH
    # legend
    for lx, (lvl, lab) in zip((0, 0.95, 2.25, 3.15), (("ok", "On time"), ("warn", "Late / warning"), ("bad", "Missed"),
                                                     ("idle", "Idle / no data"))):
        ax.add_patch(Circle((x0[0] + lx + 0.06, H - 0.22), 0.05, color=DOT[lvl]))
        ax.text(x0[0] + lx + 0.18, H - 0.22, lab, fontsize=8, color=MUTED, va="center")
    fig.savefig(png_path, facecolor="white")
    plt.close(fig)


def attention(rows):
    """Short lines for the red cells only, for the card text under the grid."""
    out = []
    for r in rows:
        bad = [f"{c.lower()}: {t}" for c, (lvl, t) in zip(("Purge", "Nozzle check", "Put off"), r["cells"]) if lvl == "bad"]
        if bad:
            out.append(f"{r['plant']} {r['name']} – " + "; ".join(bad))
    return out
