#!/usr/bin/env python3
"""
Publish Oxford English-Tagalog dictionary updates for the CrossPoint on-device updater.

The reader-side plugin (crosspoint-plugin/dictionary-updater/device.json) browses
    https://api.github.com/repos/<owner>/<repo>/contents/oxford-en-tl?ref=main
so every published build is simply the tracked oxford-en-tl/ folder on the
repository's main branch. This script is the computer-side half: it applies new
words, rebuilds the StarDict binaries, validates them, and shows exactly what
will change online.

Typical loop:
    1. add words to crosspoint-plugin/dictionary-updater/curated_updates.json
    2. python3 crosspoint-plugin/dictionary-updater/update_dictionary.py build
    3. python3 crosspoint-plugin/dictionary-updater/update_dictionary.py publish --apply
    4. on the reader: Home > Plugins > Oxford English-Tagalog > download a file

Commands:
    status     Compare the local build with the published one (reads update.json) and
               optionally with whatever live GitHub is serving.
    build      Apply curated_updates.json onto oxford-en-tl/, validate, refresh update.json.
    publish    Check the build, then commit and push oxford-en-tl/ to the ref the reader
               reads (dry run unless --apply is given).
    check-ref  Verify that the ref used by device.json actually serves the dictionary.

Run with --help for the full option list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
DICT_DIR = REPO_ROOT / "oxford-en-tl"
UPDATES = HERE / "curated_updates.json"
DEVICE_JSON = HERE / "device.json"
BUILD_SCRIPT = HERE / "build_dictionary.py"
VALIDATE_SCRIPT = HERE / "validate_stardict.py"
STORED_UPDATE = DICT_DIR / "update.json"
DICT_STEM = "oxford-en-tl"
DICT_FILES = [f"{DICT_STEM}.dict.dz", f"{DICT_STEM}.idx", f"{DICT_STEM}.ifo", f"{DICT_STEM}.syn"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def device_urls() -> tuple[str, str]:
    """Return the (browse_url, download_url_template) the reader will actually use."""
    manifest = read_json(DEVICE_JSON)
    browse = manifest["browse"]["url"]
    download = manifest.get("download", {}).get("url", "")
    return browse, download


def repo_from_url(url: str) -> str:
    """Return https://github.com/<owner>/<repo> for an api.github.com contents URL."""
    parts = urllib.parse.urlparse(url)
    segments = [seg for seg in parts.path.split("/") if seg]
    if segments[:1] == ["repos"]:
        segments = segments[1:]
    if parts.netloc != "api.github.com" or len(segments) < 2:
        return "https://github.com/mrcloudworks-glitch/oxford-english-to-tagalog"
    return f"https://github.com/{segments[0]}/{segments[1]}"


def ref_from_browse_url(browse_url: str) -> str | None:
    query = urllib.parse.urlparse(browse_url).query
    return urllib.parse.parse_qs(query).get("ref", [None])[0]


def set_ref(url: str, ref: str) -> str:
    """Point a GitHub contents URL at another branch/tag (the ref is unquoted in the URL)."""
    parts = urllib.parse.urlparse(url)
    query = [(key, ref if key == "ref" else value) for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
    if not any(key == "ref" for key, _ in query):
        query.append(("ref", ref))
    return parts._replace(query=urllib.parse.urlencode(query, safe="/")).geturl()


def http_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "oxford-en-tl-updater"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def ifo_field(name: str) -> str:
    for line in (DICT_DIR / f"{DICT_STEM}.ifo").read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1]
    return ""


def curated_entries() -> list[str]:
    entries = read_json(UPDATES).get("entries", {})
    return sorted(entries)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def update_manifest() -> dict:
    """Metadata the reader can display (file sizes, word counts) without parsing StarDict."""
    files = {
        name: {"size": (DICT_DIR / name).stat().st_size, "sha256": sha256_of(DICT_DIR / name)}
        for name in DICT_FILES
        if (DICT_DIR / name).exists()
    }
    browse_url, download_url = device_urls()
    return {
        "schema": 1,
        "name": ifo_field("bookname") or "Oxford English-English-Tagalog Dictionary",
        "headwords": int(ifo_field("wordcount") or 0),
        "synonyms": int(ifo_field("synwordcount") or 0),
        "sametypesequence": ifo_field("sametypesequence"),
        "source": {
            "repository": repo_from_url(browse_url),
            "browse_url": browse_url,
            "download_url": download_url,
        },
        "files": files,
    }


def compare_with_stored() -> list[str]:
    """Return human-readable differences between update.json and the binaries next to it."""
    if not STORED_UPDATE.exists():
        return ["update.json is missing from oxford-en-tl/"]
    stored = read_json(STORED_UPDATE)
    problems = []
    for name, meta in stored.get("files", {}).items():
        path = DICT_DIR / name
        if not path.exists():
            problems.append(f"{name}: listed in update.json but not on disk")
        elif path.stat().st_size != meta.get("size"):
            problems.append(f"{name}: size {path.stat().st_size} != update.json {meta.get('size')}")
        elif sha256_of(path) != meta.get("sha256"):
            problems.append(f"{name}: sha256 does not match update.json")
    for name in DICT_FILES:
        if (DICT_DIR / name).exists() and name not in stored.get("files", {}):
            problems.append(f"{name}: on disk but missing from update.json")
    return problems


def run(cmd: list[str]) -> int:
    print("$ " + " ".join(shlex.quote(part) for part in cmd))
    return subprocess.call(cmd, cwd=REPO_ROOT)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    print(f"Local dictionary : {DICT_DIR}")
    print(f"  headwords      : {ifo_field('wordcount')}  (Oxford CEFR entries carry a level)")
    print(f"  synonyms       : {ifo_field('synwordcount')}")
    print(f"  curated words  : {len(curated_entries())} in {UPDATES.name}")

    problems = compare_with_stored()
    if problems:
        print("\nupdate.json vs local binaries:")
        for line in problems:
            print(f"  ! {line}")
        print("  -> run 'build' to refresh the binaries and this manifest together")
    else:
        print("\nupdate.json: local binaries match the published manifest")

    browse_url, _ = device_urls()
    print(f"\nReader browse URL: {browse_url}")

    stored = read_json(STORED_UPDATE) if STORED_UPDATE.exists() else {}
    if not args.online:
        print("\n(pass --online to query GitHub for what is published right now)")
        return 1 if problems else 0

    ref = ref_from_browse_url(browse_url)
    try:
        rows = http_json(browse_url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"\nCould not reach GitHub: {exc}")
        return 2
    if not isinstance(rows, list):
        print(f"\nGitHub did not return a file list (rate limited?): {str(rows)[:200]}")
        return 2

    published = {row["name"]: row for row in rows if row.get("type") == "file"}
    print(f"\nPublished on ref {ref!r} ({len(published)} files):")
    for name in DICT_FILES:
        row = published.get(name)
        local = (DICT_DIR / name).stat().st_size if (DICT_DIR / name).exists() else None
        if not row:
            print(f"  {name:<24} MISSING online (local {local})")
            continue
        state = "same size" if row["size"] == local else f"local {local} -> online {row['size']}"
        print(f"  {name:<24} {row['size']:>9} bytes  {state}")

    if stored:
        drift = [n for n in DICT_FILES if n in published and stored.get("files", {}).get(n, {}).get("size") != published[n]["size"]]
        if drift:
            print("\nupdate.json is behind the published files: " + ", ".join(drift))
        else:
            print("\nupdate.json matches the published files on GitHub")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    before = {name: sha256_of(DICT_DIR / name) for name in DICT_FILES if (DICT_DIR / name).exists()}
    if run([sys.executable, str(BUILD_SCRIPT), "--patch-existing", "--out-dir", str(DICT_DIR)]) != 0:
        print("build_dictionary.py failed; dictionary left untouched")
        return 1
    if run([sys.executable, str(VALIDATE_SCRIPT), str(DICT_DIR)]) != 0:
        print("validate_stardict.py failed; do not publish this build")
        return 1
    changed = [n for n, digest in before.items() if sha256_of(DICT_DIR / n) != digest]
    STORED_UPDATE.write_text(json.dumps(update_manifest(), indent=2) + "\n", encoding="utf-8")
    print(f"\noxford-en-tl/update.json refreshed ({len(DICT_FILES)} files tracked)")
    if changed:
        print("Changed binaries: " + ", ".join(changed))
    else:
        print("Binaries unchanged (curated_updates.json was already applied)")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    problems = compare_with_stored()
    if problems:
        print("Refusing to publish: local binaries disagree with update.json")
        for line in problems:
            print(f"  ! {line}")
        return 1
    if run([sys.executable, str(VALIDATE_SCRIPT), str(DICT_DIR)]) != 0:
        print("Refusing to publish: validation failed")
        return 1

    browse_url, _ = device_urls()
    ref = ref_from_browse_url(browse_url) or "main"
    commands = [
        ["git", "add", "oxford-en-tl/"],
        ["git", "commit", "-m", args.message],
        ["git", "push", "origin", f"HEAD:{ref}"],
    ]
    print(f"The reader reads ref {ref!r} ({browse_url})\n")
    for cmd in commands:
        print("  " + " ".join(cmd))
    if not args.apply:
        print("\nDry run. Re-run with --apply to execute these commands.")
        return 0
    for cmd in commands:
        if run(cmd) != 0:
            print("Stopped: git command failed")
            return 1
    print(f"\nPublished. On the reader: Home > Plugins > Oxford English-Tagalog > download a file.")
    return 0


def cmd_check_ref(args: argparse.Namespace) -> int:
    browse_url, _ = device_urls()
    ref = args.ref or ref_from_browse_url(browse_url)
    if not ref:
        print("device.json browse.url has no ?ref=; default branch will be used")
        return 1
    probe = set_ref(browse_url, ref)
    print(f"Probing {probe}")
    try:
        rows = http_json(probe)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"ref {ref!r} is not usable: {exc}")
        print("Point device.json browse.url at a long-lived ref (e.g. main) so the updater keeps working.")
        return 1
    if not isinstance(rows, list):
        print(f"ref {ref!r} did not return a file list: {str(rows)[:200]}")
        return 1
    names = {row["name"] for row in rows if row.get("type") == "file"}
    missing = [n for n in DICT_FILES if n not in names]
    if missing:
        print(f"ref {ref!r} is missing dictionary files: {', '.join(missing)}")
        return 1
    print(f"ref {ref!r} serves all {len(DICT_FILES)} dictionary files")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show local build, update.json and (optionally) GitHub state")
    status.add_argument("--online", action="store_true", help="Query GitHub for the published files")
    status.set_defaults(func=cmd_status)

    build = sub.add_parser("build", help="Apply curated_updates.json, validate, refresh update.json")
    build.set_defaults(func=cmd_build)

    publish = sub.add_parser("publish", help="Push the current oxford-en-tl/ build to the ref the updater reads")
    publish.add_argument("--message", default="dict: publish dictionary update", help="Commit message")
    publish.add_argument("--apply", action="store_true", help="Actually run the git commands")
    publish.set_defaults(func=cmd_publish)

    check = sub.add_parser("check-ref", help="Verify the ref in device.json serves the dictionary")
    check.add_argument("--ref", help="Override the ref taken from device.json")
    check.set_defaults(func=cmd_check_ref)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
