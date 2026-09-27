"""Buddy app server: the website, and the hub the browser extension talks to.

Serves the UI, shares the browser extension's files with it, packages the
extension as a download, runs the companion brain (screen_behavior) with
optional webcam body tracking (BodyTracking), and answers chat messages.

    python3 UI/server.py            # the app in a desktop window (pywebview)
    python3 UI/server.py --open     # the app in your browser instead
    python3 UI/server.py --no-window --camera

The desktop window shows the same page the server serves at
http://127.0.0.1:8765. The server keeps running either way, because the
browser extension talks to it. Without pywebview the app opens nothing and
prints the URL instead.

Routes
    GET  /                              UI/index.html (and other files in UI/)
    GET  /extension/<file>              files from browser_extension/ (characters.js, art/...)
    GET  /download/buddy-extension.zip  the extension, zipped fresh on each request and
                                        set to talk to the site it's downloaded from
    GET  /voice/<file>                  voice clips from HackMp3s/
    GET  /api/voices                    {trigger: {"girl": [{"url", "text"}...], "boy": [...]}}
    GET  /api/status                    what's running: AI, brain awareness source, camera,
                                        key tracking, and whether the extension has checked in
    GET  /api/state                     live companion state (see companion.py)
    POST /api/presence                  tab metadata -> state; only explicit input:true marks input
    POST /api/shortcut                  {"shortcut": "copy"|"paste"|"undo"} -> immediate reaction
    POST /api/voice/claim               one playback owner per live voice event
    POST /api/interact                  {"action": pet|poke|chat|copy_paste|feed, "food"?} -> result + state
    POST /api/camera                    {"on": bool} -> start/stop body tracking
    POST /api/body                      the website's own camera tracking (UI/body.js), when
                                        this computer has none: {"state", "present", "event",
                                        "away_seconds", "hand_raised", "leaning_in"} or
                                        {"camera": "off"} -> state (409 while /api/camera is on)
    POST /api/browser-activity          extension heartbeat every 5s: counts only (clicks,
                                        keys, copies, pastes, scroll, active time) + tab
                                        title/host -> {"ok"}
    GET  /api/camera.mjpg               live webcam feed with the tracked skeleton
    POST /api/chat                      {"message", "character", "history"}
                                        -> {"reply", "source", "thought"?, "learned"?}
    POST /api/chat/stream               same request; streams newline-delimited JSON events
                                        while Claude thinks and writes (see ClaudeChat.reply)
    GET  /api/memory                    {"notes": [{"id", "kind", "text", "at"}], "ai"}
    POST /api/memory/forget             {"id"} -> {"notes"}
    POST /api/memory/clear              forget everything -> {"notes": []}

Chat uses Claude when the `anthropic` package is installed and credentials are
available (ANTHROPIC_API_KEY or an `ant auth login` profile). Otherwise the
buddy answers with short built-in replies so the app still works offline.
Claude keeps short notes about the user between chats (MemoryStore); the
website shows them and can delete any or all of them.

Only binds to 127.0.0.1; the extension is allowed to call this port.
"""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import random
import re
import secrets
import sys
import threading
import time
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 8765
# The extension's default Buddy app (browser_extension/config.js). Downloads
# from anywhere else get that address instead (build_extension_zip).
LOCAL_APP_URL = f"http://{HOST}:{PORT}"

UI_DIR = Path(__file__).resolve().parent
EXT_DIR = UI_DIR.parent / "browser_extension"
VOICE_DIR = UI_DIR.parent / "HackMp3s"
# What the buddy learned from chatting; git-ignored, it's about you.
MEMORY_FILE = UI_DIR.parent / "buddy_data" / "memory.json"

MODEL = "claude-opus-5"
MAX_MESSAGE_CHARS = 2000
MAX_HISTORY = 20
MAX_TOOL_ROUNDS = 4  # remember/forget calls per reply before Claude must answer
MAX_THOUGHT_CHARS = 2000
MEMORY_KINDS = ("about_you", "how_to_talk")
MAX_NOTES = 40
MAX_NOTE_CHARS = 200

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

def system_prompt(character: str, mood: str = "", notes: list[dict] | None = None) -> str:
    c = CHARACTERS.get(character, CHARACTERS["girl"])
    prompt = (
        f"You are {c['name']}, {c['voice']}. You are a pixel-art desktop buddy who "
        "lives in the user's browser and keeps them company while they work or study. "
        "Your job is to encourage the user, celebrate progress, suggest short breaks "
        "when they sound tired, and help with quick questions. "
        "Be a real conversation partner: pick up on what they said earlier, ask about "
        "things they mentioned, and follow up with a question when you're curious, "
        "though not every time. "
        "Reply in one to four short sentences, casual and warm, in character. "
        "Keep things friendly and wholesome. No markdown, no lists.\n\n"
        "You get better at talking with this user over time. When you learn something "
        "worth knowing next time (their name, what they're working on, goals, likes, "
        "what's stressing them), save it with the remember tool as an about_you note. "
        "Also notice how they like to be talked to (brief or chatty, jokes or straight "
        "answers, pep talks or practical tips) and save that as a how_to_talk note, "
        "then follow your how_to_talk notes. If a note turns out to be wrong or "
        "outdated, forget it and save the corrected one. Don't save passwords, secrets, "
        "or sensitive details like health or money unless they ask you to remember "
        "them. Keep notes short, and don't announce every one."
    )
    if notes:
        prompt += "\n\nYour notes from earlier chats:\n" + "\n".join(
            f"- [{n['id']}] ({n['kind']}) {n['text']}" for n in notes
        )
    else:
        prompt += "\n\nYou have no notes about this user yet."
    return prompt + ("\n\n" + mood if mood else "")


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


class MemoryStore:
    """Short notes Claude keeps about the user between chats, in a JSON file.

    about_you notes are facts (name, projects, likes); how_to_talk notes are
    how the user likes to be talked to. The oldest note goes once there are
    MAX_NOTES. Thread-safe: the server answers requests on several threads.
    """

    def __init__(self, path: Path = MEMORY_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._notes = self._load()

    def _load(self) -> list[dict]:
        try:
            notes = json.loads(self.path.read_text()).get("notes")
        except (OSError, ValueError, AttributeError):
            return []
        if not isinstance(notes, list):
            return []
        return [
            n for n in notes
            if isinstance(n, dict) and n.get("kind") in MEMORY_KINDS
            and isinstance(n.get("id"), str) and isinstance(n.get("text"), str)
        ][-MAX_NOTES:]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"notes": self._notes}, indent=2))
            tmp.replace(self.path)
        except OSError as exc:
            print(f"[chat] Couldn't save the buddy's memory to {self.path} ({exc})")

    def notes(self) -> list[dict]:
        with self._lock:
            return [dict(n) for n in self._notes]

    def remember(self, kind: str, text: str) -> dict:
        text = " ".join(text.split())[:MAX_NOTE_CHARS]
        if kind not in MEMORY_KINDS or not text:
            raise ValueError("A note needs a kind and some text.")
        with self._lock:
            for note in self._notes:
                if note["kind"] == kind and note["text"].lower() == text.lower():
                    return dict(note)
            note = {"id": secrets.token_hex(3), "kind": kind, "text": text, "at": time.time()}
            self._notes.append(note)
            del self._notes[:-MAX_NOTES]
            self._save()
            return dict(note)

    def forget(self, note_id: str) -> dict | None:
        with self._lock:
            for i, note in enumerate(self._notes):
                if note["id"] == note_id:
                    del self._notes[i]
                    self._save()
                    return dict(note)
        return None

    def clear(self) -> None:
        with self._lock:
            self._notes = []
            self._save()


MEMORY_TOOLS = [
    {
        "name": "remember",
        "description": (
            "Save a short note to use in future chats with this user. "
            "about_you: facts about them (name, projects, goals, likes). "
            "how_to_talk: how they like you to talk with them."
        ),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(MEMORY_KINDS)},
                "note": {"type": "string", "description": "One short sentence."},
            },
            "required": ["kind", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "forget",
        "description": "Delete one of your notes that is wrong or outdated, by its id.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


def run_memory_tool(block, emit) -> dict:
    """Carry out one remember/forget call; returns its tool_result block."""
    # Tool input streams as it's written, so the API doesn't validate it: check it here.
    args = block.input if isinstance(block.input, dict) else {}
    result = {"type": "tool_result", "tool_use_id": block.id}
    note_text = args.get("note")
    if block.name == "remember" and args.get("kind") in MEMORY_KINDS and isinstance(note_text, str) \
            and note_text.strip():
        note = memory.remember(args["kind"], note_text)
        emit({"type": "memory", "action": "remembered", "note": note})
        return {**result, "content": f"Saved as {note['id']}."}
    if block.name == "forget" and isinstance(args.get("id"), str):
        note = memory.forget(args["id"])
        if note:
            emit({"type": "memory", "action": "forgot", "note": note})
            return {**result, "content": "Forgotten."}
        return {**result, "content": "No note has that id.", "is_error": True}
    return {**result, "content": f"Invalid input for {block.name}: {json.dumps(args)}", "is_error": True}


def echo_blocks(content: list) -> list:
    """The assistant turn to send back with tool results. After a mid-reply
    fallback, the declined model's thinking and tool calls are left out."""
    switch = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    return [b for i, b in enumerate(content)
            if i > switch or b.type not in ("thinking", "redacted_thinking", "tool_use")]


def no_events(event: dict) -> None:
    pass


class ClaudeChat:
    """Claude-backed replies. `available` is False when the SDK or credentials are missing."""

    def __init__(self) -> None:
        self.client = None
        try:
            import anthropic  # optional dependency

            self.anthropic = anthropic
            client = anthropic.Anthropic()
            # Without an API key, auth token or `ant auth login` profile the
            # client still builds, but its first request raises TypeError.
            if not (client.api_key or client.auth_token or client.credentials):
                print("[chat] No Claude credentials (set ANTHROPIC_API_KEY or run `ant auth login`); "
                      "using built-in replies")
                return
            self.client = client
        except Exception as exc:  # not installed, or no credentials configured
            print(f"[chat] Claude unavailable, using built-in replies ({exc.__class__.__name__})")

    @property
    def available(self) -> bool:
        return self.client is not None

    def reply(self, character: str, history: list[dict], message: str, mood: str = "",
              emit=no_events) -> dict | None:
        """Claude's answer as {"text", "thought", "learned"}, or None when Claude
        can't answer (the caller then uses a built-in reply).

        Streams as it goes, calling `emit` with:
            {"type": "thinking", "text"}  a piece of Claude's summarized reasoning
            {"type": "text", "text"}      a piece of the reply
            {"type": "memory", "action": "remembered" | "forgot", "note"}
        Text pieces can be discarded later (a refusal); the final text is the answer.
        """
        anthropic = self.anthropic
        messages = to_claude_messages(history, message)
        text, thought, learned = "", "", []

        def track(event: dict) -> None:
            if event["type"] == "memory" and event["action"] == "remembered":
                learned.append(event["note"]["text"])
            emit(event)

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                with self.client.beta.messages.stream(
                    model=MODEL,
                    max_tokens=16000,
                    thinking={"type": "adaptive", "display": "summarized"},
                    output_config={"effort": "medium"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    system=system_prompt(character, mood, memory.notes()),
                    tools=MEMORY_TOOLS,
                    messages=messages,
                ) as stream:
                    for event in stream:
                        if event.type == "content_block_start":
                            kind = event.content_block.type
                            # Keep the pieces of a reply split by a tool call apart.
                            if kind == "text" and text and not text[-1].isspace():
                                text += " "
                                emit({"type": "text", "text": " "})
                            elif kind == "thinking" and thought:
                                thought += "\n\n"
                                emit({"type": "thinking", "text": "\n\n"})
                        elif event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                text += event.delta.text
                                emit({"type": "text", "text": event.delta.text})
                            elif event.delta.type == "thinking_delta":
                                thought += event.delta.thinking
                                emit({"type": "thinking", "text": event.delta.thinking})
                    response = stream.get_final_message()
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
            except ValueError:  # a tool call's input wasn't valid JSON
                print("[chat] Claude sent a tool call that couldn't be read; using a built-in reply")
                return None

            if response.stop_reason == "refusal":
                return None  # already-streamed text is discarded
            content = echo_blocks(response.content)
            tool_uses = [b for b in content if b.type == "tool_use"]
            if not tool_uses or response.stop_reason == "max_tokens":
                break  # a cut-off tool call isn't run
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": [run_memory_tool(b, track) for b in tool_uses]})

        text = text.strip()
        if not text:
            return None
        return {"text": text, "thought": thought.strip()[:MAX_THOUGHT_CHARS], "learned": learned}


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


memory = MemoryStore()
claude = ClaudeChat()


# --- Voice clips ---------------------------------------------------------------

# HackMp3s/<trigger><F|M><n>.mp3, e.g. happyF2.mp3: F is Mochi's voice, M is Kiko's.
VOICE_FILE = re.compile(r"(?P<trigger>[A-Za-z]+?)(?P<voice>[FM])\d+\.mp3")
VOICE_CHARACTERS = {"F": "girl", "M": "boy"}
# {"happyF1.mp3": "the exact words said in it"}. A clip without words shows
# no caption while it plays, so the text never differs from the voice.
VOICE_CAPTIONS = VOICE_DIR / "captions.json"


def scan_voice_clips() -> tuple[dict, list[str]]:
    """({trigger: {"girl": [{"url", "text"}, ...], "boy": [...]}}, names that
    don't fit the pattern). `text` is the clip's caption, or None."""
    try:
        captions = json.loads(VOICE_CAPTIONS.read_text())
    except (OSError, ValueError):
        captions = {}
    clips: dict = {}
    skipped = []
    for path in sorted(VOICE_DIR.glob("*.mp3")):
        match = VOICE_FILE.fullmatch(path.name)
        if not match:
            skipped.append(path.name)
            continue
        text = captions.get(path.name) if isinstance(captions, dict) else None
        per_character = clips.setdefault(match["trigger"], {"girl": [], "boy": []})
        per_character[VOICE_CHARACTERS[match["voice"]]].append({
            "url": f"/voice/{path.name}",
            "text": (text.strip() or None) if isinstance(text, str) else None,
        })
    return clips, skipped


# --- Extension packaging -------------------------------------------------------

def extension_version() -> str:
    try:
        return json.loads((EXT_DIR / "manifest.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return "unknown"


def request_origin(headers) -> str | None:
    """The site's address as the browser asked for it: the Host header, or
    X-Forwarded-Host/Proto behind Vercel or a tunnel. None if malformed."""
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").split(",")[0].strip().lower()
    scheme = (headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip().lower()
    if scheme not in ("http", "https") or not re.fullmatch(r"[a-z0-9.-]+(:\d{1,5})?", host):
        return None
    return f"{scheme}://{host}"


def point_config(source: str, app_url: str) -> str:
    """browser_extension/config.js, talking to app_url."""
    text, count = re.subn(r'url: "[^"]*"', lambda _: "url: " + json.dumps(app_url), source, count=1)
    if count != 1:
        raise ValueError("browser_extension/config.js has no url to set")
    return text


def point_manifest(source: str, app_url: str) -> str:
    """browser_extension/manifest.json, allowed to reach app_url and to run
    bridge.js on its pages."""
    manifest = json.loads(source)
    parts = urlsplit(app_url)
    pattern = f"{parts.scheme}://{parts.hostname}/*"  # match patterns can't name a port
    manifest["host_permissions"] = [pattern]
    for script in manifest["content_scripts"]:
        if "bridge.js" in script["js"]:
            script["matches"] = [pattern]
    return json.dumps(manifest, indent=2) + "\n"


def build_extension_zip(app_url: str = LOCAL_APP_URL) -> bytes:
    """browser_extension/, zipped. For another app_url (the site it's
    downloaded from, e.g. on Vercel), config.js and manifest.json point there."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(EXT_DIR.rglob("*")):
            rel = path.relative_to(EXT_DIR)
            if not path.is_file() or any(part.startswith(".") for part in rel.parts):
                continue
            name = str(Path("buddy-extension") / rel)
            if app_url != LOCAL_APP_URL and rel == Path("config.js"):
                zf.writestr(name, point_config(path.read_text(), app_url))
            elif app_url != LOCAL_APP_URL and rel == Path("manifest.json"):
                zf.writestr(name, point_manifest(path.read_text(), app_url))
            else:
                zf.write(path, name)
    return buf.getvalue()


# --- HTTP ----------------------------------------------------------------------

companion = None  # CompanionService, created in main()


def safe_path(root: Path, rel: str) -> Path | None:
    """Resolve `rel` inside `root`, refusing anything that escapes it."""
    target = (root / rel.lstrip("/")).resolve()
    if target == root or root in target.parents:
        return target if target.is_file() else None
    return None


class Handler(SimpleHTTPRequestHandler):
    server_version = "BuddyApp/1.0"

    # Set by make_server(): when given, GET /api/state returns this instead of
    # the companion's state (animation_bridge.AnimationBridge uses it).
    state_provider = None

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/api/status":
            return self.send_json({
                "ai": "claude" if claude.available else "offline",
                "extension_version": extension_version(),
                "brain": companion.awareness_source if companion else "off",
                "camera": companion.camera.status if companion else "unavailable",
                "extension_seen": bool(companion and companion.extension_seen),
                "keys": companion.keyboard_status if companion else "off",
            })

        if path == "/api/state":
            if self.state_provider is not None:
                return self.send_json(self.state_provider())
            if companion is None:
                return self.send_error(HTTPStatus.NOT_FOUND)
            return self.send_json(companion.state())

        if path == "/api/camera.mjpg":
            return self.stream_camera()

        if path == "/download/buddy-extension.zip":
            data = build_extension_zip(request_origin(self.headers) or LOCAL_APP_URL)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="buddy-extension.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path.startswith("/extension/"):
            return self.send_file(safe_path(EXT_DIR, path[len("/extension/"):]))

        if path == "/api/voices":
            return self.send_json(scan_voice_clips()[0])

        if path == "/api/memory":
            return self.send_json({"notes": memory.notes(), "ai": claude.available})

        if path.startswith("/voice/"):
            return self.send_file(safe_path(VOICE_DIR, path[len("/voice/"):]))

        if path == "/":
            path = "/index.html"
        return self.send_file(safe_path(UI_DIR, path))

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(length, 200_000)) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send_json({"error": "Request body must be a JSON object."}, HTTPStatus.BAD_REQUEST)

        if self.path == "/api/chat":
            return self.chat(body)
        if self.path == "/api/chat/stream":
            return self.chat_stream(body)
        if self.path == "/api/memory/forget":
            memory.forget(str(body.get("id", "")))
            return self.send_json({"notes": memory.notes()})
        if self.path == "/api/memory/clear":
            memory.clear()
            return self.send_json({"notes": []})
        if companion is None:
            return self.send_error(HTTPStatus.NOT_FOUND)

        if self.path == "/api/browser-activity":
            companion.record_browser_activity(body)
            return self.send_json({"ok": True})

        if self.path == "/api/shortcut":
            accepted = companion.record_browser_shortcut(str(body.get("shortcut", "")))
            return self.send_json({"accepted": accepted, "state": companion.state()},
                                  HTTPStatus.OK if accepted else HTTPStatus.BAD_REQUEST)

        if self.path == "/api/voice/claim":
            claimed = companion.claim_voice(str(body.get("key", ""))[:100],
                                             str(body.get("owner", ""))[:100],
                                             release=body.get("release") is True)
            return self.send_json({"claimed": claimed})

        if self.path == "/api/presence":
            companion.report_browser(str(body.get("title", ""))[:200], str(body.get("host", ""))[:100])
            if body.get("input") is True:
                companion.note_browser_input()
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
            companion.tick()
            return self.send_json(companion.state())

        if self.path == "/api/body":
            used = companion.record_browser_body(body)
            return self.send_json(companion.state(), HTTPStatus.OK if used else HTTPStatus.CONFLICT)

        return self.send_error(HTTPStatus.NOT_FOUND)

    def chat_args(self, body: dict) -> tuple[str, str, list, str]:
        """(message, character, history, mood) of a chat request. A message
        counts as attention for the buddy."""
        message = str(body.get("message", "")).strip()[:MAX_MESSAGE_CHARS]
        character = body.get("character") if body.get("character") in CHARACTERS else "girl"
        history = body.get("history") if isinstance(body.get("history"), list) else []
        mood = ""
        if message and companion is not None:
            companion.interact("chat")
            mood = mood_context(companion.state())
        return message, character, history, mood

    def chat(self, body: dict) -> None:
        message, character, history, mood = self.chat_args(body)
        if not message:
            return self.send_json({"error": "Message is empty."}, HTTPStatus.BAD_REQUEST)
        answer = claude.reply(character, history, message, mood) if claude.available else None
        if answer:
            return self.send_json({"reply": answer["text"], "source": "claude",
                                   "thought": answer["thought"], "learned": answer["learned"]})
        return self.send_json({"reply": offline_reply(character, message), "source": "offline"})

    def chat_stream(self, body: dict) -> None:
        """chat(), streamed: one JSON event per line as Claude thinks, writes and
        takes notes (see ClaudeChat.reply), ending with
        {"type": "done", "reply", "source", "thought", "learned"}. `reply` is the
        final answer, which replaces any text streamed before it."""
        message, character, history, mood = self.chat_args(body)
        if not message:
            return self.send_json({"error": "Message is empty."}, HTTPStatus.BAD_REQUEST)
        # No Content-Length: the stream ends when the connection closes (HTTP/1.0).
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def emit(event: dict) -> None:
            self.wfile.write(json.dumps(event).encode() + b"\n")
            self.wfile.flush()

        try:
            answer = claude.reply(character, history, message, mood, emit) if claude.available else None
            if answer:
                emit({"type": "done", "reply": answer["text"], "source": "claude",
                      "thought": answer["thought"], "learned": answer["learned"]})
            else:
                emit({"type": "done", "reply": offline_reply(character, message), "source": "offline",
                      "thought": "", "learned": []})
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page closed mid-reply

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

    def send_file(self, file: Path | None) -> None:
        if file is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        data = file.read_bytes()
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        # Byte ranges: WebKit (Safari, the desktop window) asks for audio this way.
        start, end = 0, len(data) - 1
        byte_range = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if byte_range and data and (byte_range[1] or byte_range[2]):
            if byte_range[1]:
                start = int(byte_range[1])
                end = min(int(byte_range[2]), end) if byte_range[2] else end
            else:  # "bytes=-N": the last N bytes
                start = max(0, len(data) - int(byte_range[2]))
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{len(data)}")
                self.end_headers()
                return
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            self.send_response(HTTPStatus.OK)
        body = data[start:end + 1]
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        # The website and extension poll these constantly; keep the log readable.
        if not self.path.startswith(
            ("/api/status", "/api/state", "/api/presence", "/api/camera.mjpg", "/api/browser-activity",
             "/api/body")
        ):
            super().log_message(fmt, *args)


def make_server(host: str = HOST, port: int = PORT, state_provider=None) -> ThreadingHTTPServer:
    """Build the app server. port=0 picks a free port (tests, animation_bridge)."""
    handler = Handler
    if state_provider is not None:
        handler = type("StateHandler", (Handler,), {"state_provider": staticmethod(state_provider)})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


KEYS_STATUS = {
    "on": "Cmd/Ctrl+C, V, Z and typing, in every app",
    "needs_permission": "off until you allow your terminal app in System Settings > Privacy & Security"
                        " > Input Monitoring, then restart",
    "unavailable": "off (pip install -r requirements.txt)",
    "off": "only what the browser extension reports",
}


# --- Desktop window ------------------------------------------------------------

def run_window(url: str) -> bool:
    """Show the app in a desktop window until it's closed.

    Returns False without opening anything when pywebview (or the GUI toolkit
    it needs) isn't installed.
    """
    try:
        import webview  # optional dependency
    except ImportError:
        print(f"[window] pywebview not installed (pip install pywebview); open {url} in your browser")
        return False

    # Both default to off in pywebview. Downloads are off, so the
    # "Download extension" button would do nothing. Private mode is on, so
    # localStorage would be wiped at every launch, and the page keeps the
    # buddy choice, chat and headpats there (the extension can't run in here).
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.create_window("AI Buddy", url, width=1180, height=800, min_size=(420, 560))
    try:
        webview.start(private_mode=False)
    except webview.errors.WebViewException as exc:  # e.g. Linux without GTK or Qt
        print(f"[window] Couldn't open the desktop window ({exc}); open {url} in your browser")
        return False
    return True


def main() -> None:
    global companion
    parser = argparse.ArgumentParser(description="Run the Buddy app and companion hub.")
    parser.add_argument("--camera", action="store_true", help="start webcam body tracking right away")
    parser.add_argument("--open", action="store_true",
                        help="open the app in your browser instead of the desktop window")
    parser.add_argument("--no-window", action="store_true",
                        help="only run the server (the extension still works); open the app at the printed URL")
    parser.add_argument("--no-native-awareness", action="store_true",
                        help="don't watch other apps; use only the browser tab the extension reports")
    parser.add_argument("--mic", action="store_true",
                        help="listen for loudness only (no recording): a yell wakes a buddy playing dead")
    parser.add_argument("--port", type=int, default=PORT,
                        help="port to serve on (the extension expects the default)")
    args = parser.parse_args()

    from companion import CompanionService

    companion = CompanionService(
        native_awareness=not args.no_native_awareness,
        enable_microphone=args.mic,
    )
    companion.start()
    if args.camera:
        if companion.camera.available():
            companion.camera.start()
        else:
            print("[camera] Body tracking needs OpenCV and MediaPipe: pip install -r requirements.txt")

    # The window has to own the main thread (macOS requires it), so the server
    # always runs in the background.
    server = make_server(HOST, args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{HOST}:{args.port}"
    sys.stdout.reconfigure(line_buffering=True)
    print(f"Buddy app running at {url}")
    print(f"  AI chat:      {'Claude' if claude.available else 'built-in replies'}")
    print(f"  Memory:       {len(memory.notes())} notes about you in buddy_data/ (delete them in the chat panel)")
    print(f"  Brain:        screen awareness from {'this computer' if companion.awareness_source == 'native' else 'the browser extension'}")
    print(f"  Body tracking: {companion.camera.status}")
    print(f"  Keys:         {KEYS_STATUS[companion.keyboard_status]}")
    clips, skipped = scan_voice_clips()
    print(f"  Voice:        {sum(len(c['girl']) + len(c['boy']) for c in clips.values())} clips in HackMp3s/")
    for name in skipped:
        print(f"[voice] Skipping HackMp3s/{name}: name it <trigger><F|M><n>.mp3 (F = Mochi, M = Kiko)")
    try:
        if args.open or args.no_window or not run_window(url):
            if args.open:
                webbrowser.open(url)
            threading.Event().wait()  # serve until Ctrl+C
    except KeyboardInterrupt:
        pass
    finally:
        companion.close()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
