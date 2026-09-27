"""Tests for the buddy's Claude chat: streaming, thinking, and the notes it
learns about the user (UI/server.py ClaudeChat, MemoryStore and routes).

Claude is replaced by a scripted stream, so no credentials are needed.
"""

import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.request import Request, urlopen

UI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(UI_DIR))

import server  # noqa: E402


class FakeErrors:
    """The anthropic exception classes ClaudeChat.reply catches."""
    class AuthenticationError(Exception): pass
    class RateLimitError(Exception): pass
    class APIStatusError(Exception): pass
    class APIConnectionError(Exception): pass


def start(kind):
    return SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type=kind))


def thinking(text):
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="thinking_delta", thinking=text))


def text(value):
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=value))


def block(kind, **fields):
    return SimpleNamespace(type=kind, **fields)


class FakeStream:
    def __init__(self, events, stop_reason, content):
        self.events = events
        self.final = SimpleNamespace(stop_reason=stop_reason, content=content)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.final


class FakeClient:
    """client.beta.messages.stream(...) answers with the scripted rounds in order."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **params):
        # Copy: ClaudeChat appends to the same list for the next round.
        self.requests.append({**params, "messages": list(params["messages"])})
        return self.rounds.pop(0)


def fake_chat(*rounds):
    chat = server.ClaudeChat.__new__(server.ClaudeChat)
    chat.client = FakeClient(*rounds)
    chat.anthropic = FakeErrors
    return chat


def name_round():
    """Claude thinks, greets, saves a note, then keeps talking."""
    remember = block("tool_use", id="tu1", name="remember",
                     input={"kind": "about_you", "note": "  Their name is   Sam "})
    first = FakeStream(
        [start("thinking"), thinking("They told me their name."), start("text"), text("Nice to meet you, Sam!"),
         start("tool_use")],
        "tool_use",
        [block("thinking", thinking="They told me their name.", signature="sig"),
         block("text", text="Nice to meet you, Sam!"), remember],
    )
    second = FakeStream(
        [start("text"), text("What are you studying?")],
        "end_turn",
        [block("text", text="What are you studying?")],
    )
    return first, second


class MemoryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "buddy_data" / "memory.json"
        patcher = mock.patch.object(server, "memory", server.MemoryStore(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)


class ClaudeChatTests(MemoryTestCase):
    def test_streams_thinking_and_text_and_learns_a_note(self):
        chat = fake_chat(*name_round())
        events = []
        answer = chat.reply("girl", [], "hi, I'm Sam", emit=events.append)

        self.assertEqual(answer["text"], "Nice to meet you, Sam! What are you studying?")
        self.assertEqual(answer["thought"], "They told me their name.")
        self.assertEqual(answer["learned"], ["Their name is Sam"])
        self.assertEqual([n["text"] for n in server.memory.notes()], ["Their name is Sam"])

        streamed = "".join(e["text"] for e in events if e["type"] == "text")
        self.assertEqual(streamed, answer["text"])
        self.assertIn({"type": "thinking", "text": "They told me their name."}, events)
        memory_events = [e for e in events if e["type"] == "memory"]
        self.assertEqual(memory_events[0]["action"], "remembered")

    def test_second_round_sends_back_thinking_and_tool_result(self):
        chat = fake_chat(*name_round())
        chat.reply("girl", [], "hi, I'm Sam")
        first, second = chat.client.requests
        self.assertEqual(first["thinking"], {"type": "adaptive", "display": "summarized"})
        self.assertEqual({t["name"] for t in first["tools"]}, {"remember", "forget"})
        assistant, results = second["messages"][-2:]
        self.assertEqual([b.type for b in assistant["content"]], ["thinking", "text", "tool_use"])
        self.assertEqual(results["content"][0]["tool_use_id"], "tu1")
        self.assertNotIn("is_error", results["content"][0])
        # The new note is already in the prompt Claude answers from.
        self.assertIn("Their name is Sam", second["system"])
        self.assertNotIn("Their name is Sam", first["system"])

    def test_notes_and_mood_reach_the_system_prompt(self):
        note = server.memory.remember("how_to_talk", "Likes short answers")
        chat = fake_chat(FakeStream([text("Hey!")], "end_turn", [block("text", text="Hey!")]))
        chat.reply("boy", [], "yo", mood="Right now you feel sleepy. ")
        system = chat.client.requests[0]["system"]
        self.assertIn(f"[{note['id']}] (how_to_talk) Likes short answers", system)
        self.assertIn("You are Kiko", system)
        self.assertTrue(system.rstrip().endswith("Right now you feel sleepy."))

    def test_forget_tool_removes_a_wrong_note(self):
        note = server.memory.remember("about_you", "Studies biology")
        forget = block("tool_use", id="tu1", name="forget", input={"id": note["id"]})
        chat = fake_chat(
            FakeStream([], "tool_use", [forget]),
            FakeStream([text("Chemistry, got it!")], "end_turn", [block("text", text="Chemistry, got it!")]),
        )
        events = []
        answer = chat.reply("girl", [], "no, chemistry actually", emit=events.append)
        self.assertEqual(answer["text"], "Chemistry, got it!")
        self.assertEqual(server.memory.notes(), [])
        self.assertIn("forgot", [e.get("action") for e in events])

    def test_invalid_tool_input_is_reported_and_not_saved(self):
        bad = block("tool_use", id="tu1", name="remember", input={"kind": "secrets", "note": "x"})
        chat = fake_chat(
            FakeStream([], "tool_use", [bad]),
            FakeStream([text("Okay!")], "end_turn", [block("text", text="Okay!")]),
        )
        chat.reply("girl", [], "hi")
        result = chat.client.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertEqual(server.memory.notes(), [])

    def test_refusal_discards_streamed_text(self):
        chat = fake_chat(FakeStream([text("Sure, here")], "refusal", [block("text", text="Sure, here")]))
        self.assertIsNone(chat.reply("girl", [], "something"))

    def test_cut_off_tool_call_is_not_run(self):
        partial = block("tool_use", id="tu1", name="remember", input={"kind": "about_you", "note": "Their na"})
        chat = fake_chat(FakeStream([text("Hi!")], "max_tokens", [block("text", text="Hi!"), partial]))
        self.assertEqual(chat.reply("girl", [], "hi")["text"], "Hi!")
        self.assertEqual(server.memory.notes(), [])
        self.assertEqual(len(chat.client.requests), 1)

    def test_api_errors_fall_back_to_built_in_replies(self):
        class Failing(FakeStream):
            def __enter__(self):
                raise FakeErrors.APIConnectionError()
        chat = fake_chat(Failing([], "end_turn", []))
        self.assertIsNone(chat.reply("girl", [], "hi"))
        self.assertTrue(chat.available)

    def test_rejected_credentials_turn_claude_off(self):
        class Rejected(FakeStream):
            def __enter__(self):
                raise FakeErrors.AuthenticationError()
        chat = fake_chat(Rejected([], "end_turn", []))
        self.assertIsNone(chat.reply("girl", [], "hi"))
        self.assertFalse(chat.available)

    def test_after_a_fallback_the_declined_models_thinking_and_tools_are_not_echoed(self):
        content = [block("thinking", thinking="a"), block("text", text="Partial "),
                   block("tool_use", id="old", name="remember", input={}),
                   block("fallback"), block("thinking", thinking="b"), block("text", text="rest"),
                   block("tool_use", id="new", name="remember", input={})]
        kept = server.echo_blocks(content)
        self.assertEqual([(b.type, getattr(b, "id", None)) for b in kept],
                         [("text", None), ("fallback", None), ("thinking", None), ("text", None),
                          ("tool_use", "new")])


class MemoryStoreTests(MemoryTestCase):
    def test_notes_survive_a_restart(self):
        note = server.memory.remember("about_you", "Loves cats")
        self.assertEqual(server.MemoryStore(self.path).notes(), [note])

    def test_same_note_is_kept_once(self):
        first = server.memory.remember("about_you", "Loves cats")
        again = server.memory.remember("about_you", "loves  CATS")
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(server.memory.notes()), 1)

    def test_oldest_note_goes_when_full(self):
        for i in range(server.MAX_NOTES + 3):
            server.memory.remember("about_you", f"Fact {i}")
        notes = server.memory.notes()
        self.assertEqual(len(notes), server.MAX_NOTES)
        self.assertEqual(notes[0]["text"], "Fact 3")

    def test_long_notes_are_trimmed_and_empty_ones_refused(self):
        note = server.memory.remember("how_to_talk", "x" * 500)
        self.assertEqual(len(note["text"]), server.MAX_NOTE_CHARS)
        with self.assertRaises(ValueError):
            server.memory.remember("about_you", "   ")

    def test_clear_and_forget(self):
        keep = server.memory.remember("about_you", "Keep me")
        gone = server.memory.remember("about_you", "Forget me")
        self.assertEqual(server.memory.forget(gone["id"]), gone)
        self.assertIsNone(server.memory.forget("nope"))
        self.assertEqual(server.memory.notes(), [keep])
        server.memory.clear()
        self.assertEqual(server.MemoryStore(self.path).notes(), [])

    def test_unreadable_file_starts_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json")
        self.assertEqual(server.MemoryStore(self.path).notes(), [])
        self.path.write_text(json.dumps({"notes": [{"id": "a", "kind": "weird", "text": "x"}, "junk"]}))
        self.assertEqual(server.MemoryStore(self.path).notes(), [])


class ChatRouteTests(MemoryTestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=5) as res:
            return res.headers.get("Content-Type"), res.read().decode()

    def stream(self, payload):
        ctype, raw = self.request("/api/chat/stream", payload)
        self.assertEqual(ctype, "application/x-ndjson")
        return [json.loads(line) for line in raw.splitlines()]

    def test_stream_without_claude_ends_with_a_built_in_reply(self):
        offline = server.ClaudeChat.__new__(server.ClaudeChat)
        offline.client = None
        with mock.patch.object(server, "claude", offline):
            events = self.stream({"message": "thanks!", "character": "boy"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "done")
        self.assertEqual(events[0]["source"], "offline")
        self.assertIn(events[0]["reply"], server.OFFLINE_REPLIES["boy"]["thanks"])

    def test_stream_relays_claude_events_then_done(self):
        with mock.patch.object(server, "claude", fake_chat(*name_round())):
            events = self.stream({"message": "hi, I'm Sam", "character": "girl",
                                  "history": [{"role": "buddy", "text": "Hi!"}]})
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds[0], "thinking")
        self.assertIn("memory", kinds)
        self.assertEqual(kinds[-1], "done")
        done = events[-1]
        self.assertEqual(done["source"], "claude")
        self.assertEqual(done["reply"], "Nice to meet you, Sam! What are you studying?")
        self.assertEqual(done["learned"], ["Their name is Sam"])

    def test_plain_chat_route_includes_what_was_learned(self):
        with mock.patch.object(server, "claude", fake_chat(*name_round())):
            _, raw = self.request("/api/chat", {"message": "hi, I'm Sam"})
        data = json.loads(raw)
        self.assertEqual(data["reply"], "Nice to meet you, Sam! What are you studying?")
        self.assertEqual(data["learned"], ["Their name is Sam"])
        self.assertEqual(data["thought"], "They told me their name.")

    def test_memory_routes_list_forget_and_clear(self):
        a = server.memory.remember("about_you", "Loves cats")
        b = server.memory.remember("how_to_talk", "Likes jokes")
        _, raw = self.request("/api/memory")
        self.assertEqual(json.loads(raw)["notes"], [a, b])
        _, raw = self.request("/api/memory/forget", {"id": a["id"]})
        self.assertEqual(json.loads(raw)["notes"], [b])
        _, raw = self.request("/api/memory/clear", {})
        self.assertEqual(json.loads(raw)["notes"], [])
        self.assertEqual(server.MemoryStore(self.path).notes(), [])


if __name__ == "__main__":
    unittest.main()
