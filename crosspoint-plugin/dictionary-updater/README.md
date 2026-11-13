# Oxford Dictionary Updater plugin (CrossPoint)

This folder holds the **computer-side updater** for your Oxford English → Tagalog
StarDict dictionary. Keep it separate from the compiled dictionary itself.

## Layout

```
oxford-en-tl/                        # compiled dictionary -> copy to SD card /dictionaries/
  oxford-en-tl.dict.dz
  oxford-en-tl.idx
  oxford-en-tl.ifo
  oxford-en-tl.syn

crosspoint-plugin/dictionary-updater/   # updater plugin (this folder)
  manifest.json                         # CrossPoint plugin metadata
  build_dictionary.py                   # patch/rebuild StarDict binaries
  validate_stardict.py                  # validate binaries against CrossPoint invariants
  curated_updates.json                  # add/edit words here, then run build_dictionary.py
  README.md                             # this file
```

## Adding a new word

1. Open `crosspoint-plugin/dictionary-updater/curated_updates.json` and add your
   entry under `"entries"`, e.g.:

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

2. Patch the existing dictionary binaries:

```bash
python3 crosspoint-plugin/dictionary-updater/build_dictionary.py --patch-existing
```

3. Validate:

```bash
python3 crosspoint-plugin/dictionary-updater/validate_stardict.py oxford-en-tl
```

4. Copy the updated `oxford-en-tl/` folder to your CrossPoint SD card under
   `/dictionaries/oxford-en-tl/`. CrossPoint rebuilds its `.qidx` sidecar
   automatically on the next lookup — your new word is then searchable.

## Full rebuild

If you want to rebuild from scratch instead of patching:

```bash
python3 crosspoint-plugin/dictionary-updater/build_dictionary.py
```

See `crosspoint-plugin/dictionary-updater/build_dictionary.py` and
`validate_stardict.py` for full options.

## Why two folders

- `oxford-en-tl/` is the **dictionary** — the StarDict binaries CrossPoint reads
  directly from the SD card.
- `crosspoint-plugin/dictionary-updater/` is the **updater plugin** — the
  scripts and curated updates you use to add new words and rebuild the index.

This keeps the compiled dictionary separate from the tooling that updates it.
