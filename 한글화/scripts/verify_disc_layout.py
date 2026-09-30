#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_disc_layout.py — **빌드된 디스크의 SCEN 바이트를 직접 읽어** 리프별 조판을 검증한다.
워크시트가 아니라 실제로 게임이 읽을 바이트를 보므로, 조판 파이프라인 전체의 최종 확인이다.

  python scripts/verify_disc_layout.py                 # 전체 요약
  python scripts/verify_disc_layout.py --conditions    # 조건 조각 줄바꿈 감사(1줄이어야 정상)

⛔⛔ 최대 함정 — **바이트를 그냥 `split(b"\\x08")` 하면 안 된다.**
`[NAME:08]`은 바이트로 `09 08`이라 인자 `08`이 개행으로 오독된다(세션22가 `{09}`의 인자
`04`를 MTE로 오독했던 것과 같은 사고). 세션23에 실제로 이걸로 "조건에 줄바꿈 4건"이라는
오탐이 나왔다. **반드시 아래 `tokens()`처럼 인자 있는 코드를 먼저 소비하며 훑어라.**

인자 있는 제어코드(정본): `09 XX`=이름, `04 XX`=MTE.  그 외 `<0x20`은 1바이트.
"""
import argparse
import collections
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import disc_tool                                        # noqa: E402
import kr_names                                         # noqa: E402
import scen_tool                                        # noqa: E402
import reinsert_text as R                               # noqa: E402

TRACK = os.path.join(ROOT, "build", "disc-krpoc", "track1.bin")
WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
FILES = {tag: (d["scen_lba"], d["alloc"]) for tag, d in R.FILES.items()}
# 검사할 리프와 그 폭 한도
LIMITS = {(2, 5): (R.WIDTH, R.MAX_LINES, R.DLG_PAGE2_LINES)}
for lf, (w, ml) in R.FULLSCREEN_GEOM.items():
    LIMITS[lf] = (w, ml, ml)
TUTORIAL_BLOCKS = {("L1", 20), ("L2", 98), ("L2", 100)}   # (2,6) 안의 여러 줄짜리 튜토리얼

ARG_CODES = {0x09, 0x04}      # 뒤에 1바이트 인자가 붙는 제어코드


def tokens(seg):
    """세그먼트 바이트 -> [(kind, value)] : ('nl',None) ('page',None) ('name',xx)
    ('wait',None) ('sp',None) ('ctrl',code) ('ch',n칸) 로 정확히 쪼갠다."""
    out = []
    i = 0
    n = len(seg)
    while i < n:
        c = seg[i]
        if c == 0x06 and i + 1 < n and seg[i + 1] == 0x07:
            out.append(("page", None)); i += 2; continue
        if c == 0x08:
            out.append(("nl", None)); i += 1; continue
        if c in ARG_CODES and i + 1 < n:                  # 09 XX / 04 XX
            out.append(("name" if c == 0x09 else "mte", seg[i + 1])); i += 2; continue
        if c == 0x02:
            out.append(("wait", None)); i += 1; continue
        if c == 0x01:
            out.append(("sp", None)); i += 1; continue
        if c < 0x20:
            out.append(("ctrl", c)); i += 1; continue
        if c < 0x80:
            out.append(("ch", 0.5)); i += 1; continue
        out.append(("ch", 1.0)); i += 2
    return out


def pages_of(seg, nw, ww=4, indent_w=0.0):
    """세그먼트 -> [page: [line_width]]  (칸수는 실제 이름 폭 반영).

    `indent_w` = `{05}`(0x05)의 폭. **{05}는 0폭 제어코드가 아니라 1칸 들여쓰기 공백이다**
    (세션24 실측: 원문에서 `{05}`로 시작하는 줄은 최대 15칸, 없는 줄은 16칸). 나레이션
    리프 `(2,7)`에서만 1.0을 넘긴다 — 다른 리프는 조판을 안 건드리므로 0.0 그대로다.

    `ww` = `{02}`의 폭. 여기서 검사하는 리프((2,5)/(2,6)/(2,7)/(2,9))의 `{02}`는
    세션24 전수 조사에서 **전부 주인공 이름**으로 확인됐다(아이템이 들어가는 건 UI 리프뿐).
    단 동결된 여신 블록은 조판이 옛 추정값(4칸) 그대로라 4를 넘겨야 한다."""
    pages, lines, cur = [], [], 0.0
    for kind, val in tokens(seg):
        if kind == "page":
            lines.append(cur); pages.append(lines); lines, cur = [], 0.0
        elif kind == "nl":
            lines.append(cur); cur = 0.0
        elif kind == "ch":
            cur += val
        elif kind == "sp":
            cur += 0.5
        elif kind == "name":
            cur += nw.get(val, 4)
        elif kind == "wait":
            cur += ww
        elif kind == "mte":
            cur += 2
        elif kind == "ctrl" and val == 0x05:
            cur += indent_w
    lines.append(cur); pages.append(lines)
    return pages


def iter_segments():
    ws = json.load(open(WS_PATH, encoding="utf-8"))
    nw_all = kr_names.width_map(ws)
    d = disc_tool.Disc(TRACK)
    for tag, (lba, alloc) in FILES.items():
        nw = nw_all[tag]
        tree = scen_tool.parse(d.read_file(lba, alloc))
        for path, leaf in scen_tool.iter_leaves(tree):
            leaf_key = tuple(path[1:3])
            if leaf_key not in LIMITS:
                continue
            for si, seg in enumerate(leaf.raw.split(b"\x00")):
                if not seg.strip(b"\x00"):
                    continue
                yield tag, path[0], leaf_key, si, seg, nw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", action="store_true",
                    help="조건 조각(튜토리얼 제외 (2,6))의 줄바꿈만 감사")
    a = ap.parse_args()

    stat = collections.defaultdict(lambda: [0.0, 0, 0])   # leaf -> [최장칸, 최대줄, 세그먼트]
    over_w, over_l, cond_multi = [], [], []
    for tag, blk, lf, si, seg, nw in iter_segments():
        w_lim, ml1, ml2 = LIMITS[lf]
        # 여신/미검증 블록은 reinsert가 옛 추정값으로 조판하므로 같은 자로 재야 한다.
        ww = 4 if (tag, blk) in R.LEGACY_GEOM_BLOCKS else R.PLAYER_NAME_CELLS
        # {05}는 나레이션에서만 1칸 들여쓰기로 센다(reinsert 와 같은 규칙).
        iw = 1.0 if (lf == (2, 7) and (tag, blk) not in R.LEGACY_GEOM_BLOCKS) else 0.0
        pages = pages_of(seg, nw, ww, iw)
        s = stat[(tag, lf)]
        s[2] += 1
        for pi, lines in enumerate(pages):
            live = [x for x in lines if x > 0]
            s[1] = max(s[1], len(live))
            s[0] = max(s[0], max(lines) if lines else 0)
            cap = ml1 if pi == 0 else ml2
            if len(live) > cap:
                over_l.append((tag, blk, lf, si, len(live), cap))
            for wv in lines:
                if wv > w_lim + 1e-6:
                    over_w.append((tag, blk, lf, si, round(wv, 1), w_lim))
        if lf == (2, 6) and (tag, blk) not in TUTORIAL_BLOCKS:
            nlines = sum(len([x for x in p if x > 0]) for p in pages)
            if nlines > 1 or len(pages) > 1:
                cond_multi.append((tag, blk, si, nlines, len(pages),
                                   [round(x, 1) for p in pages for x in p]))

    if a.conditions:
        n = sum(1 for t, b, lf, s, sg, nwv in iter_segments()
                if lf == (2, 6) and (t, b) not in TUTORIAL_BLOCKS)
        print(f"조건 조각 {n}개 (튜토리얼 블록 {sorted(TUTORIAL_BLOCKS)} 제외)")
        print(f"  → 2줄 이상인 조건: {len(cond_multi)}개   (원본 JP는 전부 1줄 = 0이어야 정상)")
        for c in cond_multi[:20]:
            print("     ", c)
        return int(bool(cond_multi))

    for (tag, lf) in sorted(stat):
        mw, ml, n = stat[(tag, lf)]
        lim = LIMITS[lf]
        print(f"{tag} leaf {lf}: 최장 {mw:g}칸/한도 {lim[0]} · 페이지 최대 {ml}줄/한도 "
              f"{max(lim[1], lim[2])} · 세그먼트 {n}")
    print(f"\n폭 초과 {len(over_w)}줄 · 줄수 초과 {len(over_l)}페이지 · "
          f"2줄 이상인 조건 {len(cond_multi)}개")
    for x in over_w[:10]:
        print("  [폭]", x)
    for x in over_l[:10]:
        print("  [줄]", x)
    return int(bool(over_w or over_l or cond_multi))


if __name__ == "__main__":
    sys.exit(main())
