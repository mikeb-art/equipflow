# Printer Maintenance daily refresh

Runs every morning at 7:00 AM Pacific as a Claude scheduled task through Mike's Chrome
(the Durst Analytics+ server, 50.232.157.54:8090, only answers from his network).

1. In Chrome, open `http://50.232.157.54:8090/ui/` (must already be signed in).
2. Run `pull.js` in that tab. It returns `{ok, len, hash}` and shows the pull as the page text.
3. Read the page text, save it as `dump.txt`, and check its length and hash match
   (hash: `h = (h*31 + charCode) % 2147483647` over the whole text).
4. Read the Machine Maintenance Log (`Log!A1:H` of sheet 1XSwBK8CyWAdOgR6cj9k-lF3pkBuDaeZTYwhDX2TeBBo)
   and save it as `log.json` (`{"values": [...]}`).
5. `python3 printer-maintenance/tools/build.py dump.txt log.json --reminder reminder.txt`
   rewrites the data in `printer-maintenance/index.html` and drafts the Printing-space reminder.
6. Commit and push to `main`; Vercel publishes it.
