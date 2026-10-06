"""Download the Machine Maintenance Log (Log!A1:H) as Sheets values JSON for build.py.

usage: fetch_log.py OUT.json

Reads the service-account key JSON from the GOOGLE_SA_KEY environment variable (the repo secret of the same
name, set in Settings > Secrets and variables > Actions). The service account needs Viewer access to the sheet.
"""
import json
import os
import sys

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

SHEET = "1XSwBK8CyWAdOgR6cj9k-lF3pkBuDaeZTYwhDX2TeBBo"
RANGE = "Log!A1:H"


def main():
    key = os.environ.get("GOOGLE_SA_KEY", "").strip()
    if not key:
        sys.exit("GOOGLE_SA_KEY secret is not set")
    # Tolerate common paste slips: a missing first "{" or last "}", and TextEdit's curly quotes.
    key = key.replace("\u201c", '"').replace("\u201d", '"')
    if not key.startswith("{"):
        key = "{" + key
    if not key.endswith("}"):
        key = key + "}"
    try:
        info = json.loads(key)
    except ValueError as e:
        sys.exit(f"GOOGLE_SA_KEY is not valid JSON ({e.msg} at character {e.pos} of {len(key)}). "
                 "Paste the whole downloaded .json key file, from the first {{ to the last }}.")
    if info.get("type") != "service_account" or "private_key" not in info:
        sys.exit(f"GOOGLE_SA_KEY is JSON but not a service-account key (fields: {sorted(info)[:8]})")
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    r = AuthorizedSession(creds).get(f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET}/values/{RANGE}",
                                     timeout=60)
    if r.status_code != 200:
        sys.exit(f"Sheets API HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    rows = j.get("values", [])
    if len(rows) < 2 or rows[0][:1] != ["Timestamp"]:
        sys.exit(f"Unexpected Log contents ({len(rows)} rows, header {rows[:1]})")
    json.dump(j, open(sys.argv[1], "w"))
    print(f"log: {len(rows) - 1} rows")


if __name__ == "__main__":
    main()
