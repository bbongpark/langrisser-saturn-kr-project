#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_text.py — dump the translatable text inventory from LANG1/LANG2 SCEN.DAT
into a JSON worksheet (stable ids + MTE-expanded Japanese + structure metadata).

This is the production backbone for base translation: it enumerates every text
segment the game can display, gives each a stable id, and records enough
structure (line count, name/MTE/control usage) to translate and reinsert.

id format:  "L1:20/2/5#0"  = LANG1, tree child-path (20,2,5), NUL-segment 0.

A segment is included if its parent leaf scores as text (scen_text.leaf_text_score)
and the segment decodes as SJIS. `jp` is the MTE-expanded, human-readable Japanese
(control codes shown as {08} etc.); `raw_hex` preserves the exact original bytes so
reinsertion can diff/verify. Control inventory (has {09} name var, {04} MTE, {02})
tells the translator which segments carry runtime insertions.

Reinsertion (separate step): for segments whose only controls are {08} line breaks,
kr_render.render_message + build_translate_poc's disc path already handle Korean
end-to-end. Segments with {09}/{04}/{02} need a control-markup convention (future).
"""
import sys, io, os, json

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scen_tool, scen_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "original")
BUILD = os.path.join(ROOT, "build")

FILES = [("L1", "LANG1_SCEN.DAT"), ("L2", "LANG2_SCEN.DAT")]


def ctrl_inline(raw, mte):
    """MTE-expanded human-readable string with control codes shown as {xx}."""
    out = []
    for t in scen_text.tokenize(scen_text.expand_mte(raw, mte)):
        if t[0] == "text":
            out.append(t[1])
        elif t[0] == "ctrl":
            out.append("{%02x%s}" % (t[1], "" if t[2] is None else ":%02x" % t[2]))
        else:
            out.append("<%02x>" % t[1])
    return "".join(out)


def controls_of(raw):
    codes = set()
    for t in scen_text.tokenize(raw):
        if t[0] == "ctrl":
            codes.add(t[1])
    return codes


def text_score(raw, mte):
    """Fraction of NUL segments that read as displayable text — MTE-expanded and
    control-code-aware — plus the non-empty segment count.

    A segment counts as text if, AFTER MTE expansion ({04 XX} -> its fragment), it
    tokenizes into clean SJIS/ASCII with at most a few stray raw bytes. SCEN control
    codes ({05}, {08}, {06}{07}, {04 XX} MTE refs, ...) are NOT penalized. The old
    byte-`isprintable` heuristic treated those control bytes as garbage and so DROPPED
    whole leaves that are real text — victory/defeat conditions (leaf X/2/6, whose
    lines are `{05}・{02}の死亡` etc.) and scenario narration (leaf X/2/7, a single
    control-heavy segment) never made it into the worksheet. This scorer keeps them
    while still rejecting the binary event-script leaves (X/0, X/1, X/3..X/8), which
    are full of raw bytes even after MTE expansion."""
    segs = [s for s in raw.split(b"\x00") if s]
    if not segs:
        return 0.0, 0
    good = 0
    for s in segs:
        toks = scen_text.tokenize(scen_text.expand_mte(s, mte))
        nraw = sum(1 for t in toks if t[0] == "raw")
        nchar = sum(1 for t in toks if t[0] == "text" for ch in t[1] if not ch.isspace())
        if nchar >= 2 and nraw <= max(2, 0.12 * nchar):
            good += 1
    return good / len(segs), len(segs)


def extract_file(tag, name):
    data = open(os.path.join(ORIG, name), "rb").read()
    tree = scen_tool.parse(data)
    records = []
    # top-level blocks -> their MTE dict
    for path, leaf in scen_tool.iter_leaves(tree):
        # skip the per-block MTE dictionary leaf (block,2,4) — it's the fragment
        # store, not display text (it's substituted into other segments via {04}).
        if len(path) >= 3 and path[-2:] == (2, 4):
            continue
        block = path[0]
        mte = scen_text.get_block_dict(tree, block)
        score, nseg = text_score(leaf.raw, mte)
        if score < 0.6 or nseg < 1:
            continue
        segs = leaf.raw.split(b"\x00")
        paths = "/".join(str(i) for i in path)
        for si, seg in enumerate(segs):
            if not seg:
                continue
            # keep every non-empty segment of a text-scored leaf (raw_hex preserves the
            # exact bytes; a few segments may carry stray high bytes — surrogateescape
            # never fails, and dropping them here would silently orphan real lines).
            seg.decode("shift_jis", "surrogateescape")
            codes = controls_of(seg)
            # sanitize surrogate-escaped undecodable bytes for JSON safety
            # (raw_hex preserves the exact original bytes losslessly)
            jp = ctrl_inline(seg, mte).encode("utf-8", "replace").decode("utf-8")
            records.append({
                "id": f"{tag}:{paths}#{si}",
                "jp": jp,
                "raw_hex": seg.hex(),
                "bytes": len(seg),
                "lines": jp.count("{08}") + 1,
                "has_name": 0x09 in codes,
                "has_mte": 0x04 in codes,
                "has_wait": 0x02 in codes,
                "kr": "",   # translator fills this
            })
    return records


def main():
    all_recs = []
    per = {}
    for tag, name in FILES:
        recs = extract_file(tag, name)
        per[tag] = recs
        all_recs.extend(recs)
    out_path = os.path.join(BUILD, "translation_worksheet.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_recs, f, ensure_ascii=False, indent=1)

    # deduplicated worksheet: SCEN replicates strings heavily across blocks, so
    # translate each UNIQUE byte sequence once -> applies to all its occurrences.
    # Keyed by raw_hex (exact bytes = identical reinsertion target).
    dedup = {}
    for r in all_recs:
        d = dedup.setdefault(r["raw_hex"], {
            "jp": r["jp"], "bytes": r["bytes"], "lines": r["lines"],
            "has_name": r["has_name"], "has_mte": r["has_mte"],
            "has_wait": r["has_wait"], "count": 0, "ids": [], "kr": "",
        })
        d["count"] += 1
        d["ids"].append(r["id"])
    dedup_list = sorted(dedup.values(), key=lambda d: -d["count"])
    dedup_path = os.path.join(BUILD, "translation_worksheet_dedup.json")
    with open(dedup_path, "w", encoding="utf-8") as f:
        json.dump(dedup_list, f, ensure_ascii=False, indent=1)
    print(f"dedup worksheet -> {dedup_path}  ({len(dedup_list):,} unique strings)")
    # summary
    tot_bytes = sum(r["bytes"] for r in all_recs)
    dlg = [r for r in all_recs if r["lines"] > 1]
    names = sum(r["has_name"] for r in all_recs)
    mte = sum(r["has_mte"] for r in all_recs)
    print(f"worksheet -> {out_path}")
    for tag in per:
        print(f"  {tag}: {len(per[tag]):,} segments")
    print(f"TOTAL: {len(all_recs):,} segments, {tot_bytes:,} JP bytes")
    print(f"  multi-line dialogue segments: {len(dlg):,}")
    print(f"  segments with {{09}} name var: {names:,}   with {{04}} MTE: {mte:,}")
    print("\nsample records:")
    for r in all_recs[:3] + dlg[:3]:
        print(f"  [{r['id']}] ({r['bytes']}B, {r['lines']}L) {r['jp'][:60]}")


if __name__ == "__main__":
    main()
