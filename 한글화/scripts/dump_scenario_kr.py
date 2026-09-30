#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_scenario_kr.py — 시나리오(블록) 단위로 한글 나레이션·대사를 검수용으로 덤프한다.

사용자가 게임을 플레이하며 대사를 검수할 때 쓴다(세션24 워크플로).

  python scripts/dump_scenario_kr.py --list          # 블록(시나리오) 목록 + 제목
  python scripts/dump_scenario_kr.py L2 0            # L2 블록0 「서장」 나레이션+대사
  python scripts/dump_scenario_kr.py L2 0 --jp       # 원문 대조용 JP도 같이
  python scripts/dump_scenario_kr.py L2 0 --layout   # ★ 실제 조판(줄/페이지/칸수) 그대로

★ 블록 = 시나리오다. 제목은 나레이션 리프 (2,7)의 「…」 에서 뽑는다.
★ [NAME:xx]는 이름표의 실제 이름으로, [WAIT]({02})은 주인공 이름으로 치환해 보여준다
  — 사용자가 화면에서 볼 문자열과 같게 하기 위함(세션24: {02}는 대사/나레이션/조건
  리프에서 100% 주인공이다. 아이템명이 오는 건 UI 리프뿐).
⚠ 고치기 전에 그 엔트리의 `len(ids)`를 반드시 확인하라 — 1이 아니면 다른 시나리오와
  공유하는 문자열이라 한쪽만 고칠 수 없다. `--ids` 로 같이 출력된다.

★ `--layout` = **게임에 나갈 실제 조판**. reinsert_text와 **같은 파라미터**로 `rewrap_markup`을
  돌려 줄/페이지/칸수를 그대로 보여준다. `manual_layout`은 "번역자 줄바꿈 유지"일 뿐
  **넘치는 줄은 여전히 자동 워드랩**되므로, 워크시트의 `[NL]`만 보고 판단하면 안 된다.
"""
import argparse
import collections
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kr_markup as M                                               # noqa: E402
import kr_names                                                     # noqa: E402

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
ID = re.compile(r"^(L\d):(\d+)/([\d/]+)#(\d+)$")
NARR, COND, DLG = "2/7", "2/6", "2/5"
NAME_LEAF = "2/1"
NAME_W = {}          # main()에서 kr_names.width_map(ws) 로 채운다


def _disp(s):
    """터미널 표시 폭(칼럼). 전각 1칸 = 2칼럼."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def load():
    with open(WS_PATH, encoding="utf-8") as f:
        return json.load(f)


def parsed_ids(entry):
    for i in entry["ids"]:
        m = ID.match(i)
        if m:
            yield m.group(1), int(m.group(2)), m.group(3), int(m.group(4))


def name_tables(ws):
    """{tag: {세그먼트#: 이름}} — {09 XX} = 세그먼트 #(XX+1) (세션22 확정)."""
    t = collections.defaultdict(dict)
    for e in ws:
        for tag, _blk, leaf, seg in parsed_ids(e):
            if leaf == NAME_LEAF:
                t[tag].setdefault(seg, e.get("kr") or e.get("jp"))
    return t


def titles(ws):
    out = {}
    for e in ws:
        for tag, blk, leaf, _seg in parsed_ids(e):
            if leaf == NARR:
                m = re.search(r"「(.+?)」", re.sub(r"\[[^\]]*\]", "", e.get("kr", "")))
                if m:
                    out.setdefault((tag, blk), m.group(1).strip())
    return out


def do_list(ws):
    cnt = collections.defaultdict(collections.Counter)
    for e in ws:
        for tag, blk, leaf, _seg in parsed_ids(e):
            cnt[(tag, blk)][leaf] += 1
    ttl = titles(ws)
    for tag in ("L1", "L2"):
        print("=== %s ===" % tag)
        for key in sorted(k for k in cnt if k[0] == tag):
            c = cnt[key]
            if not (c[DLG] or c[NARR]):
                continue
            print("  블록%-4d 대사%-5d 나레%-3d 조건%-3d  「%s」"
                  % (key[1], c[DLG], c[NARR], c[COND], ttl.get(key, "")))


def geometry(entry, tag):
    """reinsert_text.build() 의 리프별 조판 파라미터를 그대로 재현한다.

    ⛔ 여기 값이 reinsert와 어긋나면 미리보기가 거짓말을 한다 — reinsert를 고치면 같이 고쳐라.
    dedup 엔트리는 **모든 위치**를 함께 봐야 한다(reinsert의 by_tag와 같은 규칙)."""
    import reinsert_text as R                                       # noqa: E402
    locs = [(t, b, tuple(int(x) for x in lf.split("/")))
            for t, b, lf, _s in parsed_ids(entry)]
    leaves = {lf for _t, _b, lf in locs}
    is_goddess = any((t, b) in R.LEGACY_GEOM_BLOCKS for t, b, _lf in locs)
    fs = set() if is_goddess else {lf for lf in leaves if lf in R.FULLSCREEN_GEOM}
    is_narr = bool(fs)
    is_dlg = not is_narr and all(lf == R.DLG_LEAF for lf in leaves)
    is_ui = any(lf == R.UI_LEAF for lf in leaves)
    if fs:
        w = min(R.FULLSCREEN_GEOM[lf][0] for lf in fs)
        ml = min(R.FULLSCREEN_GEOM[lf][1] for lf in fs)
    else:
        w, ml = R.WIDTH, R.MAX_LINES
    if is_dlg and not entry.get("absorb_box"):
        page2, absorb = R.DLG_PAGE2_LINES, False
    else:
        page2, absorb = None, (not is_narr)
    return dict(
        w=w, ml=ml, page2=page2, absorb=absorb,
        sc=1.0 if is_ui else (0.5 if R.FILES[tag]["space"] == M.HW_SPACE else 1.0),
        reflow=(is_dlg or (bool(fs) and fs <= R.FULLSCREEN_REFLOW))
        and not entry.get("manual_layout"),
        sentence=bool(entry.get("sentence_layout")),
        name_w=None if is_goddess else NAME_W.get(tag),
        wait_w=None if (is_goddess or is_ui) else R.PLAYER_NAME_CELLS,
        # {05} = 1칸 들여쓰기(세션24 실측). 나레이션에서만 센다 — reinsert와 같은 규칙.
        indent_w=1.0 if (is_narr and not is_goddess) else 0.0,
    )


def laid_out(entry, tag, names, player, keep_codes=False):
    """[(페이지번호, 줄문자열, 칸수)] — 게임에 나갈 실제 조판."""
    import reinsert_text as R                                       # noqa: E402
    g = geometry(entry, tag)
    kr = entry.get("kr", "")
    fixed = M.rewrap_markup(kr, width=g["w"], max_lines=g["ml"], space_cells=g["sc"],
                            absorb=g["absorb"], reflow=g["reflow"], page2_lines=g["page2"],
                            sentence_pages=g["sentence"], name_w=g["name_w"],
                            wait_w=g["wait_w"], indent_w=g["indent_w"])
    out = []
    for pi, page in enumerate(fixed.split("[PAGE]")):
        for ln in page.split("[NL]"):
            wv = M.max_line_width(M.parse_markup(ln), g["name_w"], g["wait_w"],
                                  g["indent_w"])
            out.append((pi + 1, render(ln, names, player, keep_codes), round(wv, 1)))
    return out, g["w"]


def render(kr, names, player, keep_codes=False):
    kr = re.sub(r"\[NAME:([0-9a-f]{2})\]",
                lambda m: str(names.get(int(m.group(1), 16) + 1, "[NAME:%s]" % m.group(1))),
                kr, flags=re.I)
    if player:
        kr = kr.replace("[WAIT]", player)
    if not keep_codes:
        kr = re.sub(r"\[C:[0-9a-fA-F]{2}\]", "", kr)
    kr = kr.replace("[PAGE]", " ¶ ").replace("[NL]", " / ")
    return re.sub(r"\s+", " ", kr).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?", help="L1 | L2")
    ap.add_argument("block", nargs="?", type=int)
    ap.add_argument("--list", action="store_true", help="블록(시나리오) 목록")
    ap.add_argument("--jp", action="store_true", help="원문도 함께 출력")
    ap.add_argument("--ids", action="store_true", help="중복 위치 수(len(ids))도 출력")
    ap.add_argument("--codes", action="store_true", help="[C:xx] 색코드 유지")
    ap.add_argument("--layout", action="store_true",
                    help="게임에 나갈 실제 조판(줄/페이지/칸수)으로 출력")
    ap.add_argument("--only", choices=["dlg", "narr"], help="대사만 / 나레이션만")
    a = ap.parse_args()

    ws = load()
    global NAME_W
    NAME_W = kr_names.width_map(ws)
    if a.list or not a.tag:
        return do_list(ws)

    names = name_tables(ws).get(a.tag, {})
    player = names.get(1)                     # L1 레딘 · L2 엘윈
    ttl = titles(ws).get((a.tag, a.block), "")
    want = {"dlg": (DLG,), "narr": (NARR,)}.get(a.only, (NARR, DLG))
    rows = []
    for e in ws:
        for tag, blk, leaf, seg in parsed_ids(e):
            if tag == a.tag and blk == a.block and leaf in want:
                rows.append((0 if leaf == NARR else 1, seg, leaf, e))
    rows.sort(key=lambda r: (r[0], r[1]))

    print("%s 블록%d 「%s」  — 나레이션+대사 %d개" % (a.tag, a.block, ttl, len(rows)))
    cur = None
    for _k, seg, leaf, e in rows:
        if leaf != cur:
            cur = leaf
            print("\n---- %s ----" % ("나레이션" if leaf == NARR else "대사"))
        tail = "  (ids %d)" % len(e["ids"]) if a.ids else ""
        if a.layout:
            lines, lim = laid_out(e, a.tag, names, player, a.codes)
            print("%-4d ┌%s┐%s" % (seg, "─" * (lim * 2), tail))
            prev = 1
            for pi, txt, wv in lines:
                if pi != prev:
                    print("     ├%s┤ ── 페이지 %d" % ("─" * (lim * 2), pi))
                    prev = pi
                pad = " " * max(0, lim * 2 - _disp(txt))
                print("     │%s%s│ %4.1f%s" % (txt, pad, wv, " ⛔초과" if wv > lim else ""))
        elif a.jp:
            print("%-4d JP  %s" % (seg, e.get("jp", "").replace("\n", "/")))
            print("     KR  %s%s" % (render(e.get("kr", ""), names, player, a.codes), tail))
        else:
            print("%-4d %s%s" % (seg, render(e.get("kr", ""), names, player, a.codes), tail))


if __name__ == "__main__":
    main()
