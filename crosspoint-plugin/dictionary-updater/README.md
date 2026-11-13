# Oxford Dictionary Updater plugin (CrossPoint)

This folder holds the **online updater** for your Oxford English → Tagalog
StarDict dictionary, plus the computer-side tools that publish new builds.

The reader downloads updates straight from the GitHub folder you linked to:

```text
https://github.com/mrcloudworks-glitch/oxford-english-to-tagalog/tree/main/oxford-en-tl
```

## Layout

```text
oxford-en-tl/                          # the dictionary that is published online
  oxford-en-tl.dict.dz
  oxford-en-tl.idx
  oxford-en-tl.ifo
  oxford-en-tl.syn
  update.json                          # published build info (word counts, sizes, sha256)

crosspoint-plugin/dictionary-updater/  # updater plugin (this folder)
  device.json                          # CrossPoint on-device catalog manifest
  manifest.json                        # CrossPoint plugin metadata
  update_dictionary.py                 # status / build / publish / check-ref helper
  build_dictionary.py                  # patch or rebuild the StarDict binaries
  validate_stardict.py                 # check binaries against CrossPoint invariants
  curated_updates.json                 # add/edit words here
  README.md                            # this file
```

## Updating the dictionary on the reader

1. Copy this whole `dictionary-updater/` folder onto the SD card as
   `/plugins/dictionary-updater/` (`/.crosspoint/plugins/` and `/.plugins/` work
   too — the firmware scans all three roots).
2. On the reader: **Settings → Connectivity → Plugins → Enabled**.
3. Open **Home → Plugins → Oxford English-Tagalog** (Wi-Fi is prompted if needed).
4. Pick a file and download it. Files land in `/dictionaries/oxford-en-tl/`,
   replacing the old copy.

Download order matters if your reader still has the previous build. Grab
**`oxford-en-tl.dict.dz` first**, then `oxford-en-tl.idx`, then `oxford-en-tl.syn`
(and `oxford-en-tl.ifo` if present). `.ifo` and `.syn` are read straight away;
`.idx` and `.dict.dz` are only opened on the next lookup, so an interrupted
download of either one gets retried before it is used.

5. Open **Settings → Reader → Dictionary → Oxford**. The next lookup rebuilds
   the reader's `.qidx` / `.sidx` sidecars automatically and the new words are
   searchable. That first lookup shows *"Indexing dictionary…"* for a few seconds.

> The plugin asks GitHub for the files at the path `oxford-en-tl/` on the
> `main` branch, over plain HTTPS. No login or token is needed because the
> repository is public.

## Publishing an update from your computer

The reader always pulls the *committed* `oxford-en-tl/` folder, so publishing
means "rebuild, validate, commit, push to `main`". `update_dictionary.py`
does that in one step:

```bash
# 1. Add or edit a word in curated_updates.json (format below)

# 2. Rebuild + validate + refresh oxford-en-tl/update.json
python3 crosspoint-plugin/dictionary-updater/update_dictionary.py build

# 3. Push it to the main branch the reader reads
python3 crosspoint-plugin/dictionary-updater/update_dictionary.py publish --apply
```

`publish` refuses to push when the binaries no longer match `update.json`, when
`validate_stardict.py` fails, or when the reader's `?ref=` does not point at a
branch you are publishing to. Without `--apply` it only prints the commands.

Useful checks:

```bash
# Local build vs. the published manifest, and what GitHub is serving right now
python3 crosspoint-plugin/dictionary-updater/update_dictionary.py status --online

# Does the ref in device.json actually serve the dictionary?
python3 crosspoint-plugin/dictionary-updater/update_dictionary.py check-ref
```

## Adding a new word

Add an entry under `"entries"` in `curated_updates.json`:

```json
{
  "entries": {
    "yourword": [
      {
        "pos": "noun",
        "cefr": "B1",
        "meaning": "Your English meaning here.",
        "example_en": "An English example sentence.",
        "tagalog": ["Tagalog translation"],
        "example_tl": "Tagalog example sentence."
      }
    ]
  }
}
```

Then run `build` and `publish --apply` as above. `"synonyms"` in the same file
maps inflections and spelling variants (`"colour": ["color"]`) onto headwords.

## Full rebuild

Patching is enough for new words. To rebuild everything from the source corpora
under `/tmp/research` (or `--sources-dir <path>`):

```bash
python3 crosspoint-plugin/dictionary-updater/build_dictionary.py
python3 crosspoint-plugin/dictionary-updater/validate_stardict.py oxford-en-tl
python3 crosspoint-plugin/dictionary-updater/update_dictionary.py publish --apply
```

## Why two folders

- `oxford-en-tl/` is the **dictionary** — the StarDict binaries the reader reads
  from the SD card and the files the online updater serves.
- `crosspoint-plugin/dictionary-updater/` is the **updater** — the on-device
  catalog manifest plus the scripts you use to add words and publish builds.

Keeping them separate means the published dictionary folder contains only what
the reader needs.

## Troubleshooting

- **The plugin is not listed** — plugins are off. Set
  **Settings → Connectivity → Plugins** to Enabled. Firmware older than 2.0.0
  has no plugin support, so copy `oxford-en-tl/` to the SD card by hand.
- **Browse shows an error** — GitHub answered with something other than a file
  list. Check Wi-Fi, then re-open the catalog; `check-ref` from a computer tells
  you whether the branch and path still exist.
- **"Word not found" after updating** — the files were downloaded in a different
  order and the reader is still using the old `.idx`. Re-download
  `oxford-en-tl.idx` (and `.dict.dz`), then look the word up again.
- **Not enough memory loading `.dict.dz`** — on readers without PSRAM, unpack it
  once (`gzip -d -c oxford-en-tl.dict.dz > oxford-en-tl.dict`), delete the
  `.dict.dz` on the card, and look up the word again.
