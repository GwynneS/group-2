# This project is based on the idea of a Fem Boy AI Buddy

# This AI will praise you and support you on your productive tasks

# Particular response on command V
# Particular response on command C
# You cant pet the cat girl or femboy and it boosts the "happiness" bar


## Running the Buddy app

```bash
python3 UI/server.py
```

Then open http://127.0.0.1:8765. From there you can:

- pick Mochi (cat girl) or Kiko (cat boy), and pet them
- chat with your buddy
- download the browser extension (**Download extension**, then follow the install steps)

Once the extension is installed, the app and the extension share one set of
settings and one chat history. Your buddy floats on every website you visit;
right-click it to chat, switch character, or hide it.

**AI replies:** chat uses Claude when the `anthropic` package is installed and
credentials are set (`pip install -r UI/requirements.txt`, then
`export ANTHROPIC_API_KEY=...`). Without them the buddy answers with short
built-in replies.

How the pieces connect:

| Piece | Folder | Role |
|---|---|---|
| App server | `UI/server.py` | Serves the UI, shares `browser_extension/sprites.js` with it, zips the extension for download, answers `/api/chat` |
| App page | `UI/index.html`, `UI/app.js` | Buddy, settings, chat, download |
| Bridge | `browser_extension/bridge.js` | Runs only on the app page; syncs settings, headpats and chat with the extension |
| On-page buddy | `browser_extension/buddy.js` | The floating buddy and its chat panel on every other website |
| Background | `browser_extension/background.js` | Stores data and sends chat to the app server |
