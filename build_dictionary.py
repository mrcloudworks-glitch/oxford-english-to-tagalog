#!/usr/bin/env python3
"""
Build an Oxford English-to-English-to-Tagalog StarDict dictionary for CrossPoint e-readers.

Entry layout (sametypesequence=h):
    english word > meaning > example in sentence > tagalog translate > example in tagalog

Output files (written to --out-dir, default ./oxford-en-tl):
    oxford-en-tl.ifo       StarDict metadata (version=2.4.2, 32-bit offsets, sametypesequence=h)
    oxford-en-tl.idx       Uncompressed index sorted by CrossPoint's asciiCaseCmp
    oxford-en-tl.dict.dz   DictZip-compressed definitions (58315B chunks, Z_FULL_FLUSH + RA table)
    oxford-en-tl.syn       Synonym/inflection/UK-US variant index sorted by asciiCaseCmp
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import html
import json
import math
import os
import re
import struct
import zipfile
import zlib
from collections import defaultdict
from pathlib import Path

DICT_STEM = "oxford-en-tl"
BOOKNAME = "Oxford English-English-Tagalog Dictionary"
DICTZIP_CHUNK = 58315
MAX_CHUNKS = 8192
MAX_HEADWORD_BYTES = 200
MAX_DEFINITION_BYTES = 60000

# ---------------------------------------------------------------------------
# Helpers & normalization
# ---------------------------------------------------------------------------

def ascii_lower_bytes(b: bytes) -> bytes:
    """Mirror CrossPoint StringUtils::asciiCaseCmp byte folding (ASCII A-Z -> a-z)."""
    return bytes(c + 32 if 65 <= c <= 90 else c for c in b)


def fix_mojibake(s: str) -> str:
    if not s:
        return ""
    if "Ã" in s or "Â" in s or "â" in s:
        try:
            return s.encode("latin1").decode("utf-8")
        except Exception:
            pass
    return s


def norm_pos(p: str | None) -> str:
    p = (p or "").lower().strip().rstrip(".")
    if p in ("n", "noun", "n.bot", "n.zool", "proper noun", "name", "n.pl", "pl.n"):
        return "noun"
    if p in ("v", "verb", "v.inf", "v.t", "v.i", "vt", "vi", "auxiliary verb", "modal verb", "phrasal verb"):
        return "verb"
    if p in ("adj", "adjective", "a", "s"):
        return "adjective"
    if p in ("adv", "adverb", "r"):
        return "adverb"
    if p in ("prep", "preposition"):
        return "preposition"
    if p in ("conj", "conjunction"):
        return "conjunction"
    if p in ("pron", "pronoun"):
        return "pronoun"
    if p in ("intrj", "interj", "interjection", "exclamation"):
        return "exclamation"
    if p in ("det", "determiner", "art", "article", "indefinite article", "definite article"):
        return "determiner"
    if p in ("num", "number", "numeral"):
        return "number"
    return p or "other"


def pos_bucket(pos: str) -> str:
    if pos in ("noun", "verb", "adjective", "adverb"):
        return pos
    return "other"


UK_US_PAIRS = [
    ("our", "or"),
    ("ise", "ize"),
    ("yse", "yze"),
    ("tre", "ter"),
    ("ogue", "og"),
    ("ae", "e"),
    ("oe", "e"),
    ("ll", "l"),
]

UK_US_EXACT = {
    "tyre": "tire",
    "tire": "tyre",
    "grey": "gray",
    "gray": "grey",
    "cheque": "check",
    "programme": "program",
    "plough": "plow",
    "kerb": "curb",
    "storey": "story",
    "sceptical": "skeptical",
    "skeptical": "sceptical",
    "pyjamas": "pajamas",
    "pajamas": "pyjamas",
    "mum": "mom",
    "aluminium": "aluminum",
    "artifact": "artefact",
    "artefact": "artifact",
    "draught": "draft",
    "gaol": "jail",
    "jewellery": "jewelry",
    "jewelry": "jewellery",
    "marvellous": "marvelous",
    "travelled": "traveled",
    "travelling": "traveling",
    "cancelled": "canceled",
    "cancelling": "canceling",
    "counselling": "counseling",
    "counsellor": "counselor",
    "labelling": "labeling",
    "labelled": "labeled",
    "modelling": "modeling",
    "modelled": "modeled",
    "fulfil": "fulfill",
    "skilful": "skillful",
    "wilful": "willful",
    "enrol": "enroll",
    "instalment": "installment",
    "defence": "defense",
    "offence": "offense",
    "licence": "license",
    "practice": "practise",
    "practise": "practice",
    "pretence": "pretense",
    "realise": "realize",
    "realize": "realise",
    "organise": "organize",
    "organize": "organise",
    "recognise": "recognize",
    "recognize": "recognise",
    "analyse": "analyze",
    "analyze": "analyse",
    "criticise": "criticize",
    "criticize": "criticise",
    "emphasise": "emphasize",
    "emphasize": "emphasise",
    "apologise": "apologize",
    "apologize": "apologise",
    "characterise": "characterize",
    "characterize": "characterise",
    "colour": "color",
    "color": "colour",
    "flavour": "flavor",
    "flavor": "flavour",
    "favour": "favor",
    "favor": "favour",
    "honour": "honor",
    "honor": "honour",
    "humour": "humor",
    "humor": "humour",
    "labour": "labor",
    "labor": "labour",
    "neighbour": "neighbor",
    "neighbor": "neighbour",
    "behaviour": "behavior",
    "behavior": "behaviour",
    "rumour": "rumor",
    "rumor": "rumour",
    "splendour": "splendor",
    "vigour": "vigor",
    "centre": "center",
    "center": "centre",
    "theatre": "theater",
    "theater": "theatre",
    "metre": "meter",
    "litre": "liter",
    "fibre": "fiber",
    "sombre": "somber",
    "catalogue": "catalog",
    "dialogue": "dialog",
    "monologue": "monolog",
    "prolog": "prologue",
    "encyclopaedia": "encyclopedia",
    "mediaeval": "medieval",
    "manoeuvre": "maneuver",
    "paediatric": "pediatric",
    "oestrogen": "estrogen",
    "diarrhoea": "diarrhea",
}


def uk_us_variants(w: str) -> list[str]:
    res = [w]
    if w in UK_US_EXACT:
        res.append(UK_US_EXACT[w])
    for a, b in UK_US_PAIRS:
        if a in w:
            res.append(w.replace(a, b))
        if b in w:
            res.append(w.replace(b, a))
    return list(dict.fromkeys(v for v in res if v))


# Standard Tagalog equivalents for core Oxford 5000 function/modern words and
# tricky high-frequency words where reverse glossaries lack exact POS matches.
CORE_POS_TRANSLATIONS: dict[tuple[str, str], list[str]] = {
    ("the", "determiner"): ["ang", "si", "mga"],
    ("a", "determiner"): ["isang"],
    ("an", "determiner"): ["isang"],
    ("could", "verb"): ["maaari", "puwede", "nakaya"],
    ("would", "verb"): ["gagawin sana", "nais"],
    ("should", "verb"): ["dapat", "nararapat"],
    ("shall", "verb"): ["dapat", "gagawin"],
    ("might", "verb"): ["maaari", "baka"],
    ("must", "verb"): ["kailangan", "dapat"],
    ("have to", "verb"): ["kailangan"],
    ("unable", "adjective"): ["hindi kaya", "walang kakayahan"],
    ("homeless", "adjective"): ["walang tirahan", "palaboy"],
    ("achieve", "verb"): ["matamo", "makamit", "maisakatuparan"],
    ("belong", "verb"): ["mapabilang", "pag-aari", "nauukol"],
    ("consist", "verb"): ["binubuo ng", "kinapapalooban"],
    ("tire", "noun"): ["gulong", "goma"],
    ("tyre", "noun"): ["gulong", "goma"],
    ("albeit", "conjunction"): ["bagaman", "kahit na"],
    ("amid", "preposition"): ["sa gitna ng"],
    ("anywhere", "adverb"): ["kahit saan", "saanman"],
    ("elsewhere", "adverb"): ["sa ibang lugar"],
    ("additionally", "adverb"): ["bukod pa rito", "dagdag pa"],
    ("explicitly", "adverb"): ["nang malinaw", "tahasan"],
    ("hurricane", "noun"): ["malakas na bagyo", "buhawi"],
    ("cent", "noun"): ["sentimo"],
    ("euro", "noun"): ["euro"],
    ("acre", "noun"): ["ektreya (acre)"],
    ("county", "noun"): ["kondado", "lalawigan"],
    ("email", "noun"): ["e-mail", "sulatroniko"],
    ("email", "verb"): ["mag-email", "magpadala ng e-mail"],
    ("e-mail", "noun"): ["e-mail", "sulatroniko"],
    ("e-mail", "verb"): ["mag-email"],
    ("website", "noun"): ["website", "sayt sa web"],
    ("software", "noun"): ["sopwer", "programa sa kompyuter"],
    ("download", "verb"): ["i-download", "kunin mula sa internet"],
    ("download", "noun"): ["na-download na file"],
    ("app", "noun"): ["app", "aplikasyon"],
    ("blog", "noun"): ["blog"],
    ("blog", "verb"): ["mag-blog"],
    ("database", "noun"): ["database", "kalipunan ng datos"],
    ("fridge", "noun"): ["pridyider", "repridyereytor"],
    ("tv", "noun"): ["telebisyon", "TV"],
    ("consensus", "noun"): ["pinagkaisahan", "konsensus"],
    ("feedback", "noun"): ["puna", "tugon"],
    ("habitat", "noun"): ["likas na tirahan"],
    ("healthcare", "noun"): ["pangangalagang pangkalusugan"],
    ("genocide", "noun"): ["paglipol ng lahi"],
    ("genre", "noun"): ["uri", "henero"],
    ("globalization", "noun"): ["globalisasyon"],
    ("globalisation", "noun"): ["globalisasyon"],
    ("internet", "noun"): ["internet"],
    ("laptop", "noun"): ["laptop"],
    ("desktop", "noun"): ["desktop", "kompyuter na pang-mesa"],
    ("digital", "adjective"): ["dihital", "digital"],
    ("jeans", "noun"): ["maong", "pantalong maong"],
    ("laser", "noun"): ["laser"],
    ("audio", "noun"): ["tunog", "awdyo", "audio"],
    ("audio", "adjective"): ["pang-tunog", "awdyo"],
    ("graphics", "noun"): ["grapiko", "mga larawan"],
    ("interface", "noun"): ["ugnayan", "interface"],
    ("marketing", "noun"): ["pagmemerkado", "marketing"],
    ("marathon", "noun"): ["maraton", "karerang pampaligsahan"],
    ("elite", "noun"): ["mga piling tao", "elite"],
    ("elite", "adjective"): ["piling-pili", "mataas na uri"],
    ("entrepreneur", "noun"): ["negosyante", "entrepreneurs", "namumuhunan"],
    ("airline", "noun"): ["kompanya ng eroplano", "linya ng eroplano"],
    ("deserve", "verb"): ["karapat-dapat", "nararapat", "magkamit"],
    ("deem", "verb"): ["ituring", "isipin", "ipagpalagay"],
    ("enable", "verb"): ["paganahin", "pahintulutan", "gawing posible"],
    ("cater", "verb"): ["maghanda ng pagkain", "maglingkod"],
    ("haunt", "verb"): ["multuhin", "bagabagin", "madalas puntahan"],
    ("explicit", "adjective"): ["malinaw", "tahasan", "tiyak"],
    ("fabulous", "adjective"): ["kamangha-mangha", "kahanga-hanga"],
    ("feat", "noun"): ["dakilang gawa", "tagumpay"],
    ("insight", "noun"): ["malalim na pag-unawa", "pananaw"],
    ("likelihood", "noun"): ["posibilidad", "pagkakataon"],
    ("coastal", "adjective"): ["sa baybayin", "pambaybayin"],
    ("environmental", "adjective"): ["pangkapaligiran"],
    ("ecological", "adjective"): ["pang-ekolohiya", "pangkapaligiran"],
    ("competitive", "adjective"): ["mapagkumpitensya", "mahusay makipagtagisan"],
    ("accountability", "noun"): ["pananagutan"],
    ("availability", "noun"): ["pagiging handa", "pagkakaroon"],
    ("consistency", "noun"): ["pagkakapare-pareho", "katatagan"],
    ("breakthrough", "noun"): ["malaking tagumpay", "pambihirang pag-unlad"],
    ("casino", "noun"): ["kasino"],
    ("hockey", "noun"): ["hockey"],
    ("feminist", "noun"): ["peminista"],
    ("feminist", "adjective"): ["peminista"],
    ("interact", "verb"): ["makipag-ugnayan", "makihalubilo"],
    ("interaction", "noun"): ["pakikipag-ugnayan", "interaksyon"],
    ("interactive", "adjective"): ["interaktibo", "nagtutugunan"],
    ("divorced", "adjective"): ["diborsyado", "hiwalay sa asawa"],
    ("associated", "adjective"): ["kaugnay", "may kinalaman"],
    ("yeah", "exclamation"): ["oo", "sige"],
    ("ah", "exclamation"): ["ah", "aba"],
    ("ok", "exclamation"): ["sige", "ayos"],
    ("okay", "exclamation"): ["sige", "ayos"],
    ("bye", "exclamation"): ["paalam"],
    ("t-shirt", "noun"): ["t-shirt", "kamiseta"],
    ("wifi", "noun"): ["Wi-Fi", "wireless na internet"],
    ("broadband", "noun"): ["broadband", "mabilis na koneksyon sa internet"],
    ("footage", "noun"): ["bidyo", "kuha sa kamera"],
    ("benchmark", "noun"): ["pamantayan", "batayan"],
    ("deploy", "verb"): ["italaga", "ilagay sa pwesto"],
    ("deployment", "noun"): ["pagtatalaga"],
    ("flawed", "adjective"): ["may depekto", "may pagkakamali"],
    ("compelling", "adjective"): ["nakakahikayat", "kapani-paniwala"],
    ("constituency", "noun"): ["nasasakupan", "distrito"],
    ("bin", "noun"): ["basurahan", "sisidlan"],
    ("decision-making", "noun"): ["pagpapasya", "paggawa ng desisyon"],
    ("film-maker", "noun"): ["gumagawa ng pelikula", "direktor"],
    ("full-time", "adjective"): ["buong oras", "full-time"],
    ("full-time", "adverb"): ["nang buong oras"],
    ("high-profile", "adjective"): ["kilala", "tanyag"],
    ("fundraising", "noun"): ["paglikom ng pondo"],
    ("sometime", "adverb"): ["balang araw", "minsan"],
    ("thereafter", "adverb"): ["pagkatapos noon"],
    ("whatsoever", "adverb"): ["kahit ano pa man"],
    ("wherever", "conjunction"): ["saanman", "kahit saan"],
    ("whilst", "conjunction"): ["habang", "samantalang"],
}

# ---------------------------------------------------------------------------
# Tagalog root/stem & parallel sentence corpus
# ---------------------------------------------------------------------------

TGL_PREFIXES = (
    "nakikipag", "makikipag", "pinakama", "pinapag", "pinagpa",
    "nagpapa", "magpapa", "ipagpa", "ipakita", "nakaka", "makaka",
    "nagkaka", "magkaka", "pagkaka", "napapa", "mapapa",
    "nagpa", "magpa", "pinag", "naka", "maka", "naki", "maki",
    "nang", "mang", "pang", "paki", "pag", "nag", "mag", "ipa",
    "pin", "na", "ma", "ka", "pa", "ni", "in", "um", "i",
)


def tgl_stems(word: str) -> set[str]:
    """Generate likely Tagalog root stems for sentence alignment matching."""
    w = word.lower().strip("-' ")
    if len(w) < 3:
        return {w} if w else set()
    stems = {w}
    # Strip infix -um- / -in- after initial consonant(s)
    for m_infix in ("um", "in"):
        if len(w) > 4 and w[1:3] == m_infix:
            stems.add(w[0] + w[3:])
    # Strip common prefixes (only yield >= 4-char roots to avoid spurious short hits)
    for pref in TGL_PREFIXES:
        if w.startswith(pref) and len(w) - len(pref) >= 4:
            r = w[len(pref):]
            stems.add(r)
            # Handle CV reduplication like nagbabasa -> basa, tumatakbo -> takbo
            if len(r) >= 6 and r[:2] == r[2:4]:
                stems.add(r[2:])
    # Also strip trailing -in / -an / -hin / -han
    for suf in ("hin", "han", "in", "an"):
        for base in list(stems):
            if base.endswith(suf) and len(base) - len(suf) >= 4:
                stems.add(base[:-len(suf)])
    return stems


def load_parallel_corpus(sources_dir: Path):
    """Load and deduplicate clean English-Tagalog parallel sentences."""
    raw = []

    tatoeba_files = sorted(
        glob.glob(str(sources_dir / "Tatoeba-Challenge/data/*/eng-tgl/*.txt"))
        + glob.glob(str(sources_dir / "Tatoeba-Challenge/data/release/*/*/*eng-tgl*.gz"))
    )
    for p in tatoeba_files:
        op = gzip.open if p.endswith(".gz") else open
        with op(p, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                cols = line.rstrip("\n").split("\t")
                if len(cols) >= 4:
                    e = fix_mojibake(cols[2].strip())
                    t = fix_mojibake(cols[3].strip())
                    raw.append((0, "tatoeba", e, t))

    lt_path = sources_dir / "LearnTagalogApp/app.js"
    if lt_path.exists():
        txt = lt_path.read_text(encoding="utf-8", errors="replace")
        for e, t in re.findall(r'english:\s*"([^"]+)",\s*tagalog:\s*"([^"]+)"', txt):
            raw.append((0, "learntagalog", e.strip(), t.strip()))

    for split in ("train", "val", "test"):
        fe_p = sources_dir / f"nmt-eng-tgl/data/FloRes200/{split}_eng_inputs.txt"
        ft_p = sources_dir / f"nmt-eng-tgl/data/FloRes200/{split}_tgl_labels.txt"
        if fe_p.exists() and ft_p.exists():
            with fe_p.open(encoding="utf-8", errors="replace") as fe, ft_p.open(
                encoding="utf-8", errors="replace"
            ) as ft:
                for e, t in zip(fe, ft):
                    raw.append((1, "flores", fix_mojibake(e.strip()), fix_mojibake(t.strip())))

    kjv_p = sources_dir / "Digi-bible/assets/bible/kjv.verses.json"
    adb_p = sources_dir / "Digi-bible/assets/bible/adb.verses.json"
    if kjv_p.exists() and adb_p.exists():
        kjv = {(v["book"], v["chapter"], v["verse"]): v["text"].strip() for v in json.loads(kjv_p.read_text())}
        adb = {(v["book"], v["chapter"], v["verse"]): v["text"].strip() for v in json.loads(adb_p.read_text())}
        for k, e in kjv.items():
            if k in adb:
                raw.append((3, "bible", e, adb[k]))

    raw.sort(key=lambda x: x[0])
    seen_en = set()
    pairs: list[tuple[int, str, str, str]] = []
    for prio, src, e, t in raw:
        e = re.sub(r"\s+", " ", e).strip()
        t = re.sub(r"\s+", " ", t).strip()
        if not e or not t:
            continue
        if len(e) < 10 or len(e) > 260 or len(t) < 10 or len(t) > 300:
            continue
        # Reject bracket-only/garbled lines or replacement char
        if e.count("[") > 1 or t.count("[") > 1 or "\ufffd" in e or "\ufffd" in t:
            continue
        # Reject untranslated Taglish / identical copycat pairs (e.g. tabloid English copied into TL)
        e_toks = re.findall(r"[a-z]+", e.lower())
        t_toks = re.findall(r"[a-z]+", t.lower())
        if len(e_toks) >= 4 and len(t_toks) >= 4:
            overlap = len(set(e_toks) & set(t_toks)) / max(1, min(len(set(e_toks)), len(set(t_toks))))
            if overlap > 0.55:
                continue
        # Reject headline-style Title-Cased spam in M2M100/FloRes
        if prio >= 1:
            words_e = e.split()
            if len(words_e) >= 6 and sum(1 for w in words_e if w[0].isupper()) > len(words_e) * 0.65:
                continue
        key = e.lower()
        if key in seen_en:
            continue
        seen_en.add(key)
        pairs.append((prio, src, e, t))

    en_index: dict[str, list[int]] = defaultdict(list)
    tl_index: dict[str, list[int]] = defaultdict(list)
    tl_stem_index: dict[str, list[int]] = defaultdict(list)
    pair_en_tokens: list[set[str]] = []
    pair_tl_stems: list[set[str]] = []

    for idx, (prio, src, e, t) in enumerate(pairs):
        etoks = set(re.findall(r"[a-z']+", e.lower()))
        ttoks = set(re.findall(r"[a-z\u00C0-\u024F'-]+", t.lower()))
        tstems: set[str] = set()
        for tok in ttoks:
            tstems.update(tgl_stems(tok))
        pair_en_tokens.append(etoks)
        pair_tl_stems.append(tstems)
        for tok in etoks:
            if len(en_index[tok]) < 30:
                en_index[tok].append(idx)
        for tok in ttoks:
            if len(tl_index[tok]) < 25:
                tl_index[tok].append(idx)
        for st in tstems:
            if len(st) >= 4 and len(tl_stem_index[st]) < 25:
                tl_stem_index[st].append(idx)

    return pairs, en_index, tl_index, tl_stem_index, pair_en_tokens, pair_tl_stems


# ---------------------------------------------------------------------------
# WordNet & Tagalog lexicon engine
# ---------------------------------------------------------------------------

LOW_TAGS_RE = re.compile(
    r"\b(slang|archaic|obsolete|dated|vulgar|offensive|derogatory|humorous|dialectal|"
    r"regional|colloquial|rare|uncommon|nonstandard|Batangas|Marinduque|Quezon|Bulacan|"
    r"Laguna|Rizal|Cavite|Bataan|Nueva Ecija|Tarlac|Pampanga|Zambales|Aurora|Mindoro|"
    r"Romblon|Palawan|derog|jocular|facetious|euphemistic)\b",
    re.I,
)
META_DEF_RE = re.compile(
    r"^(Alternative|Contraction|Abbreviation|Initialism|Synonym|Antonym|Inflection|"
    r"Complete aspect|Progressive aspect|Contemplative aspect|Contemplated aspect|"
    r"Imperative|Past tense|Plural|Diminutive|Augmentative|Variant|Archaic|Obsolete|"
    r"Dated|Misspelling|Clipping|Shortening|Ellipsis|Eye dialect|Syncopic form)\b",
    re.I,
)
NEG_PHRASE_RE = re.compile(
    r"\b(lack of|absence of|without|not |non-|incapable of|opposite of|free from|devoid of)\b",
    re.I,
)


def load_wordnet(sources_dir: Path):
    wn_zip = sources_dir / "nltk_data/packages/corpora/wordnet.zip"
    wn_syn: dict[str, tuple[str, list[str], list[str], bool]] = {}
    wn_word_sids: dict[str, list[str]] = defaultdict(list)
    wn_pert_adj: dict[str, list[str]] = defaultdict(list)
    wn_rel_sids: dict[str, list[str]] = defaultdict(list)  # '@' hypernyms & '&' similar-to
    wn_exc: dict[str, set[str]] = defaultdict(set)  # base -> {inflected forms}

    pos_map = {"1": "noun", "2": "verb", "3": "adjective", "4": "adverb"}
    pos_sym = {"n": "1", "v": "2", "a": "3", "s": "3", "r": "4"}
    with zipfile.ZipFile(wn_zip) as z:
        for fn in ("wordnet/noun.exc", "wordnet/verb.exc", "wordnet/adj.exc", "wordnet/adv.exc"):
            for line in z.read(fn).decode("utf-8", errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    infl = parts[0].replace("_", " ").lower()
                    for base in parts[1:]:
                        wn_exc[base.replace("_", " ").lower()].add(infl)

        for num, fn in (
            ("1", "wordnet/data.noun"),
            ("2", "wordnet/data.verb"),
            ("3", "wordnet/data.adj"),
            ("4", "wordnet/data.adv"),
        ):
            for line in z.read(fn).decode("utf-8", errors="replace").splitlines():
                if not line or line.startswith(" "):
                    continue
                sid = num + line[:8]
                parts = line.split("|")
                gloss = parts[1].strip() if len(parts) > 1 else ""
                examples = [ex.strip() for ex in re.findall(r'"([^"]+)"', gloss) if len(ex.strip()) >= 10]
                meta = parts[0].split()
                w_cnt = int(meta[3], 16)
                raw_lemmas = [meta[4 + 2 * i].replace("_", " ") for i in range(w_cnt)]
                words = [
                    re.sub(r"\([^)]*\)", "", rl).strip().lower()
                    for rl in raw_lemmas
                ]
                idx = 4 + 2 * w_cnt
                p_cnt = int(meta[idx])
                ptr_idx = idx + 1
                is_proper = bool(raw_lemmas and all(rl[0].isupper() for rl in raw_lemmas))
                for pi in range(p_cnt):
                    ptr_sym = meta[ptr_idx + 4 * pi]
                    tsid_num = pos_sym.get(meta[ptr_idx + 4 * pi + 2], "")
                    tsid = tsid_num + meta[ptr_idx + 4 * pi + 1]
                    if ptr_sym == "@i":
                        is_proper = True
                    elif ptr_sym in ("@", "&") and tsid_num:
                        wn_rel_sids[sid].append(tsid)
                    elif num == "4" and ptr_sym == "\\" and tsid_num:
                        wn_pert_adj[sid].append(tsid)
                wn_syn[sid] = (pos_map[num], words, examples, is_proper)
                for w in words:
                    wn_word_sids[w].append(sid)

    return wn_syn, wn_word_sids, wn_pert_adj, wn_rel_sids, wn_exc


def build_tagalog_translator(sources_dir: Path, wn_syn, wn_word_sids, wn_pert_adj, wn_rel_sids, pairs, en_index, pair_tl_stems):
    tgl_freq: dict[str, int] = {}
    with (sources_dir / "tgl-dictionary-parser/output/tgl_freqlist.csv").open(
        encoding="utf-8", errors="replace"
    ) as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[1].isdigit():
                tgl_freq[row[0].lower()] = int(row[1])

    # scores[(eng, pos_bucket)][tw] = best_score
    scores: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    # Track explicit low-quality tags (vulgar/offensive) per (ew, tw)
    bad_pairs: set[tuple[str, str]] = set()

    def add_cand(ew: str, pos: str, tw: str, base_score: float, is_vulgar: bool = False):
        ew = ew.strip().lower()
        tw = re.sub(r"\s+", " ", tw).strip()
        if not ew or not tw or len(tw) > 45 or len(ew) > 45:
            return
        if any(0x1700 <= ord(c) <= 0x171F for c in tw):  # skip Baybayin script
            return
        if is_vulgar:
            bad_pairs.add((ew, tw.lower()))
            return
        f = tgl_freq.get(tw.lower(), 0)
        tot = base_score + math.log1p(f) * 0.65
        pb = pos_bucket(pos)
        if tot > scores[(ew, pb)][tw]:
            scores[(ew, pb)][tw] = tot

    def process_gloss(tw: str, pos_raw: str | None, defn: str | None, src_w: float, sense_idx: int = 0):
        if not defn or META_DEF_RE.match(defn.strip()):
            return
        pos = norm_pos(pos_raw)
        low_match = LOW_TAGS_RE.search(defn)
        is_vulgar = bool(re.search(r"\b(vulgar|offensive|profane)\b", defn, re.I))
        low_pen = -5.0 if low_match else 0.0

        d = re.sub(r"^\s*(?:n|v|adj|adv|prep|conj|pron|intrj|v\.inf)\.\s*", "", defn.strip(), flags=re.I)
        d = re.sub(r"\([^)]*\)", "", d)
        d = re.sub(r"\[[^\]]*\]", "", d)
        semi_parts = [p.strip().rstrip(".!").strip() for p in d.split(";") if p.strip()]
        for pi, part in enumerate(semi_parts):
            if NEG_PHRASE_RE.search(part):
                continue
            comma_parts = [sp.strip() for sp in part.split(",") if sp.strip()]
            for sp in comma_parts:
                c = sp.lower()
                c = re.sub(r"^(?:to be |to |a |an |the )+", "", c).strip()
                c2 = re.sub(r"\s+(?:to|of|with|from|for|in|on|at|by|into|upon)$", "", c).strip()
                for ci, cand in enumerate(dict.fromkeys([c, c2])):
                    if not cand or len(cand.split()) > 3 or not re.match(r"^[a-z][a-z\s'-]*$", cand):
                        continue
                    spec = 4.0 if (len(semi_parts) == 1 and len(comma_parts) == 1) else (3.0 if pi == 0 else 2.0)
                    if len(cand.split()) == 1:
                        spec += 1.0
                    if ci == 1:
                        spec -= 0.4
                    sense_pen = min(2.0, sense_idx * 0.4)
                    add_cand(cand, pos, tw, src_w + spec - sense_pen + low_pen, is_vulgar=is_vulgar)

    # 1. Filipino-WordNet (matched to WordNet 3.0 synsets)
    with (sources_dir / "Filipino-WordNet/filwordnet.csv").open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            sid = row["synsetid"].zfill(9)
            if sid in wn_syn:
                wpos, words, _, is_proper = wn_syn[sid]
                if is_proper:
                    continue
                tw = row["lemma"].strip()
                # Skip suspicious single-char or untranslated English copies not attested in Tagalog corpus
                if len(tw) < 2:
                    continue
                for idx, ew in enumerate(words):
                    if len(ew) >= 4 and len(tw) <= 2:
                        continue
                    if tw.lower() == ew.lower() and tgl_freq.get(tw.lower(), 0) < 5:
                        continue
                    add_cand(ew, wpos, tw, 4.3 if idx == 0 else 3.3)

    # 2. English-Tagalog Vocab
    etv_path = sources_dir / "english-tagalog-vocab/vocabulary.json"
    if etv_path.exists():
        for it in json.loads(etv_path.read_text(encoding="utf-8", errors="replace")):
            for tw in re.split(r"[,;/]", it["tagalog"]):
                if tw.strip():
                    add_cand(it["english"], "other", tw.strip(), 5.0)

    # 3. LearnTagalogApp short vocabulary entries
    lt_path = sources_dir / "LearnTagalogApp/app.js"
    if lt_path.exists():
        for e, t in re.findall(r'english:\s*"([^"]+)",\s*tagalog:\s*"([^"]+)"', lt_path.read_text(errors="replace")):
            if len(e.split()) <= 3 and len(t.split()) <= 4:
                add_cand(e, "other", t, 4.5)

    # 4. PinoyDictionary (tgl_dictionary.json)
    tgl_d_path = sources_dir / "tgl-dictionary-parser/output/tgl_dictionary.json"
    for entry in json.loads(tgl_d_path.read_text(encoding="utf-8", errors="replace")):
        tw = entry["word"].strip()
        for idx, attr in enumerate(entry.get("attributes", [])):
            process_gloss(tw, attr.get("pos"), attr.get("definition"), 4.6, idx)

    # 5. PinoyDictionary (tagalog_dictionary.json, numbered sense splitting)
    tgl_d2_path = sources_dir / "pinoy-dictionary-scraper/Scraped Data/Dictionaries/tagalog_dictionary.json"
    for entry in json.loads(tgl_d2_path.read_text(encoding="utf-8", errors="replace")):
        tw = entry["word"].strip()
        d = entry.get("definition") or ""
        m = re.match(r"^([a-z\.]+)\s+(.*)$", d.strip())
        pos_r, rest = (m.group(1), m.group(2)) if m and "." in m.group(1) else ("", d)
        senses = [x for x in re.split(r"(?:^|\s)\d+\.\s+", rest) if x.strip()]
        for idx, s in enumerate(senses):
            process_gloss(tw, pos_r, s, 4.0, idx)

    # 6. Wiktionary Tagalog-English
    wikt_path = sources_dir / "Wiktionary-Dictionaries/Tagalog-English Wiktionary dictionary.tsv"
    with wikt_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if "\t" not in line:
                continue
            head, body = line.split("\t", 1)
            tw = head.split("|")[0].strip()
            sections = re.split(r"<i>([^<]+)</i>", body)
            for i in range(1, len(sections), 2):
                pos_r = sections[i]
                sec_body = sections[i + 1] if i + 1 < len(sections) else ""
                for idx, li in enumerate(re.findall(r"<li>(.*?)</li>", sec_body)):
                    process_gloss(tw, pos_r, re.sub(r"<[^>]+>", "", li).strip(), 4.9, idx)

    # Group by English word for fast lookup
    by_word: dict[str, list[tuple[str, dict[str, float]]]] = defaultdict(list)
    for (w, p), tws in scores.items():
        by_word[w].append((p, tws))

    def cooccur_boost(ew: str, tw: str) -> float:
        sent_ids = en_index.get(ew, [])
        if not sent_ids:
            return 0.0
        tw_parts = tw.lower().split()
        tw_key = tw_parts[-1] if tw_parts else tw.lower()
        stems = tgl_stems(tw_key)
        hits = 0
        for sid in sent_ids[:20]:
            if stems & pair_tl_stems[sid]:
                hits += 1
        return min(3.5, hits * 1.1)

    def translate(ew: str, pos: str = "", limit: int = 4, strict_pos: bool = False, meaning: str = "") -> list[str]:
        ew_l = ew.strip().lower()
        target_pb = pos_bucket(pos) if pos else ""
        meaning_toks = set(re.findall(r"[a-z]{3,}", (meaning or "").lower()))

        # Check audited core function/modern/POS words first
        for v in uk_us_variants(ew_l):
            if (v, pos) in CORE_POS_TRANSLATIONS:
                return CORE_POS_TRANSLATIONS[(v, pos)][:limit]
            if target_pb and (v, target_pb) in CORE_POS_TRANSLATIONS:
                return CORE_POS_TRANSLATIONS[(v, target_pb)][:limit]

        cand: dict[str, tuple[float, bool]] = {}

        def collect_from(word_key: str, penalty: float = 0.0, force_strict: bool = False):
            for p, tws in by_word.get(word_key, []):
                if target_pb and target_pb != "other":
                    if p == target_pb:
                        pb_bonus = 2.8
                        matched_pos = True
                    elif p == "other":
                        if force_strict or strict_pos:
                            continue
                        pb_bonus = -0.8
                        matched_pos = False
                    else:
                        if force_strict or strict_pos:
                            continue
                        pb_bonus = -6.0
                        matched_pos = False
                else:
                    pb_bonus = 0.5
                    matched_pos = True
                for tw, sc in tws.items():
                    if (word_key, tw.lower()) in bad_pairs:
                        continue
                    total = sc + pb_bonus - penalty
                    prev_sc, prev_mp = cand.get(tw, (-1e9, False))
                    if total > prev_sc:
                        cand[tw] = (total, matched_pos or prev_mp)

        for v in uk_us_variants(ew_l):
            collect_from(v, 0.0 if v == ew_l else 0.3)

        # Fallback 1: WordNet same-POS synset mate (strictly monosemous non-gerund OR literally used in Oxford's definition!)
        abstract_mates = {
            "group", "type", "kind", "sort", "way", "part", "form", "state",
            "act", "action", "thing", "person", "place", "system", "unit",
            "device", "tool", "object", "material", "substance", "process",
            "quality", "area", "body", "set", "class", "member",
        }
        if not cand:
            for v in uk_us_variants(ew_l):
                for sid in wn_word_sids.get(v, []):
                    spos, mates, _, is_proper = wn_syn[sid]
                    if is_proper:
                        continue
                    if target_pb and target_pb != "other" and spos != target_pb:
                        continue
                    for m in mates:
                        if m == v or " " in m or m in abstract_mates:
                            continue
                        m_sids = wn_word_sids.get(m, [])
                        mono_ok = len(m_sids) == 1 and not (m.endswith("ing") and not ew_l.endswith("ing"))
                        if mono_ok or (len(m) >= 3 and m in meaning_toks):
                            collect_from(m, 2.2, force_strict=bool(target_pb and target_pb != "other"))

        # Fallback 1B: WordNet @ hypernym / & similar-to ONLY for Oxford 5000 headwords when a concrete mate appears in Oxford's definition
        if not cand and not strict_pos and meaning_toks:
            for v in uk_us_variants(ew_l):
                for sid in wn_word_sids.get(v, []):
                    spos, _, _, is_proper = wn_syn[sid]
                    if is_proper:
                        continue
                    if target_pb and target_pb != "other" and spos != target_pb:
                        continue
                    for rsid in wn_rel_sids.get(sid, []):
                        if rsid in wn_syn:
                            rspos, rmates, _, ris_proper = wn_syn[rsid]
                            if ris_proper:
                                continue
                            if target_pb and target_pb != "other" and rspos != target_pb:
                                continue
                            for m in rmates:
                                if (
                                    m != v
                                    and " " not in m
                                    and len(m) >= 3
                                    and m not in abstract_mates
                                    and m in meaning_toks
                                ):
                                    collect_from(m, 2.8, force_strict=bool(target_pb and target_pb != "other"))

        # Fallback 2: WordNet adverb -> adjective pertainym ('nang ' + adj)
        if not cand and target_pb == "adverb":
            for v in uk_us_variants(ew_l):
                for sid in wn_word_sids.get(v, []):
                    for tsid in wn_pert_adj.get(sid, []):
                        if tsid in wn_syn:
                            for m in wn_syn[tsid][1]:
                                for p, tws in by_word.get(m, []):
                                    if p in ("adjective", "other"):
                                        for tw, sc in tws.items():
                                            if (m, tw.lower()) in bad_pairs:
                                                continue
                                            adv_tw = tw if tw.lower().startswith("nang ") else f"nang {tw}"
                                            val = sc - 2.6
                                            prev_sc, prev_mp = cand.get(adv_tw, (-1e9, False))
                                            if val > prev_sc:
                                                cand[adv_tw] = (val, True)

        if not cand and not strict_pos:
            for (cw, cpos), cvals in CORE_POS_TRANSLATIONS.items():
                if cw == ew_l:
                    return cvals[:limit]

        if not cand:
            return []

        # Re-rank top 12 candidates with parallel corpus co-occurrence boost (only when POS matches)
        top_pre = sorted(cand.items(), key=lambda x: -x[1][0])[:12]
        reranked = []
        for tw, (sc, matched_pos) in top_pre:
            boost = cooccur_boost(ew_l, tw) if matched_pos else 0.0
            reranked.append((tw, sc + boost))
        reranked.sort(key=lambda x: -x[1])

        best_sc = reranked[0][1]
        out: list[str] = []
        seen: set[str] = set()
        for tw, sc in reranked:
            if out and sc < best_sc - 4.5:
                break
            tl = tw.lower()
            if tl not in seen:
                seen.add(tl)
                out.append(tw)
            if len(out) >= limit:
                break
        return out

    return translate


# ---------------------------------------------------------------------------
# Oxford English sources + Wordset/WordNet example fallback
# ---------------------------------------------------------------------------

def clean_oxford_example(raw_ex: str, word: str) -> str:
    s = re.sub(r"\s+", " ", (raw_ex or "")).strip()
    if not s:
        return ""
    # Strip Oxford grammar pattern prefix like "abandon somebody, The baby..." or "abandon somebody The baby..."
    # Detect if prefix before first sentence-starting capital or comma is a pattern containing somebody/something/yourself/one's
    m = re.match(r"^[a-z0-9\s'’/()-]*\b(?:somebody|something|yourself|oneself|one's)\b[^,]*,\s*(.+)$", s)
    if m:
        s = m.group(1).strip()
    else:
        m2 = re.match(r"^[a-z0-9\s'’/()-]*\b(?:somebody|something|yourself|oneself|one's)\b[^.!?]*?\s+([A-Z‘\"].+)$", s)
        if m2:
            s = m2.group(1).strip()
    # Skip fragment collocations like "a man/horse/unit" unless no full sentence exists
    return s


def is_full_sentence(s: str) -> bool:
    return bool(s and len(s) >= 12 and s[0].isupper() and s[-1] in ".!?\"’”" and "/" not in s[:25])


def clean_oed_definition(raw_def: str) -> list[tuple[str, str]]:
    """Split an OED body string into [(pos, cleaned_definition), ...]."""
    d = raw_def.split("\x7f", 1)[0].strip()
    # Strip trailing [etymology] and trailing derivative tails
    d = re.sub(r"\s*\[[^\]]+\]\s*$", "", d).strip()
    d = re.sub(r"\s{2,}[A-Za-z-]+\s+(?:n|v|adj|adv)\.(?:\s+[A-Za-z-]+\s+(?:n|v|adj|adv)\.)*\s*$", "", d)
    d = re.sub(r"\s+", " ", d).strip()
    if not d:
        return []

    sections: list[tuple[str, str]] = []
    parts = re.split(
        r"(?:^|\s)—\s*((?:n|v|adj|adv|prep|conj|pron|int|intrj|pl|abbr|pref|suff|comb|v\.t|v\.i)\.(?:\s*&\s*(?:n|v|adj|adv)\.)?)\s+",
        d,
    )
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            pos_raw = parts[i].split("&")[0].strip()
            body = parts[i + 1] if i + 1 < len(parts) else ""
            if body.strip():
                sections.append((norm_pos(pos_raw), body.strip()))
    else:
        m = re.match(
            r"^(?:(?:Predic\.|Attrib\.|Colloq\.)\s+)?(Adj\.|n\.|v\.|adj\.|adv\.|prep\.|conj\.|pron\.|int\.|intrj\.|v\.t\.|v\.i\.|n\.pl\.|pl\.n\.)\s+(.*)$",
            d,
            re.I,
        )
        if m:
            sections.append((norm_pos(m.group(1)), m.group(2).strip()))
        else:
            # Skip broken compound sub-entries like "Age n. Age-range..."
            if re.match(r"^[A-Za-z-]+\s+(?:n|v|adj|adv)\.\s+", d):
                return []
            sections.append(("other", d))

    cleaned: list[tuple[str, str]] = []
    for pos, body in sections:
        body = re.sub(r"^(?:\([^)]{1,55}\)\s*)+", "", body).strip()
        body = re.sub(r"\.\s+[B-F]\s+(?=[a-z])", "; ", body)
        body = re.sub(r"\bfoll\.\s+by\b", "followed by", body, flags=re.I)
        body = re.sub(r"\busu\.(?=\s|$)", "usually", body, flags=re.I)
        body = re.sub(r"\besp\.(?=\s|$)", "especially", body, flags=re.I)
        if len(body) > 420:
            cut = body.rfind(".", 0, 400)
            if cut > 120:
                body = body[: cut + 1]
            else:
                body = body[:397].rstrip() + "..."
        if body:
            body = body[0].upper() + body[1:]
            if body[-1] not in ".!?":
                body += "."
            cleaned.append((pos, body))
    return cleaned


def load_oxford_entries(sources_dir: Path):
    """
    Load Oxford 5000 + Concise OED (`sujithps` + `oedict.sql`), returning:
        entries: dict[headword_lower, list[dict(pos, cefr, meaning, examples)]]
    """
    entries: dict[str, list[dict]] = defaultdict(list)

    # 1. Load Oxford-5000-words/full-word.json for clean full-sentence examples
    fw_examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    fw_path = sources_dir / "Oxford-5000-words/full-word.json"
    if fw_path.exists():
        for item in json.loads(fw_path.read_text(encoding="utf-8", errors="replace")):
            val = item.get("value") or {}
            w = (val.get("word") or "").strip().lower()
            p = norm_pos(val.get("type"))
            for ex in val.get("examples") or []:
                ce = clean_oxford_example(ex, w)
                if ce:
                    fw_examples[(w, p)].append(ce)

    # 2. Load oxford_5000.csv (primary Learner's meanings & CEFR)
    ox5k_seen_pos: dict[str, set[str]] = defaultdict(set)
    ox5k_path = sources_dir / "oxford-5000-vocabulary-audio-definition/data/oxford_5000.csv"
    with ox5k_path.open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            w = (row.get("word") or "").strip().lower()
            if not w or not re.match(r"^[a-z][a-z0-9 '-]*$", w):
                continue
            pos = norm_pos(row.get("type"))
            cefr = (row.get("cefr") or "").strip().upper()
            defn = re.sub(r"\s+", " ", (row.get("definition") or "")).strip()
            if not defn:
                continue
            defn = defn[0].upper() + defn[1:]
            if defn[-1] not in ".!?":
                defn += "."

            ex_cands = list(fw_examples.get((w, pos), []))
            csv_ex = clean_oxford_example(row.get("example") or "", w)
            if csv_ex:
                ex_cands.append(csv_ex)
            # Pick best full sentence if available
            full_sents = [x for x in ex_cands if is_full_sentence(x)]
            best_ex = min(full_sents, key=lambda s: abs(len(s) - 65)) if full_sents else (ex_cands[0] if ex_cands else "")

            # Merge duplicate word+pos rows cleanly
            merged = False
            for existing in entries[w]:
                if existing["pos"] == pos:
                    if defn not in existing["meaning"] and len(existing["meaning"]) < 260:
                        existing["meaning"] = f"{existing['meaning']} {defn}"
                    if not existing["example"] and best_ex:
                        existing["example"] = best_ex
                    merged = True
                    break
            if not merged:
                entries[w].append(
                    {
                        "pos": pos,
                        "cefr": cefr,
                        "meaning": defn,
                        "example": best_ex,
                        "is_ox5k": True,
                    }
                )
                ox5k_seen_pos[w].add(pos)

    # 3. Load sujithps Oxford English Dictionary.txt + oedict.sql
    oed_raw: dict[str, list[str]] = defaultdict(list)
    suj_path = sources_dir / "sujithps-Dictionary/Oxford English Dictionary.txt"
    with suj_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^([A-Za-z][A-Za-z0-9 '-]*?)\s{2,}(.*)$", line)
            if not m:
                continue
            w = re.sub(r"\d+$", "", m.group(1).strip().lower()).strip()
            if not w or not re.match(r"^[a-z][a-z '-]*$", w) or w.endswith("-"):
                continue
            oed_raw[w].append(m.group(2).strip())

    sql_path = sources_dir / "Oxford-English-Dictionary-41K-words/oedict.sql"
    if sql_path.exists():
        txt = sql_path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\(\d+,\s*'[^']*',\s*'((?:[^']|'')*)',\s*'((?:[^']|'')*)'\)", txt):
            w = fix_mojibake(m.group(1).replace("''", "'").replace("\\r", "").replace("\\n", "").strip()).lower()
            w = re.sub(r"\d+$", "", w).strip()
            d = fix_mojibake(
                m.group(2).replace("''", "'").replace("\\r", " ").replace("\\n", " ").strip()
            )
            if not w or not re.match(r"^[a-z][a-z '-]*$", w) or w.endswith("-"):
                continue
            if w not in oed_raw:
                oed_raw[w].append(d)

    for w, raw_list in oed_raw.items():
        for raw_d in raw_list:
            for pos, defn in clean_oed_definition(raw_d):
                if pos in ox5k_seen_pos.get(w, set()):
                    continue
                if len(entries[w]) >= 3:
                    break
                if any(e["pos"] == pos for e in entries[w]):
                    continue
                entries[w].append(
                    {
                        "pos": pos,
                        "cefr": "",
                        "meaning": defn,
                        "example": "",
                        "is_ox5k": False,
                    }
                )

    return entries


def load_english_example_fallbacks(sources_dir: Path, wn_syn, wn_word_sids):
    """Load Wordset + WordNet English examples by (word, pos_bucket)."""
    ws_ex: dict[tuple[str, str], str] = {}
    for p in sorted(glob.glob(str(sources_dir / "wordset-dictionary/data/*.json"))):
        d = json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
        for w, info in d.items():
            wl = w.strip().lower()
            for m in info.get("meanings") or []:
                ex = (m.get("example") or "").strip()
                if ex and len(ex) >= 12:
                    if ex[-1] not in ".!?\"'":
                        ex += "."
                    ex = ex[0].upper() + ex[1:]
                    pb = pos_bucket(norm_pos(m.get("speech_part")))
                    if (wl, pb) not in ws_ex:
                        ws_ex[(wl, pb)] = ex
                    if (wl, "") not in ws_ex:
                        ws_ex[(wl, "")] = ex

    wn_ex: dict[tuple[str, str], str] = {}
    for w, sids in wn_word_sids.items():
        for sid in sids:
            spos, _, exs, is_proper = wn_syn[sid]
            if is_proper:
                continue
            if exs:
                ex = exs[0].strip()
                if ex and ex[-1] not in ".!?\"'":
                    ex += "."
                ex = ex[0].upper() + ex[1:]
                if (w, spos) not in wn_ex:
                    wn_ex[(w, spos)] = ex
                if (w, "") not in wn_ex:
                    wn_ex[(w, "")] = ex

    return ws_ex, wn_ex


# ---------------------------------------------------------------------------
# Example sentence selector (English + parallel Tagalog)
# ---------------------------------------------------------------------------

def english_inflections(w: str, pos: str, wn_exc: dict[str, set[str]]) -> list[str]:
    pb = pos_bucket(pos)
    forms = list(uk_us_variants(w))
    for base in list(forms):
        if pb == "noun":
            forms.extend(sorted(inf for inf in wn_exc.get(base, set()) if not inf.endswith(("ed", "ing"))))
            if base.endswith("y") and len(base) > 2 and base[-2] not in "aeiou":
                forms.append(base[:-1] + "ies")
            elif base.endswith(("s", "sh", "ch", "x", "z")):
                forms.append(base + "es")
            else:
                forms.append(base + "s")
        elif pb == "verb":
            forms.extend(sorted(wn_exc.get(base, set())))
            if base.endswith("y") and len(base) > 2 and base[-2] not in "aeiou":
                forms.extend([base[:-1] + "ies", base[:-1] + "ied"])
            if base.endswith("e"):
                forms.extend([base + "s", base + "d", base[:-1] + "ing"])
            else:
                forms.extend([base + "s", base + "es", base + "ed", base + "ing"])
        elif pb == "adjective":
            forms.extend(sorted(inf for inf in wn_exc.get(base, set()) if inf.endswith(("er", "est"))))
            if base.endswith("y") and len(base) > 2 and base[-2] not in "aeiou":
                forms.extend([base[:-1] + "ier", base[:-1] + "iest"])
            elif base.endswith("e"):
                forms.extend([base + "r", base + "st"])
            else:
                forms.extend([base + "er", base + "est"])
    return list(dict.fromkeys(forms))


TGL_STOPWORDS = {
    "ang", "ng", "mga", "sa", "na", "ay", "at", "ni", "si", "kay", "kina",
    "para", "kung", "pag", "nang", "wala", "walang", "hindi", "di", "may",
    "mayroon", "ito", "iyan", "iyon", "dito", "doon", "rito", "roon", "noon",
    "ngayon", "siya", "niya", "kanya", "kaniya", "sila", "nila", "kami",
    "tayo", "ako", "ikaw", "ka", "mo", "ko", "akin", "iyong", "aming", "ating",
    "kanila", "kanilang", "lahat", "iba", "ibang", "kahit", "gitna", "bukod",
    "bawat", "isang", "isa", "mula", "tungo", "dahil", "kaya", "pero", "ngunit",
}


def select_examples(
    word: str,
    pos: str,
    ox_example: str,
    tgl_list: list[str],
    wn_exc: dict[str, set[str]],
    ws_ex: dict[tuple[str, str], str],
    wn_ex: dict[tuple[str, str], str],
    pairs,
    en_index,
    tl_index,
    tl_stem_index,
    pair_en_tokens,
    pair_tl_stems,
    exclude_pairs: set[tuple[str, str]] | None = None,
) -> tuple[str, str]:
    """Choose clean (example_en, example_tl) pair respecting POS and sentence brevity."""
    pb = pos_bucket(pos)
    excluded = exclude_pairs or set()
    tw_stems: set[str] = set()
    for tw in tgl_list[:3]:
        for tok in re.findall(r"[a-z\u00C0-\u024F-]+", tw.lower()):
            if len(tok) >= 3 and tok not in TGL_STOPWORDS:
                tw_stems.update(tgl_stems(tok))

    # 1. Search parallel sentences matching POS-appropriate English forms
    cand_ids: set[int] = set()
    en_forms = english_inflections(word, pos, wn_exc)
    for f in en_forms:
        if " " not in f:
            cand_ids.update(en_index.get(f, []))

    best_par = None
    best_par_sc = -1e9
    for sid in cand_ids:
        prio, src, e, t = pairs[sid]
        if (e, t) in excluded:
            continue
        sc = {0: 8.0, 1: 4.5, 2: 1.5, 3: -2.0}.get(prio, 0.0)
        if 15 <= len(e) <= 95:
            sc += 4.0
        elif 96 <= len(e) <= 130:
            sc += 1.5
        elif len(e) > 150 or len(e) < 12:
            sc -= 2.5
        if word in pair_en_tokens[sid]:
            sc += 1.5
        # Translation alignment boost (most decisive signal!)
        if tw_stems & pair_tl_stems[sid]:
            sc += 6.0
        if sc > best_par_sc:
            best_par_sc = sc
            best_par = (prio, src, e, t)

    en_fallback = ox_example or ws_ex.get((word, pb)) or ws_ex.get((word, "")) or wn_ex.get((word, pb)) or wn_ex.get((word, "")) or ""

    if best_par is not None:
        prio, src, par_e, par_t = best_par
        if prio == 0 or (prio <= 2 and len(par_e) <= 115) or not en_fallback:
            return par_e, par_t
        if en_fallback and is_full_sentence(en_fallback):
            return en_fallback, f"{par_t} ({par_e})"
        return par_e, par_t

    # 2. Search Tagalog-side parallel sentences by content words (preferring single words or exact multi-word phrases)
    tl_cand_ids: set[int] = set()
    multi_phrases: list[str] = []
    single_toks: list[str] = []
    for tw in tgl_list[:3]:
        tw_l = tw.lower().strip()
        if " " in tw_l:
            multi_phrases.append(tw_l)
        else:
            for tok in re.findall(r"[a-z\u00C0-\u024F-]+", tw_l):
                if len(tok) >= 4 and tok not in TGL_STOPWORDS:
                    single_toks.append(tok)
    for tok in single_toks:
        tl_cand_ids.update(tl_index.get(tok, []))
        tl_cand_ids.update(tl_stem_index.get(tok, []))
    if not tl_cand_ids and multi_phrases:
        for mp in multi_phrases:
            for tok in re.findall(r"[a-z\u00C0-\u024F-]+", mp):
                if len(tok) >= 4 and tok not in TGL_STOPWORDS:
                    tl_cand_ids.update(tl_index.get(tok, []))

    best_tl = None
    best_tl_sc = -1e9
    for sid in tl_cand_ids:
        prio, src, e, t = pairs[sid]
        if (e, t) in excluded:
            continue
        t_low = t.lower()
        # Reject Filipino proper names (e.g., "ni Datu", "si Datu", mid-sentence Capitalized match)
        proper_name_hit = False
        for tok in single_toks:
            cap_tok = tok.capitalize()
            if re.search(rf"\b(?:si|ni|kay|sina|nina|kina)\s+{re.escape(tok)}\b", t_low):
                proper_name_hit = True
                break
            if re.search(rf"(?<=\s){re.escape(cap_tok)}\b", t) and re.search(rf"\b{re.escape(cap_tok)}\b", e):
                proper_name_hit = True
                break
        if proper_name_hit:
            continue
        sc = {0: 7.5, 1: 4.5, 2: 1.5, 3: -2.0}.get(prio, 0.0)
        if any(mp in t_low for mp in multi_phrases):
            sc += 4.5
        if 15 <= len(t) <= 105:
            sc += 3.5
        elif len(t) > 160:
            sc -= 2.5
        if sc > best_tl_sc:
            best_tl_sc = sc
            best_tl = (e, t)

    if best_tl is not None:
        par_e, par_t = best_tl
        if en_fallback:
            return en_fallback, f"{par_t} ({par_e})"
        # Only return Tagalog example + English translation in Tagalog example slot (don't pretend par_e is an EN headword example)
        return "", f"{par_t} ({par_e})"

    return en_fallback, ""


# ---------------------------------------------------------------------------
# Synonym / Inflection builder (.syn)
# ---------------------------------------------------------------------------

def build_synonyms(headwords_set: set[str], wn_exc: dict[str, set[str]]) -> dict[str, set[str]]:
    """
    Map surface variants (irregulars, UK<->US spellings, -ied, doubled comparatives)
    not already present as headwords -> target headword(s).
    """
    syn_map: dict[str, set[str]] = defaultdict(set)

    def add_syn(surface: str, target: str):
        s = surface.strip().lower()
        t = target.strip().lower()
        if not s or not t or s == t or s in headwords_set or t not in headwords_set:
            return
        if len(s.encode("utf-8")) > MAX_HEADWORD_BYTES or "\x00" in s:
            return
        syn_map[s].add(t)

    # 1. WordNet irregular inflections
    for base, infls in wn_exc.items():
        if base in headwords_set:
            for inf in infls:
                add_syn(inf, base)

    # 2. Core irregular verbs/pronouns/auxiliaries
    extra_irreg = {
        "be": ["am", "is", "are", "was", "were", "been", "being"],
        "have": ["has", "had", "having"],
        "do": ["does", "did", "done", "doing"],
        "go": ["goes", "went", "gone", "going"],
        "good": ["better", "best"],
        "bad": ["worse", "worst"],
        "far": ["farther", "farthest", "further", "furthest"],
        "little": ["less", "least"],
        "many": ["more", "most"],
        "much": ["more", "most"],
        "person": ["people", "persons"],
        "child": ["children"],
        "man": ["men"],
        "woman": ["women"],
        "foot": ["feet"],
        "tooth": ["teeth"],
        "mouse": ["mice"],
        "goose": ["geese"],
        "ox": ["oxen"],
        "leaf": ["leaves"],
        "knife": ["knives"],
        "wife": ["wives"],
        "life": ["lives"],
        "wolf": ["wolves"],
        "shelf": ["shelves"],
        "half": ["halves"],
        "thief": ["thieves"],
        "loaf": ["loaves"],
        "criterion": ["criteria"],
        "phenomenon": ["phenomena"],
    }
    for base, forms in extra_irreg.items():
        if base in headwords_set:
            for f in forms:
                add_syn(f, base)

    # 3. UK<->US spelling variants, -ied/-ier/-iest (gaps in CrossPoint's stemVariants)
    for hw in headwords_set:
        if " " in hw:
            continue
        for v in uk_us_variants(hw):
            add_syn(v, hw)
        if hw.endswith("y") and len(hw) > 2 and hw[-2] not in "aeiou":
            stem = hw[:-1]
            add_syn(stem + "ied", hw)
            add_syn(stem + "ier", hw)
            add_syn(stem + "iest", hw)
        if "-" in hw:
            add_syn(hw.replace("-", ""), hw)

    return syn_map


# ---------------------------------------------------------------------------
# StarDict + DictZip writer (100% CrossPoint compliant)
# ---------------------------------------------------------------------------

def truncate_utf8(b: bytes, max_bytes: int) -> bytes:
    if len(b) <= max_bytes:
        return b
    end = max_bytes
    while end > 0 and (b[end] & 0xC0) == 0x80:
        end -= 1
    return b[:end]


def write_dictzip(dict_bytes: bytes, dest: Path) -> None:
    chunk_count = max(1, math.ceil(len(dict_bytes) / DICTZIP_CHUNK))
    if chunk_count > MAX_CHUNKS:
        raise ValueError(f"Dictionary too large for CrossPoint dictzip: {chunk_count} chunks > {MAX_CHUNKS}")

    comp = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
    compressed_chunks: list[bytes] = []
    chunk_sizes: list[int] = []

    for i in range(chunk_count):
        raw_chunk = dict_bytes[i * DICTZIP_CHUNK : (i + 1) * DICTZIP_CHUNK]
        data = comp.compress(raw_chunk)
        if i < chunk_count - 1:
            data += comp.flush(zlib.Z_FULL_FLUSH)
        else:
            data += comp.flush(zlib.Z_FINISH)
        if len(data) > 0xFFFF:
            raise ValueError(f"Compressed chunk {i} exceeds 64KB ({len(data)} bytes)")
        compressed_chunks.append(data)
        chunk_sizes.append(len(data))

    sub_len = 6 + 2 * chunk_count
    extra = bytearray(4 + sub_len)
    extra[0:2] = b"RA"
    struct.pack_into("<HHHH", extra, 2, sub_len, 1, DICTZIP_CHUNK, chunk_count)
    for i, sz in enumerate(chunk_sizes):
        struct.pack_into("<H", extra, 10 + 2 * i, sz)

    header = bytearray(12)
    header[0] = 0x1F
    header[1] = 0x8B
    header[2] = 8
    header[3] = 0x04  # FEXTRA
    header[9] = 0xFF  # OS unknown
    struct.pack_into("<H", header, 10, len(extra))

    crc = zlib.crc32(dict_bytes) & 0xFFFFFFFF
    isize = len(dict_bytes) & 0xFFFFFFFF
    trailer = struct.pack("<II", crc, isize)

    dest.write_bytes(bytes(header) + bytes(extra) + b"".join(compressed_chunks) + trailer)


def format_entry_html(word: str, senses: list[dict]) -> str:
    blocks = []
    for s in senses:
        pos_label = s["pos"] if s["pos"] != "other" else ""
        meta_parts = [p for p in (pos_label, s.get("cefr", "")) if p]
        meta_str = f" <i>({html.escape(', '.join(meta_parts))})</i>" if meta_parts else ""
        lines = [
            f"<p><b>{html.escape(word)}</b>{meta_str}</p>",
            f"<p><b>Meaning:</b> {html.escape(s['meaning'])}</p>",
        ]
        if s.get("example_en"):
            lines.append(f"<p><b>Example:</b> <i>{html.escape(s['example_en'])}</i></p>")
        lines.append(f"<p><b>Tagalog:</b> {html.escape(', '.join(s['tagalog']))}</p>")
        if s.get("example_tl"):
            lines.append(f"<p><b>Tagalog example:</b> <i>{html.escape(s['example_tl'])}</i></p>")
        blocks.append("".join(lines))
    return "<hr>".join(blocks) if len(blocks) > 1 else blocks[0]


def main():
    parser = argparse.ArgumentParser(description="Build Oxford English-to-English-to-Tagalog StarDict for CrossPoint.")
    parser.add_argument("--sources-dir", type=Path, default=Path("/tmp/research"), help="Directory containing downloaded source repos.")
    parser.add_argument("--out-dir", type=Path, default=Path("oxford-en-tl"), help="Output folder for StarDict files.")
    parser.add_argument("--preview", nargs="*", help="Print sample formatted entries for given words and exit.")
    args = parser.parse_args()

    print("Loading parallel English-Tagalog corpus...")
    pairs, en_index, tl_index, tl_stem_index, pair_en_tokens, pair_tl_stems = load_parallel_corpus(args.sources_dir)
    print(f"  Loaded {len(pairs):,} deduplicated parallel EN-TL sentences.")

    print("Loading WordNet 3.0 synsets and irregular inflections...")
    wn_syn, wn_word_sids, wn_pert_adj, wn_rel_sids, wn_exc = load_wordnet(args.sources_dir)
    print(f"  Loaded {len(wn_syn):,} synsets, {len(wn_exc):,} irregular base lemmas.")

    print("Building Tagalog translation scorer...")
    translate_tgl = build_tagalog_translator(
        args.sources_dir, wn_syn, wn_word_sids, wn_pert_adj, wn_rel_sids, pairs, en_index, pair_tl_stems
    )

    print("Loading Oxford English sources...")
    oxford_entries = load_oxford_entries(args.sources_dir)
    print(f"  Loaded {len(oxford_entries):,} raw Oxford headwords.")

    print("Loading English example fallbacks (Wordset + WordNet)...")
    ws_ex, wn_ex = load_english_example_fallbacks(args.sources_dir, wn_syn, wn_word_sids)

    def build_word_senses(word: str) -> list[dict]:
        built = []
        used_pairs: set[tuple[str, str]] = set()
        for s in oxford_entries.get(word, []):
            tgl = translate_tgl(word, s["pos"], strict_pos=not s["is_ox5k"], meaning=s["meaning"])
            if not tgl:
                continue
            ex_en, ex_tl = select_examples(
                word,
                s["pos"],
                s["example"],
                tgl,
                wn_exc,
                ws_ex,
                wn_ex,
                pairs,
                en_index,
                tl_index,
                tl_stem_index,
                pair_en_tokens,
                pair_tl_stems,
                exclude_pairs=used_pairs,
            )
            if ex_tl:
                if ex_tl.endswith(")") and " (" in ex_tl:
                    tl_part, en_part = ex_tl.rsplit(" (", 1)
                    used_pairs.add((en_part[:-1], tl_part))
                elif ex_en:
                    used_pairs.add((ex_en, ex_tl))
            built.append(
                {
                    "pos": s["pos"],
                    "cefr": s["cefr"],
                    "meaning": s["meaning"],
                    "tagalog": tgl,
                    "example_en": ex_en,
                    "example_tl": ex_tl,
                    "is_ox5k": s["is_ox5k"],
                }
            )
        return built

    if args.preview:
        for w in args.preview:
            senses = build_word_senses(w.lower())
            print("=" * 60)
            print(f"HEADWORD: {w}")
            if not senses:
                print("  [NO ENTRY]")
            else:
                print(format_entry_html(w, senses))
        return

    print("Assembling entries with verified Oxford meanings & Tagalog translations...")
    final_entries: dict[str, str] = {}
    stats = {
        "total_headwords": 0,
        "ox5k_headwords": 0,
        "with_example_en": 0,
        "with_example_tl": 0,
        "all_5_fields": 0,
    }

    for word in sorted(oxford_entries.keys()):
        w_bytes = word.encode("utf-8")
        if not w_bytes or len(w_bytes) > MAX_HEADWORD_BYTES or b"\x00" in w_bytes:
            continue
        senses = build_word_senses(word)
        if not senses:
            continue
        body_html = format_entry_html(word, senses)
        final_entries[word] = body_html

        stats["total_headwords"] += 1
        if any(s["is_ox5k"] for s in senses):
            stats["ox5k_headwords"] += 1
        has_en = any(s["example_en"] for s in senses)
        has_tl = any(s["example_tl"] for s in senses)
        if has_en:
            stats["with_example_en"] += 1
        if has_tl:
            stats["with_example_tl"] += 1
        if has_en and has_tl:
            stats["all_5_fields"] += 1

    print(
        f"  Built {stats['total_headwords']:,} headwords "
        f"(Oxford 5000: {stats['ox5k_headwords']:,}, "
        f"EN example: {stats['with_example_en']:,}, "
        f"TL example: {stats['with_example_tl']:,}, "
        f"all 5 fields: {stats['all_5_fields']:,})"
    )

    # Sort by CrossPoint asciiCaseCmp
    sorted_words = sorted(
        final_entries.keys(),
        key=lambda w: (ascii_lower_bytes(w.encode("utf-8")), w.encode("utf-8")),
    )

    # Build .dict and .idx
    dict_parts: list[bytes] = []
    idx_parts: list[bytes] = []
    word_to_ordinal: dict[str, int] = {}
    offset = 0

    for ordinal, word in enumerate(sorted_words):
        w_bytes = word.encode("utf-8")
        body_bytes = truncate_utf8(final_entries[word].encode("utf-8"), MAX_DEFINITION_BYTES)
        dict_parts.append(body_bytes)
        idx_parts.append(w_bytes + b"\x00" + struct.pack(">II", offset, len(body_bytes)))
        word_to_ordinal[word] = ordinal
        offset += len(body_bytes)

    dict_bytes = b"".join(dict_parts)
    idx_bytes = b"".join(idx_parts)

    # Build .syn
    print("Building synonym & inflection index (.syn)...")
    syn_map = build_synonyms(set(sorted_words), wn_exc)
    syn_pairs: list[tuple[bytes, int]] = []
    for surf, targets in syn_map.items():
        s_bytes = surf.encode("utf-8")
        for tgt in sorted(targets):
            if tgt in word_to_ordinal:
                syn_pairs.append((s_bytes, word_to_ordinal[tgt]))
    syn_pairs.sort(key=lambda item: (ascii_lower_bytes(item[0]), item[0], item[1]))
    syn_bytes = b"".join(s_b + b"\x00" + struct.pack(">I", ord_id) for s_b, ord_id in syn_pairs)

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / f"{DICT_STEM}.idx").write_bytes(idx_bytes)
    (out_dir / f"{DICT_STEM}.syn").write_bytes(syn_bytes)
    write_dictzip(dict_bytes, out_dir / f"{DICT_STEM}.dict.dz")

    ifo_text = (
        "StarDict's dict ifo file\n"
        "version=2.4.2\n"
        f"bookname={BOOKNAME}\n"
        f"wordcount={len(sorted_words)}\n"
        f"synwordcount={len(syn_pairs)}\n"
        f"idxfilesize={len(idx_bytes)}\n"
        "sametypesequence=h\n"
    )
    (out_dir / f"{DICT_STEM}.ifo").write_text(ifo_text, encoding="utf-8")

    dz_size = (out_dir / f"{DICT_STEM}.dict.dz").stat().st_size
    print(f"Wrote StarDict files to {out_dir}/:")
    print(f"  {DICT_STEM}.ifo     ({len(ifo_text)} bytes)")
    print(f"  {DICT_STEM}.idx     ({len(idx_bytes):,} bytes, {len(sorted_words):,} headwords)")
    print(f"  {DICT_STEM}.syn     ({len(syn_bytes):,} bytes, {len(syn_pairs):,} synonyms)")
    print(f"  {DICT_STEM}.dict.dz ({dz_size:,} bytes compressed, {len(dict_bytes):,} bytes uncompressed)")


if __name__ == "__main__":
    main()
