#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
match_steam.py — auto-fill the SCEN translation worksheet from the Steam reference.

For each unique SCEN string (dedup worksheet, MTE-expanded JP), try:
  1) exact glossary term   (whole string is a known term -> Steam KR term)
  2) exact dialogue match   (JP normalized == a Steam eventMessage JP line -> its KR)
Fills `kr` and records `src` (glossary/dialogue/none). The Saturn Dramatic Edition
script differs from the Steam remake, so exact dialogue overlap is partial; the rest
is flagged for translation (parallel sessions), to be done in the Steam tone using
the glossary + steam_dialogue for reference.

Also width-checks each auto-filled `kr` via kr_render (window fit) and reports
per-source coverage + how many need manual work.

Outputs build/worksheet_dedup_matched.json (worksheet with kr/src filled where matched).
"""
import sys, io, os, json, re
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kr_render, kr_markup

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")
CTRL = re.compile(r'\{[0-9a-f]{2}(:[0-9a-f]{2})?\}')   # {08} {09:45} etc. in jp field


def norm(s):
    """Normalize a JP string for matching: drop control-code tokens, spaces, and
    fullwidth/half punctuation differences."""
    s = CTRL.sub('', s)
    s = s.replace('　', '').replace(' ', '').replace('\n', '')
    return s.strip()


def main():
    ws = json.load(open(os.path.join(BUILD, "translation_worksheet_dedup.json"), encoding="utf-8"))
    glo = json.load(open(os.path.join(BUILD, "steam_glossary.json"), encoding="utf-8"))
    dlg = json.load(open(os.path.join(BUILD, "steam_dialogue.json"), encoding="utf-8"))
    # normalized dialogue keys already normalized (no spaces) in extractor; re-normalize both sides
    dlg_norm = {norm(k): v for k, v in dlg.items()}

    n_glo = n_dlg = n_none = 0
    for e in ws:
        jp = e["jp"]
        key = norm(jp)
        if key in glo:                       # whole string is a glossary term
            e["kr"] = glo[key]; e["src"] = "glossary"; n_glo += 1
        elif key in dlg_norm:                # exact dialogue line
            e["kr"] = dlg_norm[key]; e["src"] = "dialogue"; n_dlg += 1
        else:
            e["src"] = "none"; n_none += 1

    total = len(ws)
    print(f"dedup entries: {total}")
    print(f"  glossary match: {n_glo}")
    print(f"  dialogue match: {n_dlg}")
    print(f"  unmatched (need translation): {n_none}")
    print(f"  AUTO-FILLED: {n_glo+n_dlg} ({100*(n_glo+n_dlg)/total:.1f}%)")

    # width check on auto-filled (does the KR fit a window without [PAGE]?)
    oversize = 0
    for e in ws:
        if e.get("kr") and e["src"] != "none":
            try:
                pieces = kr_markup.parse_markup(e["kr"])
                if kr_markup.max_page_lines(pieces) > 3 and "[PAGE]" not in e["kr"]:
                    # raw KR (no auto-wrap) exceeds; note it needs render_segment/paging
                    lines = e["kr"].count("\n") + 1
                    if lines > 3:
                        oversize += 1
            except Exception:
                pass
    print(f"  auto-filled entries with explicit >3 lines (need paging): {oversize}")

    # coverage by occurrence count (weighted): how much of the actual on-screen text is covered
    filled_occ = sum(e["count"] for e in ws if e["src"] != "none")
    total_occ = sum(e["count"] for e in ws)
    print(f"  weighted coverage (by occurrences): {100*filled_occ/total_occ:.1f}%")

    out = os.path.join(BUILD, "worksheet_dedup_matched.json")
    json.dump(ws, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"-> {out}")
    print("\nsample matches:")
    shown = 0
    for e in ws:
        if e["src"] == "dialogue" and shown < 6:
            print(f"  [{e['src']}] {e['jp'][:34]} -> {e['kr'][:34]}"); shown += 1
    shown = 0
    for e in ws:
        if e["src"] == "glossary" and shown < 6:
            print(f"  [{e['src']}] {e['jp'][:20]} -> {e['kr'][:20]}"); shown += 1


if __name__ == "__main__":
    main()
