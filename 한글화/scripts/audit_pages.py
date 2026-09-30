#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_pages.py — **원문보다 페이지가 늘어난 대사**를 찾는다.

  python scripts/audit_pages.py L2 0       # 한 시나리오
  python scripts/audit_pages.py L2          # 게임 전체 요약
  python scripts/audit_pages.py             # L1+L2 전체 요약
  python scripts/audit_pages.py L2 0 --narr # 나레이션까지 포함(기본은 대사만)

⛔ 왜 중요한가(세션22 사고): `[PAGE]`(원문 `{06}{07}`)는 조판이 아니라 **음성 재생 구간
경계**다. 원문보다 페이지가 **모자라면** 음성이 중간에 끊긴다(`repaginate.py`가 3,002건 복원).
반대로 **늘어나는 것**은 음성이 끊기진 않지만 버튼을 더 눌러야 하고, 대개 "조판이 안 들어가서
밀린" 신호다 — 문장을 다듬거나 KR에만 있는 `[PAGE]`를 빼면 원문 페이지 수로 되돌릴 수 있다.

★ **나레이션(2,7)은 기본 제외**다(세션24 사용자 판단) — 음성이 없어서 페이지가 늘어도 무방하다.
  음성 때문에 맞춰야 하는 것은 **대사(2,5)** 뿐이다.

페이지 수는 **워크시트의 `[PAGE]` 개수가 아니라 실제 조판 결과**로 센다. 워드랩이 줄을
늘려 페이지가 쪼개지는 경우가 대부분이라, `[PAGE]`만 세면 놓친다.
⛔ 원문보다 **줄이면 안 된다** — 되돌리는 목표는 언제나 "원문과 같은 수"까지다.
"""
import argparse
import collections
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dump_scenario_kr as D                                        # noqa: E402
import kr_markup as M                                               # noqa: E402
import kr_names                                                     # noqa: E402


def jp_pages(jp):
    """원문의 페이지 수 — `{06}{07}` 로 끊고 빈 조각은 세지 않는다."""
    parts = re.split(r"\{06\}\{07\}", jp or "")
    return max(1, sum(1 for p in parts if re.sub(r"\{[^}]*\}|\s", "", p)))


def kr_pages(entry, tag):
    """실제 조판 결과의 페이지 수(빈 페이지 제외)."""
    g = D.geometry(entry, tag)
    fixed = M.rewrap_markup(entry.get("kr", ""), width=g["w"], max_lines=g["ml"],
                            space_cells=g["sc"], absorb=g["absorb"], reflow=g["reflow"],
                            page2_lines=g["page2"], sentence_pages=g["sentence"],
                            name_w=g["name_w"], wait_w=g["wait_w"])
    n = 0
    for page in fixed.split("[PAGE]"):
        if re.sub(r"\[[^\]]*\]|\s", "", page):
            n += 1
    return max(1, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?", help="L1 | L2")
    ap.add_argument("block", nargs="?", type=int)
    ap.add_argument("--narr", action="store_true",
                    help="나레이션(2,7)도 포함 — 기본은 음성이 걸린 대사(2,5)만")
    a = ap.parse_args()
    want = (D.NARR, D.DLG) if a.narr else (D.DLG,)

    ws = D.load()
    D.NAME_W = kr_names.width_map(ws)
    names_all = D.name_tables(ws)
    ttl = D.titles(ws)

    over = collections.defaultdict(list)      # (tag, blk) -> [(seg, jp, kr, 본문)]
    for e in ws:
        seen = set()
        for tag, blk, leaf, seg in D.parsed_ids(e):
            if leaf not in want:
                continue
            if a.tag and tag != a.tag:
                continue
            if a.block is not None and blk != a.block:
                continue
            if (tag, blk, seg) in seen:
                continue
            seen.add((tag, blk, seg))
            j, k = jp_pages(e.get("jp", "")), kr_pages(e, tag)
            # ⛔ **줄어든 것이 늘어난 것보다 위험하다.** 페이지가 줄면 그 자리의 음성이
            #   통째로 끊긴다(세션22 사고). 세션24에 교정 중 실수로 뒤 두 페이지를
            #   날려먹은 일이 있어 이 검사를 넣었다.
            if k != j and e.get("jp"):
                names = names_all.get(tag, {})
                txt = D.render(e.get("kr", ""), names, names.get(1))
                over[(tag, blk)].append((seg, j, k, txt))

    total = sum(len(v) for v in over.values())
    if a.block is not None:
        key = (a.tag, a.block)
        rows = sorted(over.get(key, []))
        print("%s 블록%d 「%s」 — 원문과 페이지 수가 다른 항목 %d건"
              % (a.tag, a.block, ttl.get(key, ""), len(rows)))
        for seg, j, k, txt in rows:
            mark = "⛔줄어듦" if k < j else "늘어남"
            print("  #%-4d JP %d페이지 → KR %d페이지  [%s]" % (seg, j, k, mark))
            print("       %s" % txt)
        return

    print("원문과 페이지 수가 다른 항목: 총 %d건" % total)
    for key in sorted(over):
        cut = sum(1 for _s, j, k, _t in over[key] if k < j)
        note = "  (⛔줄어듦 %d)" % cut if cut else ""
        print("  %s 블록%-4d %3d건%s  「%s」"
              % (key[0], key[1], len(over[key]), note, ttl.get(key, "")))


if __name__ == "__main__":
    main()
