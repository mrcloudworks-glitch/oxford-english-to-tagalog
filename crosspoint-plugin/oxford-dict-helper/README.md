# Oxford English-Tagalog dictionary helper (CrossPoint SD-card plugin)

This plugin folder does nothing on the device — it only documents, on-device
under **Settings → System → Plugins**, how to keep your Oxford English →
Tagalog StarDict index current when you add new words.

CrossPoint 1.5+ reads StarDict dictionaries from `/dictionaries/` (or
`/.dictionaries/`) on the SD card, one folder per dictionary. The reader
rebuilds its fast `.qidx` sidecar automatically whenever the `.idx` file
changes, so you do not need a device-side plugin to "update the list": you
need a computer-side rebuild whenever you edit the word list, then copy the
three files to the card.

## How it works (on your computer)

This repo (`oxford-english-to-tagalog`) contains:

- `dictionary/oxford-en-tl.txt` — your editable word list
  (`word<TAB>tagalog`, one per line). Add new words here.
- `scripts/build_oxford_dict.py` — builds
  `dictionaries/Oxford/oxford-en-tl.{dict,idx,ifo}` from the list.
- `scripts/watch_oxford_dict.py` — watches the list and rebuilds (and copies
  to the SD card with `--sd /mnt/...`) on every save.
- `scripts/sync_to_sd.py` — one-shot copy to the card.

Typical workflow:

```sh
# edit the list however you like
vim dictionary/oxford-en-tl.txt

# rebuild the StarDict files
python3 scripts/build_oxford_dict.py

# copy to the SD card (adjust the mount point)
python3 scripts/sync_to_sd.py /media/$USER/XTEINK

# or keep a watcher running so every save rebuilds + syncs:
python3 scripts/watch_oxford_dict.py --sd /media/$USER/XTEINK
```

## On the Xteink X3 / X4

1. Make sure CrossPoint 1.5 or newer is installed.
2. Insert the microSD card with `/dictionaries/Oxford/` containing
   `oxford-en-tl.dict`, `oxford-en-tl.idx`, `oxford-en-tl.ifo`.
3. Open **Settings → Reader → Dictionary** and select **Oxford** (the entry
   appears only once a usable dictionary folder is on the card).
4. While reading, open the reader menu (**Confirm**) and choose **Look Up**,
   or long-press **Menu** if set to "Dictionary".

The reader shows *"Indexing dictionary…"* on the first lookup (and again
whenever `.idx` changes) while it builds the `.qidx` sidecar — after that,
your new words are findable immediately.

## Why there is no on-device compiler plugin

CrossPoint's SD-card plugin surface is declarative (catalog browse/download via
`device.json`) or browser-side (`plugin.js` in a connected browser); the
firmware itself compiles nothing on-device. The correct integration point is
therefore regenerating the StarDict files on the computer and copying them to
`/dictionaries/` on the card — exactly what the scripts above do. The reader
picks up `.idx` changes by itself.

## Dictionary source

The starter list in `dictionary/oxford-en-tl.txt` was written for this
project and is not the copyrighted Oxford dictionary — edit, add to, or
replace it freely.
