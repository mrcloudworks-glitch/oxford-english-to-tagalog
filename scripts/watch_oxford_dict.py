#!/usr/bin/env python3
"""
Watch dictionary/oxford-en-tl.txt and rebuild the StarDict index whenever it
changes — so adding a new word updates the dictionary on your Xteink X3 / X4
running CrossPoint, with no manual rebuild step.

Usage:
    python3 scripts/watch_oxford_dict.py [source.txt] [output_dir] [--sd /mnt/sdcard]

Defaults:
    source     dictionary/oxford-en-tl.txt
    output     dictionaries/Oxford          (StarDict .dict/.idx/.ifo go here)
    --sd       <mount point>                (optional) also copy the rebuilt
                                            files to <mount>/dictionaries/Oxford/
                                            so the reader picks them up next
                                            time it opens the dictionary.

The watcher polls the source file every 2 seconds (no inotify dependency, so
it works the same on Windows, macOS and Linux). On every change it runs
scripts/build_oxford_dict.py and, when --sd is given, syncs the three
StarDict files to the SD card.

After the files land on the card under /dictionaries/Oxford/, CrossPoint
rebuilds its own fast .qidx sidecar automatically the next time the
dictionary is opened — new words are then searchable. Select the dictionary
on the device: Settings -> Reader -> Dictionary -> Oxford.

Press Ctrl-C to stop.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
BUILDER = os.path.join(SCRIPT_DIR, "build_oxford_dict.py")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def state_of(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None


def build_once(source, output, stem):
    cmd = [sys.executable, BUILDER, source, output, "--stem", stem]
    log(f"running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        log(line)
    for line in proc.stderr.splitlines():
        log(line)
    return proc.returncode == 0


def sync_to_sd(output, sd_mount, stem):
    """Copy the rebuilt StarDict files onto the SD card dictionary folder."""
    dest_dir = os.path.join(sd_mount, "dictionaries", "Oxford")
    os.makedirs(dest_dir, exist_ok=True)
    ok = True
    for ext in (".dict", ".idx", ".ifo"):
        src = os.path.join(output, stem + ext)
        if not os.path.exists(src):
            log(f"warning: {src} not produced, skipping")
            ok = False
            continue
        shutil.copy2(src, os.path.join(dest_dir, stem + ext))
        log(f"synced {stem + ext} -> {dest_dir}")
    # Touch the folder so CrossPoint sees .idx changed on next open.
    try:
        os.utime(dest_dir, None)
    except OSError:
        pass
    return ok


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Auto-rebuild StarDict index when the word list changes")
    ap.add_argument("source", nargs="?", default="dictionary/oxford-en-tl.txt",
                    help="input word list (relative to repo root)")
    ap.add_argument("output", nargs="?", default="dictionaries/Oxford",
                    help="output dictionary folder (relative to repo root)")
    ap.add_argument("--sd", default=None,
                    help="SD card mount point; copies rebuilt files to "
                         "<sd>/dictionaries/Oxford/")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="poll interval in seconds (default: 2)")
    ap.add_argument("--stem", default="oxford-en-tl",
                    help="file stem for .dict/.idx/.ifo (default: oxford-en-tl)")
    args = ap.parse_args()

    source = os.path.join(REPO_ROOT, args.source)
    output = os.path.join(REPO_ROOT, args.output)

    if not os.path.exists(source):
        raise SystemExit(f"source not found: {source}")

    stop = False

    def handle_sig(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    log(f"watching {source}")
    log(f"output   {output}")
    if args.sd:
        log(f"sd sync  {args.sd}/dictionaries/Oxford/")
    log("press Ctrl-C to stop")

    last = state_of(source)
    built = False

    # Initial build so the index exists before the first edit.
    if build_once(source, output, args.stem):
        built = True
        if args.sd:
            sync_to_sd(output, args.sd, args.stem)

    while not stop:
        time.sleep(args.interval)
        cur = state_of(source)
        if cur != last and cur is not None:
            log("change detected in word list -> rebuilding")
            if build_once(source, output, args.stem):
                built = True
                if args.sd:
                    sync_to_sd(output, args.sd, args.stem)
            last = cur

    if built:
        log("done. StarDict files are in " + output)
    log("stopped")


if __name__ == "__main__":
    main()
