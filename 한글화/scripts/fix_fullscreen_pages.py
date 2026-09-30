#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_fullscreen_pages.py — 전체화면 리프((2,6) 조건/튜토리얼 · (2,9) 엔딩)에서
**문장을 가르는 가짜 [PAGE]** 를 없앤다.

왜 생겼나: 세션22까지 이 두 리프는 대사 박스 지오메트리(14칸x3줄, 흡수줄 있음)로 조판됐다.
실제 창은 나레이션과 같은 16칸 격자(세션23 실측 — reinsert_text.FULLSCREEN_GEOM 주석)라
좁게 접힌 결과 페이지가 모자라, 재조판이 **문장 한복판에 [PAGE]를 밀어 넣었다**:

    …수많은 전장에서[PAGE]공을 세웠다.[PAGE]이윽고…      ← "공을 세웠다."만 남는 페이지

원본 JP의 페이지 구분({06}{07})과 대조하면 이런 항목만 KR 쪽 [PAGE]가 더 많다.
판정: **앞 페이지가 문장 종결부호로 끝나지 않는 [PAGE]** = 조판이 만든 가짜 → 지운다.
번역문 자체는 한 글자도 손대지 않는다(페이지 경계만 되돌린다). 지운 뒤에는
reinsert가 새 16칸 격자로 알아서 다시 페이지를 나눈다.

사용:
  python scripts/fix_fullscreen_pages.py            # 검사만(dry-run)
  python scripts/fix_fullscreen_pages.py --apply    # 백업 후 워크시트에 반영
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kr_markup as M                                    # noqa: E402
import reinsert_text as R                                # noqa: E402

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
TARGET_LEAVES = {R.COND_LEAF, R.END_LEAF}
# 문장이 끝났다고 볼 종결부호(반각/전각, 닫는 따옴표·괄호가 뒤따라도 인정)
SENT_END = re.compile(r"[.!?。．！？…‥](?:[」』\"'\)\]】〉》]|\s)*$")


def leaves_of(entry):
    out = set()
    for _id in entry["ids"]:
        p = [int(x) for x in _id.split(":")[1].split("#")[0].split("/")]
        if len(p) >= 3:
            out.add((p[1], p[2]))
    return out


def strip_split_pages(kr, budget):
    """문장을 가르는 [PAGE]를 최대 `budget`개까지 제거. 반환 (새 kr, 지운 개수).

    ★ budget = KR 페이지 수 - JP 페이지 수 (원문보다 많은 만큼만 지운다).
    원문 자체가 종결부호 없이 페이지를 넘기는 자리가 있기 때문이다 —
    `…傷を悪化させてしまう{06}{07}雨の中、…`(L1:17/2/9#45)에는 「。」가 없다.
    문장 종결부호만 보고 지우면 이 **정상 페이지 구분까지 없애** 두 문장이 붙는다.
    """
    parts = kr.split("[PAGE]")
    out = [parts[0]]
    removed = 0
    for nxt in parts[1:]:
        prev_vis = re.sub(r"\[[^\]]*\]", " ", out[-1]).rstrip()
        if removed < budget and prev_vis and not SENT_END.search(prev_vis):
            out[-1] = out[-1].rstrip() + " " + nxt.lstrip()   # 페이지 경계 해제
            removed += 1
        else:
            out.append(nxt)
    return "[PAGE]".join(out), removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    ws = json.load(open(WS_PATH, encoding="utf-8"))
    hits, failed = [], []
    for e in ws:
        fs = leaves_of(e) & TARGET_LEAVES
        if not fs or not e.get("kr", "").strip():
            continue
        # ⚠ manual_layout 은 건너뛰지 않는다. 이 두 리프의 플래그는 사람이 검수툴에서
        # 손으로 잡은 게 아니라 세션21 restyle_dialogue.py 가 **14칸 지오메트리로**
        # 일괄 재조판하며 자동으로 단 것이다((2,6) 139/140 · (2,9) 50/50).
        # 게다가 restyle 자신의 규칙 5번이 "문장 중간에 페이지가 넘어가면 [PAGE]를 뺀다"이므로
        # 여기 남은 문장 가르는 [PAGE]는 14칸에서 자리가 없어 어쩔 수 없이 남은 잔재다.
        budget = e["kr"].count("[PAGE]") - e["jp"].count("{06}{07}")
        if budget <= 0:
            continue
        new_kr, removed = strip_split_pages(e["kr"], budget)
        if not removed:
            continue
        # 새 지오메트리로 조판이 되는지 검증한 뒤에만 채택한다.
        w = min(R.FULLSCREEN_GEOM[lf][0] for lf in fs)
        ml = min(R.FULLSCREEN_GEOM[lf][1] for lf in fs)
        try:
            fixed = M.rewrap_markup(new_kr, width=w, max_lines=ml, space_cells=0.5,
                                    absorb=False, reflow=fs <= R.FULLSCREEN_REFLOW)
            pieces = M.parse_markup(fixed, absorb=False)
            if M.max_line_width(pieces) > w:
                raise ValueError(f"line > {w} 칸")
            if M.max_page_lines(pieces) > ml:
                raise ValueError(f"page > {ml} lines")
        except Exception as ex:
            failed.append((e["ids"][0], str(ex)[:40]))
            continue
        hits.append((e, new_kr, removed, fixed))

    print(f"가짜 [PAGE] 제거 대상 {len(hits)}항목 (검증 실패 {len(failed)})")
    for e, new_kr, removed, fixed in hits:
        print(f"--- {e['ids'][0]}  (-{removed} PAGE)")
        print(f"    이전: {e['kr']}")
        print(f"    이후: {new_kr}")
        print(f"    조판: {fixed}")
    for i, why in failed:
        print(f"  ! {i}: {why}")

    if not a.apply:
        print("\n(dry-run — 반영하려면 --apply)")
        return
    if not hits:
        return
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{WS_PATH}.bak_{stamp}"
    shutil.copy2(WS_PATH, bak)
    for e, new_kr, _r, _f in hits:
        e["kr"] = new_kr
    with open(WS_PATH, "w", encoding="utf-8") as f:
        json.dump(ws, f, ensure_ascii=False, indent=1)
    print(f"\n반영 완료 {len(hits)}항목. 백업: {os.path.basename(bak)}")


if __name__ == "__main__":
    main()
