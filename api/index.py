"""Vercel entrypoint: the Buddy website and its API as one Python function.

vercel.json sends every request here, and UI/server.py's Handler answers it
exactly as `python3 UI/server.py` does locally. On a server there's no desktop
to watch, so the companion brain uses only the browser tab the extension
reports; the microphone and desktop window stay off. There's no webcam here
either: the website tracks the visitor's own (UI/body.js) and sends the
results to POST /api/body.

The pet's state and the chat notes live in this function instance's memory:
every visitor shares one buddy, and a fresh instance starts over.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "UI"))

import server  # noqa: E402
from companion import CompanionService  # noqa: E402

server.companion = CompanionService(native_awareness=False)
server.companion.start()


class handler(server.Handler):
    """The name Vercel's Python runtime looks for."""
