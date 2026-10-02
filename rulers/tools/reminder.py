"""Writes the 7-days-ahead ruler reminder for the Google Chat "Printing" space.

usage: python3 rulers/tools/reminder.py [YYYY-MM-DD]   (default: today in Pacific time)
Prints the message if a due Wednesday is exactly 7 days after that date; prints nothing otherwise.
Due dates come from rulers/data/schedule.json (copied from the Ruler Verification Frequency Chart)."""
import datetime as dt, json, pathlib, sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
S = json.loads((ROOT / "data" / "schedule.json").read_text())

# Google Chat user IDs of the three print leads (from the Printing space member list), tagged in every reminder
LEADS = {"Todd": "106179057914934309628", "Toan": "112042970564499422793", "Christian": "100639998660371440140"}
MONTHLY = ["Stretch", "Black and White", "Backlit", "MultiStretch"]
QUARTERLY = ["Mesh", "Tent", "SilverBack", "SmoothWall"]
F = "https://docs.google.com/forms/d/e/{}/viewform"
FORMS = [("CA", [("Monti 1", "1FAIpQLSflJigWnoa1nc-t-YK7cNVL4JBHjpahTVIB-2dLIBUBnw7aDA"),
                 ("Monti 2", "1FAIpQLSd3Iebg5APeZj9G6nRSxtrSlRC6WMONMYTZOtBsd_wwtMivVA")]),
         ("MX", [("Monti 1", "1FAIpQLSdI2fxgS_Uev1hS_8bswSSQzqYwPotmF5ieq_ya2fex9jPkaw"),
                 ("Monti 3", "1FAIpQLSdN7iovMYwo40N90ix37hx61PyawgYA_tNFxLu6PnhC9scVvg"),
                 ("Monti 4", "1FAIpQLSeySrRIgy54jcVr1VMQL-ldFf0rIgyOrmy55G3DBKEvEdmnvA")]),
         ("PA", [("Monti 1", "1FAIpQLSfklHoCAlVuoNbz7ucnZo2rNY4dK1q9MHXXYtKXEeVUdkGWuQ"),
                 ("Monti 2", "1FAIpQLSdSqRdr-0v9WW5gWWejsCZFxMOqYkXRT9y0DEPtf3SVEOu-wg")])]
HOWTO = [("Adding rulers to production layouts (video)", "https://drive.google.com/file/d/18nTAKfS0UAOib3LFcRCwGF0iYvIpcEbu/view"),
         ("Measuring rulers for media compensation", "https://drive.google.com/file/d/1Zj9yQZ6g7pePLVw9p-yqfSZ2BA7lrq4j/view")]
CHART = "https://docs.google.com/spreadsheets/d/1aDQB2beKf9QzEFTg5a5GW8GYenJlnaNVFRWdCIQcNjs/edit"
PAGE = "https://equipflow-lemon.vercel.app/rulers/"


def message(today):
    due = today + dt.timedelta(days=7)
    if due.isoformat() not in S["monthly"]:
        return None
    qtr = due.isoformat() in S["quarterly"]
    d = due.strftime("%A, %b %-d")
    tags = " ".join(f"<users/{u}>" for u in LEADS.values())
    lines = [f"*Ruler verification due next week: {d}* {tags}", "",
             f"*Monthly:* {', '.join(MONTHLY)}"]
    if qtr:
        lines.append(f"*Quarterly (also due this time):* {', '.join(QUARTERLY)}")
    lines += ["", "Print the rulers with production work this week, get them back from cutting and finishing, "
              f"and upload by {d}. Uploads in the week before count.", "",
              "*Upload forms*"]
    for loc, fs in FORMS:
        lines.append(f"• {loc}: " + " · ".join(f"<{F.format(i)}|{n}>" for n, i in fs))
    lines += ["", "*How-to:* " + " · ".join(f"<{u}|{t}>" for t, u in HOWTO),
              f"*Status:* <{PAGE}|Rulers page> · <{CHART}|Frequency chart>"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    day = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else dt.datetime.now(ZoneInfo("America/Los_Angeles")).date()
    m = message(day)
    if m:
        sys.stdout.write(m)
