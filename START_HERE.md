# Start Buddy in your browser — repaired version 0.5.3

Use this complete copy for a first run. If your team has made newer changes,
read **REPAIR_REPORT.md** before merging; a clean patch against this ZIP's
source does not guarantee a conflict-free merge into another branch.

## 1. Test the website first

1. Stop any older Buddy terminal with **Ctrl+C**.
2. Right-click the downloaded ZIP and choose **Extract All**. Open its
   **group-2** folder. Do not run the app from inside the ZIP.
3. Double-click **START_BUDDY.bat**. Keep its terminal window open.
4. Your browser should open **http://127.0.0.1:8765**. If it does not, enter
   that address yourself.
5. Choose a character. Try petting, feeding and chat. Turn on voice if you
   want to check the existing audio clips; interact with the page first if
   the browser blocks automatic sound.

The basic website needs **Python 3.11 or newer**. The automated tests for this
repair used **Python 3.12.14**. If the launcher says Python is missing, install
Python for Windows, reopen the folder, and try again. No Node.js, webcam,
paid AI account or optional Python packages are needed for this first test.
Chat uses built-in replies when Claude is unavailable.

You can also open a terminal inside **group-2** and run:

```powershell
py -3 start_buddy.py
```

The launcher prints the Python executable it uses. It prefers a project
`.venv` when present; otherwise it tries the Windows `py` command, then
`python`. Stop Buddy with **Ctrl+C** in that terminal.

## 2. Test the extension second

1. Keep the Python app running.
2. In desktop Chrome open **chrome://extensions**. In Edge use
   **edge://extensions**.
3. Disable old copies of **Buddy Activity Tracker**, so two versions do not
   run together.
4. Turn on **Developer mode**, then choose **Load unpacked**.
5. Select **group-2/browser_extension**, the folder containing
   **manifest.json**. Do not select the whole project or the ZIP.
6. Confirm version **0.5.3**. Grant the extension access to the sites where
   you want it to run, if the browser asks.
7. Refresh the Buddy website and your test webpage. Choose a character from
   the extension's toolbar icon and enable showing it on websites.
8. Check the floating character on an ordinary webpage. Try a headpat or
   feeding, then make sure the website reflects the shared pet state.

Browser settings pages, extension stores and some protected pages do not
allow content scripts. The Buddy website draws its own character and does
not add a second floating one. If you use the website's **Download extension**
button, extract that download and load its **buddy-extension** folder instead.

**A working website does not prove the extension is installed correctly.**
Confirm the floating character appears, check the extension's **Errors**
panel, and verify that interaction reaches the running app.

### Check the faster shortcut voices

1. Enable **Voice** in the extension's toolbar popup and choose a character.
2. On an ordinary webpage, select a little text and press **Ctrl+C**. Paste
   into a text box with **Ctrl+V**, then press **Ctrl+Z** to undo.
3. Each different shortcut should request its voice immediately, without
   waiting for the five-second activity report. Repeating the same shortcut
   within one second is ignored for speech; it is not queued for later.
4. Try with two tabs open. One shortcut should not produce duplicate voices.
5. Close the Buddy website tab and try again on the ordinary webpage. Keep
   the Python terminal running. Voice can be muted from the extension popup.

Ctrl/Command+C/V/Z are recognized without reading copied text or recording
what you type. The original clips contain roughly 0.2–0.6 seconds of leading
silence; those recordings are unchanged. Actual sound and end-to-end timing
still need checking on your computer.

### Check inactivity without the camera

Open **http://127.0.0.1:8765/api/state** in another tab. This is a read-only
diagnostic page. Under `activity`, look for `idle_seconds`, `user_state`,
`user_present`, and `away_inferred`. The response also contains `behavior`,
`onpage_mode`, `decision_age_ms`, and `distraction_budget`.

- Type or move the pointer on a permitted ordinary webpage. After the next
  report and brain tick, normally about 5–6 seconds, `idle_seconds` should
  drop. Then stop touching the keyboard and mouse: it should increase again.
- A page staying open, a title change, and automatic polling must not keep
  resetting that number.
- Switching tabs alone must not trigger a camera-style "welcome back".
- With no camera evidence, `user_present` is `null` (unknown). The existing
  policy still estimates IDLE after about 60 seconds plus state smoothing,
  and AWAY after 300 seconds without observed input. `away_inferred: true`
  identifies that estimate. It does not prove someone left the desk.

Manually clicking refresh is itself user input on extension-enabled pages.
For a continuous hands-off check, a technical teammate can run this in a
second PowerShell window after moving the pointer away from the test page:

```powershell
while ($true) {
    $buddyState = Invoke-RestMethod http://127.0.0.1:8765/api/state
    $buddyState.activity | ConvertTo-Json -Compress
    Start-Sleep -Seconds 2
}
```

This command only reads state. Press **Ctrl+C** in that second window to stop
watching; keep the original Buddy terminal running.

## 3. Test the camera last

Get the first two stages working before adding camera dependencies.

Without the camera packages (and on the Vercel site), **Start camera** uses
the webcam in your browser instead: the page tracks you itself, and only
whether you're at your desk reaches the server, never video. It needs the page
open at `http://127.0.0.1:8765` or over `https://`, and tracking slows down
while the tab is in the background. Moving the webcam isn't detected in this
mode.

For tracking that keeps running with the website closed, stop Buddy and run the existing
project requirements from inside **group-2**, using the same Python:

```powershell
py -3 -m pip install -r requirements.txt
```

If the launcher printed a path inside `.venv`, use this instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Restart Buddy. Enable the camera using the website's camera control. If it
cannot open, check Windows camera privacy settings and close other apps using
the device. The existing tracker may download its pose model on first use,
so first-time setup can need internet access. No AI-chat key is needed.

Use **Hide preview** to remove the live video while keeping camera tracking
on. **Show preview** brings it back; your choice is remembered. The small
**Camera tracking on** status remains visible. **Stop camera** is a separate
button and actually stops tracking.

After starting the camera, you can switch tabs or close the Buddy **website
tab** and use the extension on normal webpages. You can also hide the floating
character using its existing visibility control; activity and voice reporting
continue on a focused permitted webpage. Keep the Python terminal running
(minimizing it is fine). Closing the separate native desktop-app window may
stop its server, so use **START_BUDDY.bat** for this browser workflow.

| Camera check | Expected result in `/api/state` |
|---|---|
| Sit in view, then stop typing/moving the mouse | `user_present: true`; input inactivity continues increasing. After about a minute, IDLE is allowed. Presence prevents the five-minute inferred AWAY. |
| Leave the camera's view | Once the tracker confirms absence, `user_present: false`, `user_state: "away"`, and `away_inferred: false`. The existing tracker normally debounces loss for about three seconds. |
| Return to view | `user_present: true`, and the state leaves AWAY. You can still be IDLE until actual input occurs. Existing return/inactive voice reactions remain available. |
| Turn the camera off | `user_present: null`, `body: null`. Input-based classification continues. |
| Move/adjust the camera | Presence is unknown during detected movement. Wait for the tracker to settle. |
| Camera fails or stops producing snapshots | Presence becomes unknown. Data older than five seconds is rejected, with the normal one-second brain tick delay. |

If you remain inactive for five minutes after turning the camera off,
`user_state` can still say AWAY, but it must be marked **inferred** and
`user_present` must be `null`.

## If something does not work

| Symptom | First check |
|---|---|
| Python was not found | Install Python 3.11+ and reopen the launcher. |
| Port 8765 is already in use | Close the previous Buddy terminal with Ctrl+C, then start this copy. Keep port 8765: the extension expects it. |
| Website will not open | Leave the terminal open, read its error, and check the address includes `:8765`. |
| Website works but no floating buddy | Check extension version 0.5.3, select a character, enable site access, and refresh an ordinary webpage. |
| Old JavaScript syntax error remains | Disable the old extension and load this copy's folder. Refresh all test tabs. |
| Camera packages fail to install | Save the first installation error and the Python path printed by the launcher. Continue testing with the camera off. |
| Voice is quiet | Check the extension popup's Voice switch, selected character, app terminal, browser sound permissions and volume. Reload the updated extension and test an ordinary webpage. Audio playback was not tested on hardware here. |

The launcher uses **browser-only awareness**. It cannot observe typing in
other desktop apps or protected browser pages, so those can eventually look
idle/away. For the existing native desktop-awareness option, install the
project requirements and run:

```powershell
py -3 UI/server.py --open
```

The original desktop window is also preserved: `py -3 UI/server.py` uses
pywebview when available. On macOS the project additionally has
`screen_behavior/requirements-macos.txt`. These optional platform paths need
testing on your computer.

## Automated checks for a technical teammate

Run from **group-2**:

```powershell
py -3 -m unittest discover -s UI/tests
py -3 -m screen_behavior.run_tests
py -3 build_extension.py chromium firefox
node --check browser_extension/buddy.js
```

The test suites check every extension/UI JavaScript file when Node.js is
installed. Without Node those JavaScript checks are skipped. Node is needed
only for testing, not for normal operation. If using `.venv`, replace `py -3`
with `.\.venv\Scripts\python.exe`.

Validation here used Linux: **244 tests passed, one macOS hardware test was
skipped**. Browser/DOM APIs and camera input were simulated. A standalone
Python server and its actual HTTP routes were also exercised. The extension
has **not** been installed in a real browser during this repair; physical
webcam behavior, Windows batch execution, audio playback and native desktop
permissions still require the staged checks above.

Chrome/Edge are the first test targets. Background audio adds the extension's
`offscreen` permission. For Firefox, use the separately generated Firefox
package in `dist` after running the build command above; its manifest omits
that Chrome-only permission. Firefox audio was checked with mocked APIs only.
Safari background voice is not supported by this repair; the website keeps
its own audio fallback where background audio is unavailable.

Automatic voice checks use the focused permitted webpage. Protected pages,
no open permitted tabs, a suspended tab, or a minimized browser can delay or
prevent browser reporting/audio. Python camera tracking continues until you
stop the camera or the server.
