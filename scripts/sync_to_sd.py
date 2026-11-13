#!/usr/bin/env python3
"""
One-shot sync: copy the rebuilt StarDict files to the SD card dictionary
folder used by CrossPoint on the Xteink X3 / X4.

Usage:
    python3 scripts/sync_to_sd.py /mnt/sdcard

Copies dictionaries/Oxford/oxford-en-tl.{dict,idx,ifo} to
<mount>/dictionaries/Oxford/ (creates the folder). CrossPoint discovers the
folder on the card; then select it on the device at
Settings -> Reader -> Dictionary -> Oxford.
"""

import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT = os.path.join(REPO_ROOT, "dictionaries", "Oxford")
STEM = "oxford-en-tl"


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <sd-card-mount>", file=sys.stderr)
        sys.exit(2)
    sd = sys.argv[1]
    if not os.path.isdir(sd):
        print(f"error: {sd} is not a directory", file=sys.stderr)
        sys.exit(1)

    dest_dir = os.path.join(sd, "dictionaries", "Oxford")
    os.makedirs(dest_dir, exist_ok=True)
    ok = True
    for ext in (".dict", ".idx", ".ifo"):
        src = os.path.join(OUTPUT, STEM + ext)
        if not os.path.exists(src):
            print(f"error: {src} missing — run build_oxford_dict.py first",
                  file=sys.stderr)
            ok = False
            continue
        shutil.copy2(src, os.path.join(dest_dir, STEM + ext))
        print(f"copied {STEM + ext} -> {dest_dir}")
    os.utime(dest_dir, None)
    print("done. On the reader: Settings -> Reader -> Dictionary -> Oxford")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
