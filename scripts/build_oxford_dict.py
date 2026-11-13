#!/usr/bin/env python3
"""
Build StarDict (.dict / .idx / .ifo) files from a plain English->Tagalog
word list, for CrossPoint on the Xteink X3 / X4.

CrossPoint (firmware for the Xteink X3 and X4 e-readers) reads StarDict
dictionaries from /dictionaries/ (or /.dictionaries/) on the SD card: one
folder per dictionary, holding an uncompressed .idx plus a .dict (or
.dict.dz) and an optional .ifo. The firmware builds its own fast .qidx
sidecar automatically whenever the .idx changes, so regenerating these
three files is all you need to do after adding new words.

Usage:
    python3 scripts/build_oxford_dict.py [source.txt] [output_dir]

Defaults: source=dictionary/oxford-en-tl.txt, output=dictionaries/Oxford

The .idx record layout matches CrossPoint's Dictionary::locate exactly:

    headword (NUL-terminated UTF-8) | BE32 offset into .dict | BE32 size

The index is sorted case-insensitively (ASCII), the same comparison the
reader uses for lookups, so binary search stays correct.

Run with --check to self-verify the generated index (re-reads .idx/.dict
and binary-searches a sample of words the way the device does).
"""

import argparse
import os
import struct
import sys


def parse_word_list(path):
    """Return [(word, definition), ...] from the tab-separated source."""
    entries = []
    seen = {}
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" not in line:
                print(f"warning: {path}:{lineno}: no tab separator, skipping",
                      file=sys.stderr)
                continue
            word, definition = line.split("\t", 1)
            word = word.strip()
            definition = definition.strip()
            if not word:
                print(f"warning: {path}:{lineno}: empty word, skipping",
                      file=sys.stderr)
                continue
            key = word.lower()
            if key in seen:
                print(f"warning: {path}:{lineno}: duplicate '{word}' "
                      f"(first seen at {seen[key]}), keeping first",
                      file=sys.stderr)
                continue
            seen[key] = lineno
            entries.append((word, definition))
    entries.sort(key=lambda e: e[0].lower())
    return entries


def build(stem, entries, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    dict_path = os.path.join(out_dir, stem + ".dict")
    idx_path = os.path.join(out_dir, stem + ".idx")
    ifo_path = os.path.join(out_dir, stem + ".ifo")

    offsets = []
    sizes = []
    with open(dict_path, "wb") as df:
        for word, definition in entries:
            blob = definition.encode("utf-8")
            offsets.append(df.tell())
            sizes.append(len(blob))
            df.write(blob)

    with open(idx_path, "wb") as xf:
        for (word, _), off, size in zip(entries, offsets, sizes):
            xf.write(word.encode("utf-8"))
            xf.write(b"\x00")
            xf.write(struct.pack(">II", off, size))  # BE32, BE32 (CrossPoint)

    with open(ifo_path, "w", encoding="utf-8") as ff:
        ff.write("StarDictDictionary\n")
        ff.write("ifoVersion: 3.0\n")
        ff.write(f"bookname: Oxford English-Tagalog\n")
        ff.write(f"wordcount: {len(entries)}\n")
        ff.write("synwordcount: 0\n")
        ff.write(f"idxfiles: 1: {stem}.idx\n")
        ff.write("idxfiles_bitsize: 0\n")

    return len(entries), dict_path, idx_path, ifo_path


def ascii_case_cmp(a, b):
    """CrossPoint-style case-insensitive ASCII comparison."""
    return (a.lower() > b.lower()) - (a.lower() < b.lower())


def check(stem, out_dir, entries):
    """Self-verify: re-read .idx and binary-search sample words like the reader."""
    idx_path = os.path.join(out_dir, stem + ".idx")
    dict_path = os.path.join(out_dir, stem + ".dict")

    # Parse the .idx back exactly as CrossPoint does (NUL word + BE32 off/sz).
    index = []
    with open(idx_path, "rb") as xf:
        data = xf.read()
    pos = 0
    while pos < len(data):
        end = data.index(b"\x00", pos)
        word = data[pos:end].decode("utf-8")
        off, size = struct.unpack(">II", data[end + 1:end + 9])
        index.append((word, off, size))
        pos = end + 9

    assert len(index) == len(entries), "idx entry count mismatch"
    # Sortedness check under the reader's comparison.
    for i in range(len(index) - 1):
        assert ascii_case_cmp(index[i][0], index[i + 1][0]) <= 0, \
            f"not sorted: {index[i][0]} > {index[i+1][0]}"

    def locate(target):
        lo, hi = 0, len(index) - 1
        # firmware: bisect sampled offsets then linear scan; here a plain
        # case-insensitive binary search over the parsed index is equivalent.
        while lo <= hi:
            mid = (lo + hi) // 2
            cmp = ascii_case_cmp(index[mid][0], target)
            if cmp == 0:
                return index[mid]
            if cmp < 0:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    with open(dict_path, "rb") as df:
        tests = [entries[0][0], entries[len(entries) // 2][0],
                 entries[-1][0]]
        # case-variant probes (reader strips case when searching)
        tests += [entries[0][0].upper(), entries[len(entries) // 2][0].swapcase()]
        missing = []
        src = dict((w, d) for w, d in entries)
        for word in tests:
            hit = locate(word)
            if hit is None:
                missing.append(word)
                continue
            headword, off, size = hit
            df.seek(off)
            blob = df.read(size).decode("utf-8", errors="replace")
            assert src[headword] == blob, \
                f"definition mismatch for {headword!r} (queried {word!r})"
        if missing:
            raise SystemExit(f"self-check failed: words not found: {missing}")
    print(f"self-check ok: {len(index)} index entries verified")


def main():
    ap = argparse.ArgumentParser(
        description="Build StarDict files for CrossPoint from a word list")
    ap.add_argument("source", nargs="?", default="dictionary/oxford-en-tl.txt",
                    help="input word list (default: dictionary/oxford-en-tl.txt)")
    ap.add_argument("output", nargs="?", default="dictionaries/Oxford",
                    help="output dictionary folder (default: dictionaries/Oxford)")
    ap.add_argument("--stem", default="oxford-en-tl",
                    help="file stem for .dict/.idx/.ifo (default: oxford-en-tl)")
    ap.add_argument("--check", action="store_true",
                    help="self-verify the generated index after building")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        raise SystemExit(f"source not found: {args.source}")

    entries = parse_word_list(args.source)
    if not entries:
        raise SystemExit("no usable entries found in source")
    count, dict_path, idx_path, ifo_path = build(args.stem, entries, args.output)
    print(f"built {count} entries -> {dict_path}, {idx_path}, {ifo_path}")
    if args.check:
        check(args.stem, args.output, entries)


if __name__ == "__main__":
    main()
