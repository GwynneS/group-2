"""Buddy app server: the website, and the hub the browser extension talks to.

Serves the UI, shares the browser extension's files with it, packages the
extension as a download, runs the companion brain (screen_behavior) with
optional webcam body tracking (BodyTracking), and answers chat messages.

    python3 UI/server.py            # then open http://127.0.0.1:8765
    python3 UI/server.py --camera --open

Routes
    GET  /                              UI/index.html (and other files in UI/)
    GET  /extension/<file>              files from browser_extension/ (characters.js, art/...)
    GET  /download/buddy-extension.zip  the extension, zipped fresh on each request
<<<<<<< HEAD
    GET  /api/status                    what's running: AI, brain awareness source, camera
    GET  /api/state                     live companion state (see companion.py)
    POST /api/presence                  {"title", "host"} of the focused tab -> state
    POST /api/interact                  {"action": pet|poke|chat|copy_paste|feed, "food"?} -> result + state
    POST /api/camera                    {"on": bool} -> start/stop body tracking
    GET  /api/camera.mjpg               live webcam feed with the tracked skeleton
=======
    GET  /api/status                    {"ai", "brain": "running" | "offline", "extension_version"}
    GET  /api/state                     the companion brain's presented state (see
                                        screen_behavior/integration/presenter.py)
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff
    POST /api/chat                      {"message", "character", "history"} -> {"reply", "source"}
    POST /api/feed                      give buddy a fish -> {"accepted", "reason"}
    POST /api/interact                  {"type": "pet" | "chat"} -> {"ok"}
    POST /api/browser-activity          extension heartbeat (counts only) -> {"ok"}

The companion brain (screen_behavior/) runs inside this server, so the UI,
the extension and the brain share one process and one port. Start with
--no-brain to serve the UI without it.

Chat uses Claude when the `anthropic` package is installed and credentials are
available (ANTHROPIC_API_KEY or an `ant auth login` profile). Otherwise the
buddy answers with short built-in replies so the app still works offline.

Only binds to 127.0.0.1; the extension is allowed to call this port.
"""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import random
import re
import sys
<<<<<<< HEAD
import webbrowser
=======
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff
import zipfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765  # keep in sync with APP_ORIGINS in browser_extension/background.js

UI_DIR = Path(__file__).resolve().parent
ROOT_DIR = UI_DIR.parent
EXT_DIR = ROOT_DIR / "browser_extension"

# Let `python3 UI/server.py` import screen_behavior from the repo root.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

MODEL = "claude-opus-5"
MAX_MESSAGE_CHARS = 2000
MAX_HISTORY = 20

CHARACTERS = {
    "girl": {
        "name": "Mochi",
        "voice": "a cheerful, bubbly cat girl who sometimes adds a soft 'nya~'",
    },
    "boy": {
        "name": "Kiko",
        "voice": "a laid-back, slightly shy cat boy who is quietly encouraging",
    },
}


# --- Chat ----------------------------------------------------------------------

def system_prompt(character: str, mood: str = "") -> str:
    c = CHARACTERS.get(character, CHARACTERS["girl"])
    return mood + (
        f"You are {c['name']}, {c['voice']}. You are a pixel-art desktop buddy who "
        "lives in the user's browser and keeps them company while they work or study. "
        "Your job is to encourage the user, celebrate progress, suggest short breaks "
        "when they sound tired, and help with quick questions. "
        "Reply in one to three short sentences, casual and warm, in character. "
        "Keep things friendly and wholesome. No markdown, no lists."
    )


def mood_context(state: dict | None) -> str:
    """How the buddy is feeling right now, from the companion brain."""
    if not state:
        return ""
    pet = state["pet"]
    return (
        f"Right now you feel {pet['mood']} and are {state['message'].lower().rstrip('.!~')}. "
        f"Hunger {pet['hunger']}/100, energy {pet['energy']}/100. "
        f"The user seems to be {state['activity']['type']}. "
        "Let this color your reply naturally; don't list these numbers. "
    )


def to_claude_messages(history: list[dict], message: str) -> list[dict]:
    """Convert stored chat history ({role: user|buddy, text}) to API messages."""
    messages = []
    for item in history[-MAX_HISTORY:]:
        if item.get("error") or not isinstance(item.get("text"), str):
            continue
        role = "assistant" if item.get("role") == "buddy" else "user"
        messages.append({"role": role, "content": item["text"][:MAX_MESSAGE_CHARS]})
    # The conversation has to open with a user turn.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    messages.append({"role": "user", "content": message})
    return messages


class ClaudeChat:
    """Claude-backed replies. `available` is False when the SDK or credentials are missing."""

    def __init__(self) -> None:
        self.client = None
        try:
            import anthropic  # optional dependency

            self.anthropic = anthropic
            self.client = anthropic.Anthropic()
        except Exception as exc:  # not installed, or no credentials configured
            print(f"[chat] Claude unavailable, using built-in replies ({exc.__class__.__name__})")

    @property
    def available(self) -> bool:
        return self.client is not None

    def reply(self, character: str, history: list[dict], message: str, mood: str = "") -> str | None:
        anthropic = self.anthropic
        try:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system_prompt(character, mood),
                messages=to_claude_messages(history, message),
            )
        except anthropic.AuthenticationError:
            print("[chat] Claude rejected the credentials; using built-in replies")
            self.client = None
            return None
        except anthropic.RateLimitError:
            print("[chat] Claude rate limit hit; using a built-in reply")
            return None
        except anthropic.APIStatusError as exc:
            print(f"[chat] Claude API error {exc.status_code}: {exc.message}")
            return None
        except anthropic.APIConnectionError:
            print("[chat] Could not reach the Claude API; using a built-in reply")
            return None

        if response.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None


OFFLINE_REPLIES = {
    "girl": {
        "greet": ["Hi hi! Mochi's here~ What are we working on?", "Hello! Ready when you are, nya~"],
        "tired": ["You've been working hard! A five-minute stretch break? I'll wait right here~"],
        "stuck": ["Tricky one? Try writing down the very next tiny step. You've got this!"],
        "done": ["Yay, you did it! That deserves a little celebration~", "Finished?! Mochi is so proud!"],
        "thanks": ["Anytime! That's what buddies are for~"],
        "default": ["I'm cheering for you!", "Mhm, mhm! Keep going, you're doing great~", "Nya~ tell me more!"],
    },
    "boy": {
        "greet": ["Hey. Kiko here. What's the plan?", "Oh, hey! Ready to get stuff done?"],
        "tired": ["Sounds like break time. Stand up, stretch, grab some water. I'll hold your spot."],
        "stuck": ["Stuck happens. Break it into the smallest next step and just do that one."],
        "done": ["Nice. Seriously, good work.", "Done already? ...Not bad at all."],
        "thanks": ["Yeah, of course. Anytime."],
        "default": ["Mrrp. I'm listening.", "You're doing fine. Keep at it.", "Solid. What's next?"],
    },
}

OFFLINE_PATTERNS = [
    ("greet", r"\b(hi|hello|hey|yo|morning|evening)\b"),
    ("tired", r"\b(tired|sleepy|exhausted|break|burn(ed|t)? out)\b"),
    ("stuck", r"\b(stuck|help|confused|hard|can't|cant|error|bug)\b"),
    ("done", r"\b(done|finished|shipped|passed|submitted|did it)\b"),
    ("thanks", r"\b(thanks|thank you|ty|thx)\b"),
]


def offline_reply(character: str, message: str) -> str:
    lines = OFFLINE_REPLIES.get(character, OFFLINE_REPLIES["girl"])
    lowered = message.lower()
    for key, pattern in OFFLINE_PATTERNS:
        if re.search(pattern, lowered):
            return random.choice(lines[key])
    return random.choice(lines["default"])


claude = ClaudeChat()


# --- Extension packaging -------------------------------------------------------

def extension_version() -> str:
    try:
        return json.loads((EXT_DIR / "manifest.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return "unknown"


def build_extension_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(EXT_DIR.rglob("*")):
            rel = path.relative_to(EXT_DIR)
            if path.is_file() and not any(part.startswith(".") for part in rel.parts):
                zf.write(path, Path("buddy-extension") / rel)
    return buf.getvalue()


# --- HTTP ----------------------------------------------------------------------

companion = None  # CompanionService, created in main()


def safe_path(root: Path, rel: str) -> Path | None:
    """Resolve `rel` inside `root`, refusing anything that escapes it."""
    target = (root / rel.lstrip("/")).resolve()
    if target == root or root in target.parents:
        return target if target.is_file() else None
    return None


# --- Companion brain -----------------------------------------------------------

def start_brain(enable_microphone: bool = False):
    """Start the companion brain, or return None if it can't run here."""
    try:
        from screen_behavior.integration.brain import CompanionBrain
        from screen_behavior.integration.runtime import BuddyRuntime

        return BuddyRuntime(
            lambda: CompanionBrain(enable_microphone=enable_microphone)
        ).start()
    except Exception as exc:  # unsupported OS, missing deps, permissions
        print(f"[brain] not running ({exc.__class__.__name__}: {exc})")
        return None


def offline_brain_state(message: str = "Brain offline") -> dict:
    try:
        from screen_behavior.integration.presenter import offline_state
        return offline_state(message)
    except Exception:
        return {"brain": "offline", "animation": "lounging", "message": message}


class Handler(SimpleHTTPRequestHandler):
    server_version = "BuddyApp/1.0"

    # Set by make_server(). `state_provider` overrides the runtime's state
    # (used by animation_bridge.AnimationBridge for manual animations).
    runtime = None
    state_provider = None

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/api/status":
            return self.send_json({
                "ai": "claude" if claude.available else "offline",
                "brain": "running" if self.runtime or self.state_provider else "offline",
                "extension_version": extension_version(),
                "brain": companion.awareness_source if companion else "off",
                "camera": companion.camera.status if companion else "unavailable",
            })

        if path == "/api/state":
<<<<<<< HEAD
            if companion is None:
                return self.send_error(HTTPStatus.NOT_FOUND)
            return self.send_json(companion.state())

        if path == "/api/camera.mjpg":
            return self.stream_camera()
=======
            if self.state_provider is not None:
                return self.send_json(self.state_provider())
            if self.runtime is not None:
                return self.send_json(self.runtime.state())
            return self.send_json(offline_brain_state())
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff

        if path == "/download/buddy-extension.zip":
            data = build_extension_zip()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="buddy-extension.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path.startswith("/extension/"):
            return self.send_file(safe_path(EXT_DIR, path[len("/extension/"):]))

        if path == "/":
            path = "/index.html"
        return self.send_file(safe_path(UI_DIR, path))

    def do_POST(self) -> None:
<<<<<<< HEAD
=======
        path = self.path.split("?", 1)[0]
        if path not in {"/api/chat", "/api/feed", "/api/interact", "/api/browser-activity"}:
            return self.send_error(HTTPStatus.NOT_FOUND)
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(length, 200_000)) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send_json({"error": "Request body must be a JSON object."}, HTTPStatus.BAD_REQUEST)

<<<<<<< HEAD
        if self.path == "/api/chat":
            return self.chat(body)
        if companion is None:
            return self.send_error(HTTPStatus.NOT_FOUND)

        if self.path == "/api/presence":
            companion.report_browser(str(body.get("title", ""))[:200], str(body.get("host", ""))[:100])
            return self.send_json(companion.state())

        if self.path == "/api/interact":
            result = companion.interact(str(body.get("action", "")), str(body.get("food", "dry")))
            status = HTTPStatus.OK if result["accepted"] or body.get("action") == "feed" else HTTPStatus.BAD_REQUEST
            return self.send_json({**result, "state": companion.state()}, status)

        if self.path == "/api/camera":
            if body.get("on"):
                if not companion.camera.available():
                    return self.send_json({
                        "error": "Body tracking needs OpenCV and MediaPipe: pip install -r requirements.txt",
                    }, HTTPStatus.CONFLICT)
                companion.camera.start()
            else:
                companion.camera.stop()
            return self.send_json(companion.state())

        return self.send_error(HTTPStatus.NOT_FOUND)

    def chat(self, body: dict) -> None:
=======
        if path != "/api/chat":
            return self.brain_post(path, body)

>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff
        message = str(body.get("message", "")).strip()[:MAX_MESSAGE_CHARS]
        character = body.get("character") if body.get("character") in CHARACTERS else "girl"
        history = body.get("history") if isinstance(body.get("history"), list) else []
        if not message:
            return self.send_json({"error": "Message is empty."}, HTTPStatus.BAD_REQUEST)

<<<<<<< HEAD
        mood = ""
        if companion is not None:
            companion.interact("chat")
            mood = mood_context(companion.state())
        reply = claude.reply(character, history, message, mood) if claude.available else None
=======
        if self.runtime is not None:
            self.runtime.interact("chat")

        reply = claude.reply(character, history, message) if claude.available else None
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff
        if reply:
            return self.send_json({"reply": reply, "source": "claude"})
        return self.send_json({"reply": offline_reply(character, message), "source": "offline"})

<<<<<<< HEAD
    def stream_camera(self) -> None:
        """Motion-JPEG stream of the webcam, for an <img> on the website."""
        if companion is None or companion.camera.status not in ("on", "starting"):
            return self.send_error(HTTPStatus.NOT_FOUND, "Camera is off")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        frame_id = 0
        try:
            while companion.camera.status in ("on", "starting"):
                frame_id, jpg = companion.camera.wait_frame(frame_id)
                if jpg is None:
                    continue
                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
                )
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page closed or the image was hidden
=======
    def brain_post(self, path: str, body: dict) -> None:
        if self.runtime is None:
            return self.send_json({"error": "Brain is not running."}, HTTPStatus.SERVICE_UNAVAILABLE)
        if path == "/api/feed":
            return self.send_json(self.runtime.feed())
        if path == "/api/interact":
            result = self.runtime.interact(str(body.get("type", "")))
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            return self.send_json(result, status)
        return self.send_json(self.runtime.browser_activity(body))
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff

    def send_file(self, file: Path | None) -> None:
        if file is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        data = file.read_bytes()
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    QUIET_PATHS = ("/api/status", "/api/state", "/api/browser-activity")

    def log_message(self, fmt: str, *args) -> None:
<<<<<<< HEAD
        # The website and extension poll these constantly; keep the log readable.
        if not self.path.startswith(("/api/status", "/api/state", "/api/presence", "/api/camera.mjpg")):
=======
        if not self.path.startswith(self.QUIET_PATHS):
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff
            super().log_message(fmt, *args)


def make_server(host: str = HOST, port: int = PORT, runtime=None, state_provider=None):
    """Build the app server. Pass port=0 for a free port (tests, bridges)."""
    handler = type(
        "BoundHandler",
        (Handler,),
        {"runtime": runtime, "state_provider": staticmethod(state_provider) if state_provider else None},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main() -> None:
<<<<<<< HEAD
    global companion
    parser = argparse.ArgumentParser(description="Run the Buddy website and companion hub.")
    parser.add_argument("--camera", action="store_true", help="start webcam body tracking right away")
    parser.add_argument("--open", action="store_true", help="open the website in your browser")
    parser.add_argument("--no-native-awareness", action="store_true",
                        help="don't watch other apps; use only the browser tab the extension reports")
    args = parser.parse_args()

    from companion import CompanionService

    companion = CompanionService(native_awareness=not args.no_native_awareness)
    companion.start()
    if args.camera:
        if companion.camera.available():
            companion.camera.start()
        else:
            print("[camera] Body tracking needs OpenCV and MediaPipe: pip install -r requirements.txt")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    url = f"http://{HOST}:{PORT}"
    sys.stdout.reconfigure(line_buffering=True)
    print(f"Buddy app running at {url}")
    print(f"  AI chat:      {'Claude' if claude.available else 'built-in replies'}")
    print(f"  Brain:        screen awareness from {'this computer' if companion.awareness_source == 'native' else 'the browser extension'}")
    print(f"  Body tracking: {companion.camera.status}")
    if args.open:
        webbrowser.open(url)
=======
    parser = argparse.ArgumentParser(description="Buddy app server")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-brain", action="store_true", help="serve the UI without the companion brain")
    parser.add_argument("--mic", action="store_true", help="enable loudness detection (yell to wake buddy)")
    args = parser.parse_args()

    runtime = None if args.no_brain else start_brain(enable_microphone=args.mic)
    server = make_server(HOST, args.port, runtime=runtime)
    print(
        f"Buddy app running at http://{HOST}:{args.port}  "
        f"(AI: {'Claude' if claude.available else 'built-in replies'}, "
        f"brain: {'running' if runtime else 'off'})"
    )
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        companion.close()
        server.server_close()
        if runtime is not None:
            runtime.stop()


if __name__ == "__main__":
    main()
