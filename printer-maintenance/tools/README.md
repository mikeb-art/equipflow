# Printer Maintenance daily refresh

Runs every morning at 7:00 AM Pacific as a Claude scheduled task through Mike's Chrome
(the Durst Analytics+ server, 50.232.157.54:8090, only answers from his network).

1. Mike's Chrome (Mac Studio, the profile signed in to Durst) has the Tampermonkey script `tools/durst-pull.user.js`
   installed. It is built from `pull.js` by `tools/make_userscript.py` (rerun after changing `pull.js`) and only
   acts when the Durst page is opened with `?pull=N`.
2. Open `http://50.232.157.54:8090/ui/?pull=3#/lfa/printers/printer-list` (`?pull=90` on Mondays for a full refresh).
   The script pulls that many days and replaces the page with `PULL ok len=… hash=… printers=…`, a `---` line, and the
   dump (or `PULL FAILED: …`).
   Auto sign-in: when the Durst session has expired, the script signs in again by itself (`POST /frontend-api/login`)
   with a sign-in saved in Tampermonkey's own storage on the Mac Studio (never in the repo). To save or change it, open
   `http://50.232.157.54:8090/ui/?pullsetup=1` in that Chrome profile (or Tampermonkey menu > "Durst sign-in for the daily
   pull…"), enter it and press "Test and save". `PULL FAILED: Durst auto sign-in …` means the saved sign-in is missing
   or no longer works. The script also remembers `?pull=N` for 10 minutes in the tab, because the Durst app can reload
   itself and drop it from the address.
3. Read the page text, save everything after the `---` line as `printer-maintenance/data/pull.txt` (no trailing
   newline), and check its length and hash match (hash: `h = (h*31 + charCode) % 2147483647` over the whole text).
4. Commit and push only `pull.txt` to `main`. The Claude run never reads the Maintenance Log itself: the log is
   ~900 KB, too big to pass through a connector reliably.
5. The push starts the GitHub Action `.github/workflows/printer-maintenance-build.yml`, which
   - reads the Machine Maintenance Log (`Log!A1:H` of sheet 1XSwBK8CyWAdOgR6cj9k-lF3pkBuDaeZTYwhDX2TeBBo) with
     `tools/fetch_log.py`, using the service-account key in the repo secret `GOOGLE_SA_KEY` (that account needs
     Viewer access to the sheet),
   - runs `tools/build.py pull.txt log.json`, which merges the pull into `data/history.txt` (rolling 91 days; the
     pulled days replace what was stored), rewrites the data in `index.html`, and writes `data/reminder.txt`,
   - adds the "Other maintenance" status (Monti, Vutek, Klieverik sign-offs, `tools/other_maintenance.py`): machine
     and task lists come from `maintenance/index.html` (read with node), status as of the post's morning goes to
     `data/other.json`, the chart to `data/other-chart.png`, and the Chat card to `data/card.json`. Tasks never signed
     off in the log are listed separately and left out of the percentage,
   - commits those files to `main` (Vercel publishes the page and the chart), and
   - posts `card.json` to the Google Chat "Printing" space (webhook: repo secret `PRINTING_CHAT_WEBHOOK`) once the
     chart is live on the site (up to 4 minutes; without the chart if it isn't). If the card post fails it posts
     `reminder.txt` as plain text instead.
   - Card buttons open `/maintenance/#CA` (etc.) and `/printer-maintenance/#CA`; both pages read that location tag.
6. To rebuild or re-send by hand: Actions tab > Printer maintenance build > Run workflow (untick "Post" to rebuild
   without posting). `printing-reminder.yml` can still post a test message or re-send the stored reminder.

To build locally: `python3 printer-maintenance/tools/build.py printer-maintenance/data/pull.txt log.json`, where
`log.json` is `{"values": [...]}` of the Log tab (a Drive CSV export also works).

## P5 "done" messages

P5 printers send the same text ("Maintenance warning: X") for the on-screen prompt and for the operator tapping Execute. The Execute message has a zero-padded second ID in `errorNr` (e.g. `50001|00000000000003089282`). `pull.js` records those as done. Confirmed Oct 1, 2026 with Execute taps on the CA P5-350.
