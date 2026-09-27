"""Beginner-friendly launcher for the existing local browser app."""
import socket
import subprocess
import sys
from pathlib import Path


def main():
    if sys.version_info < (3, 11):
        print("Buddy needs Python 3.11 or newer. Python 3.12 is suitable.")
        print("Your Python is: " + sys.version.split()[0])
        return 1

    root = Path(__file__).resolve().parent
    if not (root / "UI" / "server.py").is_file():
        print("Extract the entire ZIP first. Keep start_buddy.py inside group-2.")
        return 1

    # The same guard used by the extension packager catches unfinished merges
    # before a broken JavaScript file is sent to the browser again.
    from build_extension import check, load_manifest
    try:
        manifest = load_manifest()
        check(manifest)
    except SystemExit as exc:
        print("Buddy could not start: " + str(exc))
        print("Use the complete corrected folder; do not combine different ZIPs.")
        return 1

    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.5):
            print("Port 8765 is already in use.")
            print("Close the previous Buddy terminal (Ctrl+C), then start this copy.")
            return 1
    except OSError:
        pass

    print("Starting Buddy " + manifest["version"] + "...", flush=True)
    print("Python: " + sys.executable, flush=True)
    print("Your browser will open http://127.0.0.1:8765", flush=True)
    print("Keep this window open. Press Ctrl+C here to stop Buddy.", flush=True)
    try:
        return subprocess.call(
            [sys.executable, str(root / "UI" / "server.py"),
             "--open", "--no-native-awareness", *sys.argv[1:]],
            cwd=root,
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
