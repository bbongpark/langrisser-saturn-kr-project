#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_steam_glossary.py — build a JP->KR glossary + dialogue map from the Steam
Langrisser I&II reference (Unity TextAssets dumped to steam_ref/).

Each Steam data CSV is multi-language: a JP source column (名称/メッセージ) paired
with a Korean column (header ends with ハングル/_ハングル, or is Hangul-majority).
We detect Korean columns and pair each with its nearest preceding JP text column,
emitting JP->KR pairs. Terminology (classes, spells, items, chars, system words)
becomes the shared glossary every translation session must obey; eventMessage
becomes a JP->KR dialogue reference for tone/exact matches.

Outputs (build/):
  steam_glossary.json   {jp: kr, ...}         (terminology, deduped, JP unique)
  steam_glossary.tsv    jp<TAB>kr<TAB>source
  steam_dialogue.json   {jp_norm: kr}          (eventMessage lines for matching)
"""
import sys, io, os, csv, re, json
sys.stdout.reconfigure(encoding="utf-8")

REF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "steam_ref")
BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")
HAN = re.compile(r'[가-힣]')
JP = re.compile(r'[぀-ヿ一-鿿]')

# terminology CSVs (short name/label fields) — priority glossary sources
TERM_FILES = ["GameWordList", "classData", "magicData", "skillData", "itemData",
              "weaponData", "charactorData", "unitList", "unitList2", "shopData",
              "scenarioInfoData"]


def read_rows(name):
    p = os.path.join(REF, name + ".txt")
    if not os.path.exists(p):
        return None
    t = open(p, encoding="utf-8", errors="replace").read()
    return list(csv.reader(t.splitlines()))


# language suffixes on Steam CSV column headers (case-insensitive)
_LANGSUF = re.compile(r'[_ ]?(EN|CH|KR|JP|ハングル|한글|中国|中文|日本語?|英語?)$', re.I)
_KRSUF = re.compile(r'[_ ]?(KR|ハングル|한글)$', re.I)
_JPSUF = re.compile(r'[_ ]?(JP|日本語?)$', re.I)


def _base(n):
    return _LANGSUF.sub('', n).strip()


def kr_jp_col_pairs(header):
    """Pair each Korean column (name endswith KR/_kr/ハングル/한글) with its JP source
    column (same base name, or base+_jp). Base = header name minus any language
    suffix. Avoids the Chinese (CH/中国) column. Returns [(jp_ci, kr_ci)]."""
    names = {ci: (h or "").strip() for ci, h in enumerate(header)}
    jp_by_base = {}
    for ci, n in names.items():
        if not n:
            continue
        if _JPSUF.search(n):                      # explicit _jp wins
            jp_by_base[_base(n)] = ci
        elif not _LANGSUF.search(n):              # bare base name = JP source
            jp_by_base.setdefault(_base(n), ci)
    pairs = []
    for ci, n in names.items():
        if n and _KRSUF.search(n):
            jc = jp_by_base.get(_base(n))
            if jc is not None and jc != ci:
                pairs.append((jc, ci))
    return pairs


def strip_tags(s):
    """Remove TMP rich-text tags and normalize the ideographic space."""
    s = re.sub(r'<[^>]+>', '', s)
    return s.replace('　', ' ').replace('⏎', '\n').strip()


def extract_terms():
    glossary = {}          # jp -> (kr, source)
    for name in TERM_FILES:
        rows = read_rows(name)
        if not rows:
            continue
        start = next((i for i, r in enumerate(rows) if r and r[0] == "START"), 0) + 1
        header = rows[start - 1] if start else []
        pairs = 0
        for jc, kc in kr_jp_col_pairs(header):
            for r in rows[start:]:
                if kc < len(r) and jc < len(r):
                    jv, kv = strip_tags(r[jc]), strip_tags(r[kc])
                    # short label only (glossary = terms, not sentences)
                    if jv and kv and len(jv) <= 16 and '\n' not in jv and JP.search(jv) and HAN.search(kv):
                        if jv not in glossary:
                            glossary[jv] = (kv, name)
                            pairs += 1
        print(f"  {name}: {pairs} term pairs")
    return glossary


def extract_dialogue():
    """eventMessage JP->KR lines (full sentences) for tone/exact matching."""
    dlg = {}
    for name in ["eventMessage", "eventMessage2"]:
        rows = read_rows(name)
        if not rows:
            continue
        start = next((i for i, r in enumerate(rows) if r and r[0] == "START"), 0) + 1
        header = rows[start - 1] if start else []
        n = 0
        for jc, kc in kr_jp_col_pairs(header):
            for r in rows[start:]:
                if kc < len(r) and jc < len(r):
                    jv, kv = strip_tags(r[jc]), strip_tags(r[kc])
                    if jv and kv and JP.search(jv) and HAN.search(kv):
                        key = re.sub(r'\s+', '', jv)   # normalized JP key
                        if key not in dlg:
                            dlg[key] = kv
                            n += 1
        print(f"  {name}: {n} dialogue lines")
    return dlg


if __name__ == "__main__":
    os.makedirs(BUILD, exist_ok=True)
    print("=== terminology glossary ===")
    g = extract_terms()
    flat = {jp: kr for jp, (kr, src) in g.items()}
    json.dump(flat, open(os.path.join(BUILD, "steam_glossary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with open(os.path.join(BUILD, "steam_glossary.tsv"), "w", encoding="utf-8") as f:
        for jp, (kr, src) in sorted(g.items()):
            f.write(f"{jp}\t{kr}\t{src}\n")
    print(f"glossary: {len(g)} unique JP terms -> build/steam_glossary.json/.tsv")
    print("\n=== dialogue reference ===")
    d = extract_dialogue()
    json.dump(d, open(os.path.join(BUILD, "steam_dialogue.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"dialogue: {len(d)} JP->KR lines -> build/steam_dialogue.json")
    print("\nsample glossary:")
    for jp, (kr, src) in list(g.items())[:20]:
        print(f"  {jp} -> {kr}  [{src}]")
