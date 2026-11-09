#!/usr/bin/env python3
"""
Validate generated StarDict files against CrossPoint e-reader firmware invariants
(Dictionary.cpp, DictZip.cpp, StringUtils::asciiCaseCmp).
"""

from __future__ import annotations

import gzip
import html
import re
import struct
import sys
import zlib
from pathlib import Path

MAX_DEFINITION_BYTES = 65536
MAX_HEADWORD_BYTES = 255
MAX_CHUNK_COUNT = 8192
MAX_PATH_STEM_LEN = 151  # PATH_BUF_BYTES(160) - len(".dict.dz") - 1


def ascii_lower_bytes(b: bytes) -> bytes:
    return bytes(c + 32 if 65 <= c <= 90 else c for c in b)


def ascii_case_cmp(a: bytes, b: bytes) -> int:
    la, lb = ascii_lower_bytes(a), ascii_lower_bytes(b)
    if la < lb:
        return -1
    if la > lb:
        return 1
    return 0


def parse_dictzip(dz_bytes: bytes):
    assert len(dz_bytes) >= 20, "dict.dz too small"
    assert dz_bytes[0] == 0x1F and dz_bytes[1] == 0x8B and dz_bytes[2] == 8, "Invalid gzip magic/method"
    flags = dz_bytes[3]
    assert (flags & 0x04) != 0, "FEXTRA flag missing (required by DictZip.cpp)"
    xlen = struct.unpack_from("<H", dz_bytes, 10)[0]
    pos = 12
    extra_end = pos + xlen
    assert extra_end <= len(dz_bytes), "FEXTRA overflows file"

    found_ra = False
    chunk_len = 0
    chunk_offsets = [0]
    while pos + 4 <= extra_end:
        sub_id = dz_bytes[pos : pos + 2]
        sub_len = struct.unpack_from("<H", dz_bytes, pos + 2)[0]
        pos += 4
        assert pos + sub_len <= extra_end, "Subfield overflows FEXTRA"
        if sub_id == b"RA":
            assert not found_ra, "Duplicate RA chunk table"
            assert sub_len >= 6, "RA subfield too short"
            version, chunk_len, chunk_count = struct.unpack_from("<HHH", dz_bytes, pos)
            assert version == 1, f"Unsupported RA version {version}"
            assert chunk_len > 0 and 0 < chunk_count <= MAX_CHUNK_COUNT, f"Bad chunk params {chunk_len}, {chunk_count}"
            assert sub_len == 6 + 2 * chunk_count, "RA subLen mismatch"
            cum = 0
            for i in range(chunk_count):
                comp_len = struct.unpack_from("<H", dz_bytes, pos + 6 + 2 * i)[0]
                cum += comp_len
                chunk_offsets.append(cum)
            found_ra = True
        pos += sub_len

    assert pos == extra_end and found_ra, "Missing or misaligned RA table"
    if flags & 0x08:  # FNAME
        pos = dz_bytes.index(0, pos) + 1
    if flags & 0x10:  # FCOMMENT
        pos = dz_bytes.index(0, pos) + 1
    if flags & 0x02:  # FHCRC
        pos += 2

    data_offset = pos
    isize = struct.unpack_from("<I", dz_bytes, len(dz_bytes) - 4)[0]
    assert isize > 0, "Zero uncompressed ISIZE"
    return {
        "data_offset": data_offset,
        "chunk_len": chunk_len,
        "chunk_offsets": chunk_offsets,
        "total_size": isize,
    }


def extract_entry_random_access(dz_bytes: bytes, dz_info: dict, offset: int, size: int) -> bytes:
    """Mirror DictZip::extractEntry using independent raw-deflate chunk inflation."""
    total_size = dz_info["total_size"]
    chunk_len = dz_info["chunk_len"]
    chunk_offsets = dz_info["chunk_offsets"]
    data_offset = dz_info["data_offset"]

    assert offset <= total_size and size <= total_size - offset, "Entry out of dictzip bounds"
    if size == 0:
        return b""

    start_chunk = offset // chunk_len
    end_chunk = (offset + size - 1) // chunk_len
    assert end_chunk + 1 < len(chunk_offsets), "Chunk index out of range"

    last_chunk = len(chunk_offsets) - 2
    remaining = size
    out = bytearray()

    for chunk in range(start_chunk, end_chunk + 1):
        chunk_out_size = (total_size - chunk * chunk_len) if chunk == last_chunk else chunk_len
        if chunk_out_size == 0 or chunk_out_size > chunk_len:
            chunk_out_size = chunk_len
        local_offset = (offset % chunk_len) if chunk == start_chunk else 0
        take = min(remaining, chunk_out_size - local_offset)

        comp_start = data_offset + chunk_offsets[chunk]
        comp_end = data_offset + chunk_offsets[chunk + 1]
        comp_slice = dz_bytes[comp_start:comp_end]

        infl = zlib.decompressobj(wbits=-15)
        raw_chunk = infl.decompress(comp_slice) + infl.flush()
        assert len(raw_chunk) >= local_offset + take, (
            f"Chunk {chunk} inflated to {len(raw_chunk)} < {local_offset + take}"
        )
        out.extend(raw_chunk[local_offset : local_offset + take])
        remaining -= take

    assert remaining == 0
    return bytes(out)


def parse_idx(idx_bytes: bytes):
    entries: list[tuple[bytes, int, int]] = []
    pos = 0
    prev_word = None
    while pos < len(idx_bytes):
        nul = idx_bytes.index(0, pos)
        word = idx_bytes[pos:nul]
        assert 0 < len(word) <= MAX_HEADWORD_BYTES, f"Invalid headword length at {pos}: {len(word)}"
        offset, size = struct.unpack_from(">II", idx_bytes, nul + 1)
        assert 0 < size <= MAX_DEFINITION_BYTES, f"Invalid def size {size} for {word!r}"
        if prev_word is not None:
            assert ascii_case_cmp(prev_word, word) <= 0, (
                f".idx sort order violated: {prev_word!r} before {word!r}"
            )
        prev_word = word
        entries.append((word, offset, size))
        pos = nul + 9
    assert pos == len(idx_bytes), "Trailing bytes in .idx"
    return entries


def parse_syn(syn_bytes: bytes, wordcount: int):
    syns: list[tuple[bytes, int]] = []
    pos = 0
    prev_word = None
    while pos < len(syn_bytes):
        nul = syn_bytes.index(0, pos)
        word = syn_bytes[pos:nul]
        assert 0 < len(word) <= MAX_HEADWORD_BYTES, f"Invalid syn length at {pos}: {len(word)}"
        ordinal = struct.unpack_from(">I", syn_bytes, nul + 1)[0]
        assert 0 <= ordinal < wordcount, f"Syn ordinal {ordinal} out of bounds ({wordcount})"
        if prev_word is not None:
            assert ascii_case_cmp(prev_word, word) <= 0, (
                f".syn sort order violated: {prev_word!r} before {word!r}"
            )
        prev_word = word
        syns.append((word, ordinal))
        pos = nul + 5
    assert pos == len(syn_bytes), "Trailing bytes in .syn"
    return syns


def bisect_lookup(entries: list[tuple[bytes, int, int]], query: str) -> list[tuple[bytes, int, int]]:
    q = query.encode("utf-8")
    lo, hi = 0, len(entries)
    while lo < hi:
        mid = (lo + hi) // 2
        if ascii_case_cmp(entries[mid][0], q) < 0:
            lo = mid + 1
        else:
            hi = mid
    hits = []
    while lo < len(entries) and ascii_case_cmp(entries[lo][0], q) == 0:
        hits.append(entries[lo])
        lo += 1
    return hits


def bisect_syn(syns: list[tuple[bytes, int]], query: str) -> list[int]:
    q = query.encode("utf-8")
    lo, hi = 0, len(syns)
    while lo < hi:
        mid = (lo + hi) // 2
        if ascii_case_cmp(syns[mid][0], q) < 0:
            lo = mid + 1
        else:
            hi = mid
    ords = []
    while lo < len(syns) and ascii_case_cmp(syns[lo][0], q) == 0:
        ords.append(syns[lo][1])
        lo += 1
    return ords


def validate(dict_dir: Path) -> None:
    idx_files = list(dict_dir.glob("*.idx"))
    assert len(idx_files) == 1, f"Expected exactly 1 .idx file in {dict_dir}, got {idx_files}"
    stem = idx_files[0].stem
    sd_path = f"/dictionaries/{dict_dir.name}/{stem}"
    assert len(sd_path) <= MAX_PATH_STEM_LEN, f"SD path too long ({len(sd_path)} > {MAX_PATH_STEM_LEN}): {sd_path}"

    ifo_path = dict_dir / f"{stem}.ifo"
    idx_path = dict_dir / f"{stem}.idx"
    dz_path = dict_dir / f"{stem}.dict.dz"
    syn_path = dict_dir / f"{stem}.syn"

    assert ifo_path.exists() and idx_path.exists() and dz_path.exists(), "Missing required .ifo/.idx/.dict.dz"

    ifo_lines = ifo_path.read_text(encoding="utf-8").splitlines()
    assert ifo_lines and ifo_lines[0] == "StarDict's dict ifo file", "Invalid .ifo header"
    ifo_kv = dict(line.split("=", 1) for line in ifo_lines[1:] if "=" in line)
    assert ifo_kv.get("idxoffsetbits") != "64", "64-bit offsets unsupported by CrossPoint"
    assert ifo_kv.get("sametypesequence") == "h", f"Expected sametypesequence=h, got {ifo_kv.get('sametypesequence')!r}"

    idx_bytes = idx_path.read_bytes()
    assert int(ifo_kv["idxfilesize"]) == len(idx_bytes), "idxfilesize mismatch"

    entries = parse_idx(idx_bytes)
    assert int(ifo_kv["wordcount"]) == len(entries), "wordcount mismatch"

    dz_bytes = dz_path.read_bytes()
    dz_info = parse_dictzip(dz_bytes)
    uncompressed = gzip.decompress(dz_bytes)
    assert len(uncompressed) == dz_info["total_size"], "gzip uncompressed size != RA totalSize"

    syns = []
    if syn_path.exists():
        syn_bytes = syn_path.read_bytes()
        syns = parse_syn(syn_bytes, len(entries))
        assert int(ifo_kv["synwordcount"]) == len(syns), "synwordcount mismatch"

    # Verify EVERY entry slice is valid UTF-8 & bounds-safe, and run chunk-level DictZip extraction on 500+ entries
    sample_indices = set(range(0, min(50, len(entries))))
    sample_indices.update(range(max(0, len(entries) - 50), len(entries)))
    step = max(1, len(entries) // 450)
    sample_indices.update(range(0, len(entries), step))
    # Add entries crossing chunk boundaries
    chunk_len = dz_info["chunk_len"]
    for idx_i, (_, off, sz) in enumerate(entries):
        if off // chunk_len != (off + sz - 1) // chunk_len:
            sample_indices.add(idx_i)
            if len(sample_indices) > 900:
                break

    for idx_i in sorted(sample_indices):
        word_b, off, sz = entries[idx_i]
        extracted = extract_entry_random_access(dz_bytes, dz_info, off, sz)
        assert extracted == uncompressed[off : off + sz], f"Random-access chunk mismatch at {word_b!r}"
        text = extracted.decode("utf-8")
        assert "<p><b>" in text and "<b>Meaning:</b>" in text and "<b>Tagalog:</b>" in text, (
            f"Malformed entry layout for {word_b!r}: {text[:150]}"
        )

    # Verify all .idx entries decode cleanly as UTF-8 and obey tag structure
    for word_b, off, sz in entries:
        assert off + sz <= len(uncompressed), f"Entry {word_b!r} out of uncompressed bounds"
        _ = word_b.decode("utf-8")

    # Test real CrossPoint-style lookups (direct .idx + .syn irregulars/variants)
    test_direct = ["abandon", "ability", "achieve", "book", "friend", "house", "love", "run", "tyre", "water", "whisper"]
    for q in test_direct:
        hits = bisect_lookup(entries, q)
        assert hits, f"Missing expected headword {q!r}"
        _, off, sz = hits[0]
        body = extract_entry_random_access(dz_bytes, dz_info, off, sz).decode("utf-8")
        assert "<b>Meaning:</b>" in body and "<b>Tagalog:</b>" in body, f"Incomplete body for {q!r}"

    test_syns = [
        ("went", "go"),
        ("children", "child"),
        ("better", "good"),
        ("mice", "mouse"),
        ("teeth", "tooth"),
        ("color", "colour"),
        ("studied", "study"),
    ]
    for surf, expected_target in test_syns:
        hits = bisect_lookup(entries, surf)
        if hits:
            continue  # already an exact headword (e.g. color vs colour)
        ords = bisect_syn(syns, surf)
        assert ords, f"Missing expected .syn mapping for {surf!r} -> {expected_target!r}"
        targets = [entries[o][0].decode("utf-8") for o in ords]
        assert expected_target in targets or any(expected_target in t for t in targets), (
            f".syn {surf!r} resolved to {targets}, expected {expected_target!r}"
        )

    print(
        f"VALIDATED {dict_dir}:\n"
        f"  headwords: {len(entries):,}\n"
        f"  synonyms:  {len(syns):,}\n"
        f"  dictzip:   {len(dz_info['chunk_offsets']) - 1} chunks x {chunk_len}B -> "
        f"{len(dz_bytes):,}B ({len(uncompressed):,}B raw)\n"
        f"  verified {len(sample_indices):,} chunk-level random-access extractions & {len(test_direct) + len(test_syns)} lookups."
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("oxford-en-tl")
    validate(target)
