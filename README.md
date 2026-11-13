# oxford-english-to-tagalog

Computer-side "plugin/patch" for **CrossPoint** on the **Xteink X3 / X4**:
rebuild the StarDict dictionary index automatically whenever you add new
words to your English → Tagalog word list.

## What this is

CrossPoint 1.5+ supports offline StarDict dictionaries stored on the SD card
(`/dictionaries/<name>/` with `.dict`, `.idx` and optional `.ifo`), and it
rebuilds its own fast `.qidx` sidecar automatically whenever `.idx` changes.
There is no on-device compiler plugin needed — CrossPoint's plugin surface is
declarative (catalogs/downloads) or browser UI, and the reader picks up index
changes by itself. What *is* needed is a tool that turns your editable word
list into StarDict files and rebuilds them when you add a word. That is what
this repo provides.

```
dictionary/oxford-en-tl.txt   <- edit this; add words (word<TAB>tagalog)
scripts/build_oxford_dict.py  <- builds dictionaries/Oxford/*.{dict,idx,ifo}
scripts/watch_oxford_dict.py  <- watches the list; rebuilds (+ syncs to SD)
scripts/sync_to_sd.py         <- one-shot copy to the SD card
dictionaries/Oxford/          <- generated StarDict files (gitignored)
```

## Quick start

### 1. On the device (Xteink X3 / X4 with CrossPoint 1.5+)

- Copy `dictionaries/Oxford/` to `/dictionaries/Oxford/` on the microSD card.
- **Settings → Reader → Dictionary** → select **Oxford**.
- Look up while reading: reader menu → **Look Up**, or long-press **Menu**
  when set to "Dictionary".

### 2. On your computer

```sh
# add a new word to the list
echo 'newword\tbago' >> dictionary/oxford-en-tl.txt

# rebuild the StarDict files
python3 scripts/build_oxford_dict.py

# copy to the SD card (adjust the mount point)
python3 scripts/sync_to_sd.py /media/$USER/XTEINK
```

The reader re-indexes automatically on the next lookup — no restart needed.

### 3. Auto-rebuild on every save

```sh
python3 scripts/watch_oxford_dict.py --sd /media/$USER/XTEINK
```

Keeps `dictionaries/Oxford/` and the SD card copy in sync as you edit.

## File layout on the SD card

```
/dictionaries/Oxford/
  oxford-en-tl.dict   definition data
  oxford-en-tl.idx    word index (uncompressed, required)
  oxford-en-tl.ifo    metadata (optional)
.qidx                 rebuilt by CrossPoint automatically (sidecar)
```

Folder name `Dictionaries`/`dictionaries` is case-sensitive on some setups —
use exactly `dictionaries` with one dictionary per folder; folders with more
than one `.idx` stem are skipped as ambiguous.

## StarDict format notes (CrossPoint-compatible)

- `.idx` records: NUL-terminated headword + **big-endian 32-bit** offset +
  **big-endian 32-bit** size, sorted case-insensitively (ASCII). Matches
  `Dictionary::locate` in crosspoint-reader.
- `.dict` holds plain-text definition blobs (uncompressed; `.dict.dz` also
  accepted by CrossPoint).
- `.ifo` written with `wordcount`, `idxfiles`, `idxfiles_bitsize: 0`.
- No 64-bit offsets (`idxoffsetbits=64` is rejected by the reader).

## Dictionary content

The starter list in `dictionary/oxford-en-tl.txt` was written for this
project — it is **not** the copyrighted Oxford dictionary. Add, edit, or
remove entries freely; the build script deduplicates and sorts automatically.

CrossPoint source: https://github.com/PilotConway/crosspoint-reader
