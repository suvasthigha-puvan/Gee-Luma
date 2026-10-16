# Black-box test of Gee-Luma with selenium-mcp

Instructions for a Claude Code session. Test the Gee-Luma web app as a **black box**:
use it only through the browser, the way a user would. Don't read the app's source code
to decide what should happen. Judge it by what the page shows and says.

## Setup (check before testing)

1. **selenium-mcp tools.** The project's `.mcp.json` registers the `selenium-mcp` server.
   Its tools (`connectToBrowser`, `navigate`, `click`, `sendKeys`, `takeScreenshot`, ...)
   must be in your tool list. If they aren't, stop and ask the user to reload the
   session and approve the server. Don't write your own MCP client.
2. **Chrome in debug mode on port 1997.** Check that `http://127.0.0.1:1997/json/version`
   responds. If it doesn't, start Chrome:
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=1997 --user-data-dir="C:\Users\Suva\Documents\selenium-mcp\temp" --no-first-run --no-default-browser-check
   ```
   Then call `connectToBrowser` with `debuggerAddress: "127.0.0.1:1997"`. Work in that
   window and don't close it (`closeBrowser`) at the end.
3. **The app on http://localhost:&lt;PORT&gt;** (`PORT` is set in the `.env` file). Check that
   `GET /api/meta` returns `"ready": true`.
   If nothing is listening, start it in the background from the repo root:
   `../../.venv/Scripts/python.exe server.py`. Don't restart a server that's already running.
4. Call `startConsoleCapture` and `startNetworkCapture` after the first `navigate`, so you
   can report JavaScript errors and failed API calls.

## How to work

- Find elements with `getPageElements` / `getPageElementsFiltered`, not by guessing selectors.
- Take a screenshot (`takeScreenshot` with `filePath`) at each main step, save it in the
  session's scratchpad, and open it with Read to check what the user actually sees.
- **Generating a map takes 1 to 5 minutes.** Wait with `waitForTextPresent` /
  `waitForVisible` (long timeouts, done in several rounds) instead of fixed sleeps.
  Keep the number of maps small: each run uses the real OpenAI API and Earth Engine.
- After each area, check `getConsoleLogs` (type `error`) and `getNetworkLog` for 4xx/5xx.

## What to test (overall pass)

1. **Home page loads.** Title, logo, prompt box, example requests and options are all
   shown, with no console errors. Try a narrow width with `setWindowSize` (about 500 px)
   and check that the layout still works.
2. **Input checks.** Submitting an empty prompt, and then a nonsense prompt (e.g. "asdf"),
   should give a clear message, not a crash or a spinner that never stops.
3. **Main flow, one map.** Use one of the example requests, or "NDVI of Sri Lanka in
   2023". Check that progress steps appear and update. If the app asks you to choose a
   dataset, choose one and continue. The finished map must show a title, legend, scale
   bar and region.
4. **Downloads.** Each download link offered (PNG, PDF, CSV statistics, GeoTIFF) should
   work: check the link responds with status 200 using the network log or `httpGet`.
5. **Other controls.** Palette choice, theme (light/dark), the original (not gap-filled)
   map if offered, and the list of recent maps (opening an earlier result again).
6. **Deep links.** Copy a finished map's link (`?map=<id>`) into a fresh `navigate` and
   check it opens the same map. Try `?theme=dark`, and `?map=does-not-exist`, which should
   show an error message, not a blank page.
7. **Region upload.** If there is a GeoJSON upload, try a small valid polygon and an
   invalid file (e.g. a .txt), using `uploadFile`. Make the test files in the scratchpad.
8. **Time series (optional, slow).** One request spanning several periods (e.g. "monthly
   rainfall of Kenya in 2022") to check the multi-map figure.

## Report

Write a short report: what passed, then each problem found, with its steps to reproduce,
expected vs. actual result, a screenshot path, and severity (blocker / major / minor /
cosmetic). Put any console or network errors with the problem they belong to. Don't
change the app's code during this test; only report.
