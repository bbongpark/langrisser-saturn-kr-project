#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
restyle_narration.py — 시나리오 화면(나레이션 (2,7))과 조건/튜토리얼 리프 (2,6)을
세션21 조판 규칙으로 재조판한다.

대사(restyle_dialogue.py)와 규칙은 같다 — 문장이 끝나면 줄을 바꾸고, 문장 중간에는 줄을
바꾸지 않는다. 다만 나레이션은 **구조가 있는 화면**이라 대사처럼 통째로 풀면 안 된다:

  [C:05][NL][C:05][C:05]ＳＣＥＮＡＲＩＯ−[C:03][NL][C:05][C:05][C:05]「제목」   ← 타이틀 페이지
  [PAGE][C:05]본문 문단…[NL][C:05]다음 문단…                                  ← 본문(문단마다 [C:05] 리드)
  [PAGE]＊승리조건[NL][C:05]・적 전멸[NL][C:05][NL]＊패배조건[NL][C:05]・[WAIT]의 사망

그래서 아래 줄들은 **자기 줄을 그대로 지킨다(보호줄)**:
  · `＊`/`・`로 시작하는 승리·패배 조건 목록 항목
  · 「…」 제목줄, ＳＣＥＮＡＲＩＯ 헤더줄
  · 정렬코드([C:05] 등)만 있고 글자가 없는 줄 = 문단 사이 빈 줄
보호줄이 아닌 산문만 이어 붙여 문장 단위로 다시 나눈다. 줄 앞에 정렬코드가 붙은 산문은
**새 문단의 시작**으로 보아 앞 문단과 합치지 않는다(원본의 문단 구성을 지킨다).

[PAGE]는 대사와 달리 **유지한다** — 나레이션의 페이지는 장면 전환/문단 묶음이라 연출이다.
페이지가 7줄을 넘으면 엔진이 문장 경계에서 알아서 넘긴다(sentence_pages).

⚠ 조건 항목은 "한 조건 = 여러 세그먼트"로 쪼개져 있다(`・크리스가 맵 좌상단의` + `문으로 탈출`이
별개 항목). 게임이 세로로 이어 그리므로 **합치면 안 된다** — 보호줄 규칙이 이걸 지킨다.

사용:
  python scripts/restyle_narration.py              # 통계 + 샘플(기본 dry-run)
  python scripts/restyle_narration.py --apply      # 백업 후 워크시트에 반영
"""
import argparse
import datetime
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kr_markup as M                                    # noqa: E402
from restyle_dialogue import (normalize_punct, normalize_ortho,   # noqa: E402
                              split_sentences, _CTRL_TOK, OPENERS, NOSPACE_LEAD,
                              restyle as dialogue_restyle)

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
NARR_LEAF = (2, 7)
COND_LEAF = (2, 6)
# 엔딩(캐릭터별 후일담). 조건 목록·타이틀 같은 보호 구조가 없는 순수 산문이고, 원문이
# "발디아 기사단장에[PAGE]임명된다."처럼 **문장 한복판에서 페이지를 넘긴다**(50/50 전부).
# 그래서 나레이션처럼 [PAGE]를 유지하면 갈린 문장을 되붙일 수 없다 → 대사와 똑같이
# [PAGE]까지 풀어 문장 단위로 다시 짜고, 페이지는 엔진(sentence_pages)에 맡긴다.
END_LEAF = (2, 9)
NARR_WIDTH, NARR_LINES = 16, 7          # 전체화면 나레이션 렌더러(reinsert와 동일)
COND_WIDTH, COND_LINES = 14, 3          # (2,6)은 reinsert 기본 지오메트리를 따른다
_ID = re.compile(r"(L\d):(\d+)/(\d+)/(\d+)#(\d+)$")

# 자기 줄을 지켜야 하는 줄: 조건 목록(＊ ・), 제목(「」), ＳＣＥＮＡＲＩＯ 헤더
_LIST_LEAD = re.compile(r"^(?:\[[^\]]*\])*[・＊*]")


def leaf_of(ids):
    lf = set()
    for s in ids:
        m = _ID.match(s)
        if m:
            lf.add((int(m.group(3)), int(m.group(4))))
    return lf


def _visible(s):
    return re.sub(r"\[[^\]]*\]", "", s).strip()


def is_protected(line):
    """이 줄은 합치지 않고 그대로 둔다."""
    vis = _visible(line)
    if not vis:                                  # 정렬코드만 = 문단 사이 빈 줄
        return True
    if _LIST_LEAD.match(line.lstrip()):          # ＊승리조건 / ・적 전멸
        return True
    if "「" in vis or "」" in vis or "ＳＣＥＮＡＲＩＯ" in line:
        return True
    return False


def _join(a, b):
    """산문 두 조각을 어절 경계로 잇는다(restyle_dialogue.unwrap과 같은 규칙)."""
    if not a:
        return b
    head = _CTRL_TOK.sub("", b).lstrip()
    vis_head = "" if head.startswith("[") else head[:1]
    if a[-1] in OPENERS or (vis_head and vis_head in NOSPACE_LEAD) or a[-1] == " ":
        return a + b
    return a + " " + b


def restyle_page(page):
    """한 페이지를 재조판한다. 보호줄은 그대로, 산문은 문단별로 문장 단위 재분할."""
    out, cur = [], None                       # cur = 모으는 중인 산문 문단
    for ln in page.split("[NL]"):
        s = ln.strip()
        if is_protected(s):
            if cur is not None:
                out.extend(split_sentences(cur)); cur = None
            out.append(s)
            continue
        # 정렬코드로 시작하는 산문 = 새 문단 → 앞 문단을 끊는다
        starts_new = bool(_CTRL_TOK.match(s))
        if cur is None or starts_new:
            if cur is not None:
                out.extend(split_sentences(cur))
            cur = s
        else:
            cur = _join(cur, s)
    if cur is not None:
        out.extend(split_sentences(cur))
    return "[NL]".join(out)


def restyle(kr):
    s = normalize_ortho(normalize_punct(kr.replace("\n", "[NL]")))
    return "[PAGE]".join(restyle_page(p) for p in s.split("[PAGE]"))


def check(kr, width, max_lines):
    has_markup = bool(re.search(r"\[(NAME|MTE|NL|PAGE|WAIT|C|RAW):?", kr))
    absorb = width != NARR_WIDTH               # 나레이션만 흡수줄 없음
    if has_markup:
        fixed = M.rewrap_markup(kr, width=width, max_lines=max_lines, space_cells=0.5,
                                absorb=absorb, reflow=False, sentence_pages=True)
        pieces = M.parse_markup(fixed, space=M.HW_SPACE, absorb=absorb)
    else:
        import kr_render
        pieces = kr_render.render_segment(kr, width=width, window_lines=max_lines,
                                          space=kr_render.HW_SPACE, absorb=absorb,
                                          sentence_pages=True)
    return round(M.max_line_width(pieces), 2), M.max_page_lines(pieces)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--samples", type=int, default=3)
    a = ap.parse_args()

    ws = json.load(open(WS_PATH, encoding="utf-8"))
    changed, over, untouched = [], [], 0
    for e in ws:
        lf = leaf_of(e["ids"])
        if lf == {NARR_LEAF}:
            w, ml, styler = NARR_WIDTH, NARR_LINES, restyle
        elif lf == {COND_LEAF}:
            w, ml, styler = COND_WIDTH, COND_LINES, restyle
        elif lf == {END_LEAF}:
            w, ml, styler = COND_WIDTH, COND_LINES, dialogue_restyle
        else:
            continue
        old = e.get("kr") or ""
        if not old.strip():
            continue
        new = styler(old)
        cw, cl = check(new, w, ml)
        if cw > w + 1e-6 or cl > ml:
            over.append({"id0": e["ids"][0], "kr": new, "w": cw, "lines": cl, "cap": (w, ml)})
        if new != old:
            changed.append({"id0": e["ids"][0], "old": old, "new": new})
        else:
            untouched += 1
        if a.apply:
            e["kr"] = new
            e["manual_layout"] = True
            e["sentence_layout"] = True

    print(f"나레이션(2,7)+조건/튜토리얼(2,6)+엔딩(2,9): 재조판 {len(changed)}건 · 변화없음 {untouched}건")
    print(f"조판 초과: {len(over)}건")
    for o in over[:10]:
        print(f"  [초과] {o['id0']} {o['w']}칸/{o['lines']}줄 (상한 {o['cap'][0]}칸/{o['cap'][1]}줄)")
    for c in changed[:a.samples]:
        print(f"\n--- {c['id0']}\n  before: {c['old'][:300]}\n  after : {c['new'][:300]}")

    if a.apply:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = WS_PATH.replace(".json", f".backup_narr_{ts}.json")
        with open(bak, "w", encoding="utf-8") as f:
            json.dump(ws, f, ensure_ascii=False)
        tmp = WS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ws, f, ensure_ascii=False)
        os.replace(tmp, WS_PATH)
        print(f"\n[백업] {os.path.basename(bak)}\n[저장] 반영 완료")


if __name__ == "__main__":
    main()
