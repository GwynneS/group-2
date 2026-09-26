"""Package the browser extension for every browser.

    python3 build_extension.py                    # all targets
    python3 build_extension.py chromium firefox   # just some

Output in dist/:

    buddy-chromium-<version>.zip   Chrome, Edge, Brave, Opera, Vivaldi, Arc.
                                   Upload to the Chrome Web Store, Edge Add-ons
                                   or Opera add-ons; or unzip and Load unpacked.
    buddy-firefox-<version>.zip    Firefox (desktop and Android). Upload to
                                   addons.mozilla.org to get it signed.
    safari/extension/              Safari (macOS, iOS). Load it as a temporary
                                   extension in Safari 18+, or turn it into an
                                   Xcode app with safari-web-extension-converter
                                   (run automatically when Xcode is installed).

browser_extension/manifest.json itself works unpacked in both Chromium and
Firefox (that's what the Buddy app's download serves). Each package here
keeps only the manifest keys its browser understands, so store reviews
don't flag the others.

Standard library only.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXT_DIR = ROOT / "browser_extension"
DIST = ROOT / "dist"

# Change before publishing to the App Store; must be unique to your team.
SAFARI_BUNDLE_ID = "com.group2.buddy"
SAFARI_APP_NAME = "Buddy"

TARGETS = ("chromium", "firefox", "safari")


def source_files() -> list[Path]:
    """Everything in browser_extension/ except dotfiles, like UI/server.py's zip."""
    return [
        path for path in sorted(EXT_DIR.rglob("*"))
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(EXT_DIR).parts)
    ]


def load_manifest() -> dict:
    text = (EXT_DIR / "manifest.json").read_text()
    try:
        return json.loads(text)
    except ValueError as exc:
        sys.exit(f"browser_extension/manifest.json isn't valid JSON ({exc}). Unresolved merge conflict?")


def referenced_files(manifest: dict) -> set[str]:
    refs = set(manifest.get("icons", {}).values())
    action = manifest.get("action", {})
    refs |= set(action.get("default_icon", {}).values())
    if "default_popup" in action:
        refs.add(action["default_popup"])
    background = manifest.get("background", {})
    refs |= set(background.get("scripts", []))
    if "service_worker" in background:
        refs.add(background["service_worker"])
    for script in manifest.get("content_scripts", []):
        refs |= set(script.get("js", [])) | set(script.get("css", []))
    return refs


def check(manifest: dict) -> None:
    missing = sorted(ref for ref in referenced_files(manifest) if not (EXT_DIR / ref).is_file())
    if missing:
        sys.exit(f"manifest.json points at files that don't exist: {', '.join(missing)}")
    conflicted = [
        str(path.relative_to(ROOT)) for path in source_files()
        if path.suffix in {".js", ".json", ".html", ".css"}
        and any(line.startswith(("<<<<<<< ", ">>>>>>> ")) for line in path.read_text().splitlines())
    ]
    if conflicted:
        sys.exit(f"Unresolved merge conflicts in: {', '.join(conflicted)}")


def manifest_for(target: str, source: dict) -> dict:
    m = copy.deepcopy(source)
    settings = m.pop("browser_specific_settings", {})
    scripts = m["background"].get("scripts", [])
    worker = m["background"].get("service_worker")

    if target == "chromium":
        # Chrome runs the background as a service worker; background.js
        # importScripts() characters.js itself.
        m["background"] = {"service_worker": worker}
    elif target == "firefox":
        # Firefox runs background.scripts as an event page and has no
        # service worker support for extensions.
        m.pop("minimum_chrome_version", None)
        m["background"] = {"scripts": scripts}
        m["browser_specific_settings"] = {
            key: settings[key] for key in ("gecko", "gecko_android") if key in settings
        }
    elif target == "safari":
        m.pop("minimum_chrome_version", None)
        m["background"] = {"service_worker": worker}
        if "safari" in settings:
            m["browser_specific_settings"] = {"safari": settings["safari"]}
    return m


def write_zip(dest: Path, manifest: dict) -> None:
    # Fixed timestamps so the same source always gives the same zip, which
    # keeps store diffs and Mozilla's source review simple.
    def add(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
        info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        zf.writestr(info, data)

    with zipfile.ZipFile(dest, "w") as zf:
        add(zf, "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
        for path in source_files():
            rel = path.relative_to(EXT_DIR).as_posix()
            if rel != "manifest.json":
                add(zf, rel, path.read_bytes())


def write_folder(dest: Path, manifest: dict) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    for path in source_files():
        target = dest / path.relative_to(EXT_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def convert_for_safari(extension: Path) -> str:
    have_xcode = bool(shutil.which("xcrun")) and subprocess.run(
        ["xcrun", "--find", "safari-web-extension-converter"], capture_output=True,
    ).returncode == 0
    command = [
        "xcrun", "safari-web-extension-converter", str(extension),
        "--project-location", str(extension.parent),
        "--app-name", SAFARI_APP_NAME,
        "--bundle-identifier", SAFARI_BUNDLE_ID,
        "--swift", "--copy-resources", "--no-open", "--no-prompt", "--force",
    ]
    if not have_xcode:
        return "Xcode not found; to build the Safari app later, run:\n      " + " ".join(command)
    subprocess.run(command, check=True)
    return f"Xcode project in {(extension.parent / SAFARI_APP_NAME).relative_to(ROOT)}/"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("targets", nargs="*", choices=TARGETS, help="default: all")
    targets = parser.parse_args().targets or TARGETS

    source = load_manifest()
    check(source)
    version = source["version"]
    DIST.mkdir(exist_ok=True)

    for target in targets:
        manifest = manifest_for(target, source)
        if target == "safari":
            extension = DIST / "safari" / "extension"
            write_folder(extension, manifest)
            print(f"safari    {extension.relative_to(ROOT)}/")
            print(f"          {convert_for_safari(extension)}")
        else:
            dest = DIST / f"buddy-{target}-{version}.zip"
            write_zip(dest, manifest)
            print(f"{target:<9} {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
