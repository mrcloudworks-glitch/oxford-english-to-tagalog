# Oxford English-to-Tagalog Dictionary for CrossPoint Reader

An offline StarDict (`sametypesequence=h`) **English → English → Tagalog** dictionary built specifically for [CrossPoint e-reader](https://github.com/crosspoint-reader/crosspoint-reader) firmware.

Every headword entry combines an Oxford English meaning with ranked Tagalog translations and bilingual usage examples:

```text
book (noun, A1)
Meaning: A set of printed pages that are fastened inside a cover so that you can turn them and read them.
Example: Could I go play after reading this book?
Tagalog: libro, aklat
Tagalog example: Puwede ba akong maglaro pagkatapos basahin itong libro?
────────────────────────────────────────
book (verb, A2)
Meaning: To arrange to have or use something on a particular date in the future; to buy a ticket in advance.
Example: He took a book off the shelf.
Tagalog: magreserba, ireserba, ipagreserba
Tagalog example: Kumuha siya ng libro sa aklatan.
```

## Dictionary Coverage & Stats

| Metric | Count |
| --- | ---: |
| Headwords (`.idx`) | 16,515 |
| Oxford 5000 core entries (with CEFR level) | 4,727 |
| Synonym / inflection / UK↔US mappings (`.syn`) | 33,761 |
| Entries with English usage example | 12,776 |
| Entries with Tagalog usage example | 11,766 |
| Entries with all 5 fields | 10,351 |
| Compressed dictionary size (`oxford-en-tl.dict.dz`) | 2.26 MB (7.18 MB raw) |

## Installing on CrossPoint Reader

Copy the **`oxford-en-tl/`** folder onto your CrossPoint SD card under `/dictionaries/`:

```text
/dictionaries/oxford-en-tl/
├── oxford-en-tl.dict.dz
├── oxford-en-tl.idx
├── oxford-en-tl.ifo
└── oxford-en-tl.syn
```

Notes for CrossPoint:
- Keep **only one** `.idx` file inside `/dictionaries/oxford-en-tl/` and keep the stem path under 151 characters (CrossPoint requirement).
- Inflected forms, irregular plurals/past tenses/comparatives (`.exc`), and UK↔US spelling variants (`colour` ↔ `color`, `tyre` ↔ `tire`, `went` → `go`, `children` → `child`) are indexed in `oxford-en-tl.syn` for instant lookup even where CrossPoint's built-in `stemVariants()` stops.
- If your device ever runs low on RAM decompressing `.dict.dz` chunks, you can decompress `oxford-en-tl.dict.dz` to `oxford-en-tl.dict` (`gzip -d -c oxford-en-tl.dict.dz > oxford-en-tl.dict`) and remove the `.dict.dz` file.

## Online updates — no SD card removal needed

The updater plugin (`crosspoint-plugin/dictionary-updater/device.json`) lets your CrossPoint reader browse and download dictionary updates directly from GitHub over WiFi, so you never have to move the SD card to a computer:

1. On the reader: **Settings → System → Plugins → Oxford English-Tagalog Dictionary**.
2. Browse the files in `oxford-en-tl/` (pulled from your GitHub branch).
3. Select a file → **Download**. It saves to `/dictionaries/oxford-en-tl/` on the SD card.
4. Open **Settings → Reader → Dictionary → Oxford**. On the next lookup CrossPoint rebuilds its `.qidx` sidecar automatically — the new words are searchable.

The plugin reads `https://api.github.com/repos/mrcloudworks-glitch/oxford-english-to-tagalog/contents/oxford-en-tl?ref=arena/09121263-oxford-english-to-tagalog` (public, no login required).

### Publishing an update from your computer

When you add new words locally:

```bash
# 1. Add the word to the curated updates list
#    edit crosspoint-plugin/dictionary-updater/curated_updates.json

# 2. Patch & rebuild the dictionary binaries locally
python3 crosspoint-plugin/dictionary-updater/build_dictionary.py --patch-existing
python3 crosspoint-plugin/dictionary-updater/validate_stardict.py oxford-en-tl

# 3. Push the updated oxford-en-tl/ binaries to GitHub
git add oxford-en-tl/
git commit -m "Update dictionary with new words"
git push origin arena/09121263-oxford-english-to-tagalog
```

Then pull the update on the reader via the plugin (step 1–3 above) — no SD card removal.

## Format & Firmware Compliance

Verified against CrossPoint's StarDict & DictZip implementation (`Dictionary.cpp`, `DictZip.cpp`, `StringUtils::asciiCaseCmp`):
- `version=2.4.2`, 32-bit offsets (no `idxoffsetbits=64`), `sametypesequence=h` (clean HTML using `<p>`, `<b>`, `<i>`, `<hr>` — zero IPA/UTF-8 glyphs missing from CrossPoint's built-in fonts).
- `.idx` and `.syn` keys strictly sorted by ASCII case-insensitive byte order (`asciiCaseCmp`), with case-folded duplicates merged onto single entries and 0-based `.syn` ordinals.
- `oxford-en-tl.dict.dz` compressed in independent 58,315-byte raw-deflate chunks (`Z_FULL_FLUSH`, `wbits=-15`, 124 chunks) with a standard DictZip `RA` extra field table for fast random-access extraction.

## Rebuilding & Validating (dictionary updater plugin)

The updater lives in `crosspoint-plugin/dictionary-updater/` (separate from the compiled dictionary in `oxford-en-tl/`). `build_dictionary.py` supports patching an existing `oxford-en-tl/` dictionary with `curated_updates.json`, or performing a full rebuild from source datasets under `/tmp/research` (or pass `--sources-dir <path>`):

```bash
# Apply curated_updates.json directly onto existing oxford-en-tl/ binaries
python3 crosspoint-plugin/dictionary-updater/build_dictionary.py --patch-existing

# Preview specific headwords without writing StarDict files
python3 crosspoint-plugin/dictionary-updater/build_dictionary.py --preview abandon book bear tyre

# Full rebuild of oxford-en-tl/ from source corpora
python3 crosspoint-plugin/dictionary-updater/build_dictionary.py

# Validate StarDict & DictZip binaries against CrossPoint invariants
python3 crosspoint-plugin/dictionary-updater/validate_stardict.py oxford-en-tl
```

To add a new word, edit `crosspoint-plugin/dictionary-updater/curated_updates.json`, run `--patch-existing`, then copy the updated `oxford-en-tl/` folder to your SD card under `/dictionaries/oxford-en-tl/`. CrossPoint rebuilds its `.qidx` sidecar automatically on the next lookup.

## Sources

- **English Headwords, Meanings, & CEFR**: Oxford 5000 (`oxford-5000-vocabulary-audio-definition`, `Oxford-5000-words`), Concise Oxford English Dictionary (`sujithps/Dictionary`, `Oxford-English-Dictionary-41K-words`), with Wordset Dictionary and NLTK WordNet 3.0 example fallbacks.
- **Tagalog Translations**: Cross-referenced & frequency-ranked across Filipino WordNet (`Filipino-WordNet`), Tagalog Wiktionary (`Wiktionary-Dictionaries`), PinoyDictionary (`tgl-dictionary-parser`, `pinoy-dictionary-scraper`), `english-tagalog-vocab`, and `LearnTagalogApp`, using `tgl_freqlist.csv` and WordNet 3.0 POS/synset disambiguation.
- **Parallel English–Tagalog Example Sentences**: Tatoeba Challenge `eng-tgl`, FloRes200 `eng-tgl`, `LearnTagalogApp`, and `Digi-bible` (KJV ↔ Ang Dating Biblia).
