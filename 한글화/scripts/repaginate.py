#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repaginate.py — 원본(일본어) 대사의 페이지 구분을 번역문에 되살린다.

【왜 필요한가】
세션21 조판 규칙은 번역문의 `[PAGE]`를 모두 없애고 엔진의 문장 단위 페이지네이션에 맡겼다.
그런데 원본 `{06}{07}`(=페이지 넘김)은 단순 조판이 아니라 **음성 재생 구간과 동기화**되어 있다.
짧은 대사를 일부러 2~3페이지로 쪼갠 곳이 그렇다(`옛‥‥{06}{07}うっ！`). 페이지를 1장으로
당겨버리면 **음성이 나오다 중간에 끊긴다**(사용자 실플레이 보고).

그래서 **페이지 수는 원본 이상을 보장**한다. 규칙(문장 끝 줄바꿈, 문장 중간 줄바꿈 금지)은
페이지 안에서 그대로 유지된다.

【방법】
재조판 전 워크시트 백업(번역자가 원문 `{06}{07}`를 그대로 미러링해 둔 상태)을 페이지 구조의
기준으로 삼는다. 현재 kr(말투 교정까지 반영된 최신본)에 그 경계를 되찾아 넣는다.

  1. 백업 kr을 `[PAGE]`로 나눠 각 페이지의 **가시 문자열**(마크업·공백 제외)을 만든다.
  2. 현재 kr의 가시 문자열에서 각 페이지의 꼬리를 순서대로 찾아 경계 위치를 확정한다.
     (말투 교정으로 글자가 바뀐 항목은 매칭이 실패할 수 있으므로) 실패하면 **길이 비율**로
     근사 배분하는 폴백을 쓴다.
  3. 경계가 문장 경계(`[NL]`)와 맞으면 그 `[NL]`을 `[PAGE]`로 바꾼다(규칙 유지).
     문장 중간이면 — 원본이 일부러 문장을 가른 경우다 — 그 자리에 `[PAGE]`를 넣는다(음성 우선).

사용:
  python scripts/repaginate.py                 # 통계 + 샘플(기본 dry-run)
  python scripts/repaginate.py --apply
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
import kr_markup as M                                     # noqa: E402

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
# 재조판 전 백업 = 번역문이 원문 {06}{07} 구조를 그대로 갖고 있던 시점
BASE_PATH = os.path.join(ROOT, "build",
                         "worksheet_dedup_final.backup_restyle_20260729_224341.json")
DLG_LEAF, END_LEAF = (2, 5), (2, 9)
FROZEN_BLOCKS = {("L1", 20), ("L2", 98)}
_ID = re.compile(r"(L\d):(\d+)/(\d+)/(\d+)#(\d+)$")
_ATOM = M._ATOM
WIDTH, MAX_LINES, PAGE2 = 14, 3, 4


def leaf_of(ids):
    return {(int(m.group(3)), int(m.group(4))) for s in ids if (m := _ID.match(s))}


def is_frozen(ids):
    return any((m.group(1), int(m.group(2))) in FROZEN_BLOCKS
               for s in ids if (m := _ID.match(s)))


def vis_map(kr):
    """kr의 '가시 문자'(마크업 토큰·공백 제외)와 각 문자의 원문 인덱스를 돌려준다."""
    chars, pos, i = [], [], 0
    while i < len(kr):
        m = _ATOM.match(kr, i)
        if m:
            i = m.end()
            continue
        ch = kr[i]
        if not ch.isspace():
            chars.append(ch)
            pos.append(i)
        i += 1
    return "".join(chars), pos


def visible(s):
    return vis_map(s)[0]


def _insert_pages(kr, cuts):
    """가시 인덱스 경계(cuts)에서 kr에 [PAGE]를 넣는다.
    경계가 [NL] 자리면 그 [NL]을 [PAGE]로 교체하고(문장 경계 = 규칙 유지),
    아니면 그 자리에 [PAGE]를 끼운다(원본이 문장을 가른 경우 = 음성 우선)."""
    _, pos = vis_map(kr)
    out, prev = [], 0
    for c in cuts:
        at = pos[c - 1] + 1 if c > 0 else 0        # 경계 직전 가시문자의 다음 위치
        seg = kr[prev:at]
        rest = kr[at:]
        m = re.match(r"^\s*\[NL\]\s*", rest)        # 바로 뒤가 줄바꿈이면 그것을 페이지로
        if m:
            out.append(seg)
            prev = at + m.end()
        else:
            out.append(seg.rstrip())
            prev = at
            while prev < len(kr) and kr[prev] == " ":
                prev += 1
    out.append(kr[prev:])
    return "[PAGE]".join(p for p in out)


_JPCTL = re.compile(r"\{[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2})?\}")


def jp_pages(jp):
    """원문을 {06}{07} 기준으로 나눈 페이지별 '글자만' 텍스트."""
    return [_JPCTL.sub("", p).strip() for p in jp.split("{06}{07}")]


def word_bounds(kr):
    """어절 경계에 해당하는 가시 인덱스 집합. 페이지는 반드시 여기서만 끊는다 —
    비율로만 자르면 '놈들을 놓 / 치면'처럼 낱말 한복판이 갈린다(실제로 그랬다)."""
    bounds, n, i = set(), 0, 0
    while i < len(kr):
        m = _ATOM.match(kr, i)
        if m:                                        # 토큰 앞뒤도 경계로 본다
            bounds.add(n)
            i = m.end()
            continue
        if kr[i].isspace():
            bounds.add(n)
        else:
            n += 1
        i += 1
    bounds.add(n)
    return bounds


def punct_bounds(kr):
    """말줄임·쉼표 등 문장부호 **직후**의 가시 인덱스. 원문도 이런 자리에서 페이지를 끊으므로
    (`…‥‥{06}{07}だが`) 어절 경계보다 먼저 노린다 — 안 그러면 '…다니… 하지만'처럼
    접속사가 앞 페이지 끝에 남는다."""
    bounds, n, i = set(), 0, 0
    while i < len(kr):
        m = _ATOM.match(kr, i)
        if m:
            i = m.end()
            continue
        ch = kr[i]
        if not ch.isspace():
            n += 1
            if ch in "…,.!?~":
                bounds.add(n)
        i += 1
    return bounds


def _nearest(bounds, c, used, limit, tol=None):
    """c에서 가장 가까운, 아직 안 쓴 경계(tol을 주면 그 범위 안에서만)."""
    cands = [b for b in bounds if 0 < b < limit and b not in used
             and (tol is None or abs(b - c) <= tol)]
    if not cands:
        return None
    return min(cands, key=lambda b: (abs(b - c), b))


def _snap_to_sentence(kr, cur_vis, c, used):
    """가시 인덱스 c를, 가까운 문장 경계([NL])로 끌어당긴다(규칙 유지).
    너무 멀거나 이미 쓴 경계면 그대로 둔다 — 원본이 문장을 가른 자리라 음성 동기화를 우선한다."""
    _, pos = vis_map(kr)
    tol = max(3, int(len(cur_vis) * 0.18))
    best, bestd = None, tol + 1
    for m in re.finditer(r"\[NL\]", kr):
        n = sum(1 for p in pos if p < m.start())     # 그 [NL] 앞의 가시 문자 수
        if n in used or not (0 < n < len(cur_vis)):
            continue
        d = abs(n - c)
        if d < bestd:
            best, bestd = n, d
    return best if best is not None else c


def repaginate(cur_kr, base_kr, jp):
    """원본 페이지 수를 cur_kr에 복원한다.

    기준은 두 가지다. 번역자가 원문 `{06}{07}`를 미러링해 둔 항목은 **백업 kr의 페이지 구조**를
    쓰는 것이 가장 정확하고, 미러링하지 않은 항목(백업에도 [PAGE]가 없다)은 **원문 자체**의
    페이지별 길이 비율로 배분한다. 후자를 넣지 않으면 절반 이상이 복원되지 않는다."""
    if "[PAGE]" in cur_kr:                          # 이미 페이지가 있으면 손대지 않음
        return cur_kr, "haspage"
    cur_vis, _ = vis_map(cur_kr)
    if not cur_vis:
        return cur_kr, "empty"

    base_pages = base_kr.replace("\n", "[NL]").split("[PAGE]")
    need = jp.count("{06}{07}") + 1

    # ① 백업이 원문 페이지 수를 갖고 있으면, 그 페이지 꼬리로 경계를 정확히 찾는다
    if len(base_pages) >= need > 1:
        cuts, at, matched = [], 0, True
        for p in base_pages[:-1]:
            pv = visible(p)
            if not pv:
                matched = False
                break
            tail = pv[-10:]
            idx = cur_vis.find(tail, at)
            if idx < 0:
                matched = False
                break
            at = idx + len(tail)
            cuts.append(at)
        if matched and all(0 < c < len(cur_vis) for c in cuts) and cuts == sorted(set(cuts)):
            return _insert_pages(cur_kr, cuts), "matched"

    if need <= 1:
        return cur_kr, "unchanged"

    # ② 원문(또는 백업)의 페이지별 길이 비율로 배분하고, 문장 경계로 끌어당긴다
    src = jp_pages(jp)
    if len(src) != need or not any(src):
        src = [visible(p) for p in base_pages]
    lens = [max(1, len(p)) for p in src]
    total = sum(lens)
    wb, pb = word_bounds(cur_kr), punct_bounds(cur_kr)
    ptol = max(4, int(len(cur_vis) * 0.15))
    acc, cuts, used = 0, [], set()
    for L in lens[:-1]:
        acc += L
        c = round(len(cur_vis) * acc / total)
        s = _snap_to_sentence(cur_kr, cur_vis, c, used)   # ① 문장 경계 우선
        if s in used or not (0 < s < len(cur_vis)):
            s = c
        if s not in wb or s in used:
            s = (_nearest(pb, c, used, len(cur_vis), ptol)    # ② 문장부호 뒤
                 or _nearest(wb, c, used, len(cur_vis)))      # ③ 어절 경계
        if s is None:
            continue
        used.add(s)
        cuts.append(s)
    cuts = sorted(set(cuts))
    if len(cuts) < need - 1:                        # 너무 짧아 경계를 다 만들 수 없음
        return cur_kr, "tooshort"
    return _insert_pages(cur_kr, cuts), "ratio"


def check(kr):
    fixed = M.rewrap_markup(kr, width=WIDTH, max_lines=MAX_LINES, space_cells=0.5,
                            absorb=False, reflow=False, page2_lines=PAGE2,
                            sentence_pages=True)
    p = M.parse_markup(fixed, space=M.HW_SPACE, absorb=False)
    return round(M.max_line_width(p), 2), M.max_page_lines(p), fixed.count("[PAGE]") + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--samples", type=int, default=6)
    a = ap.parse_args()

    ws = json.load(open(WS_PATH, encoding="utf-8"))
    base = {x["ids"][0]: x for x in json.load(open(BASE_PATH, encoding="utf-8"))}

    changed, over, still, how = [], [], [], {}
    for e in ws:
        lf = leaf_of(e["ids"])
        if lf not in ({DLG_LEAF}, {END_LEAF}) or is_frozen(e["ids"]):
            continue
        k = e["ids"][0]
        cur = e.get("kr") or ""
        b = base.get(k, {}).get("kr") or ""
        jp = e.get("jp") or ""
        need = jp.count("{06}{07}") + 1
        if need < 2 or not cur.strip():
            continue
        new, mode = repaginate(cur, b, jp)
        how[mode] = how.get(mode, 0) + 1
        w, l, npage = check(new)
        if w > WIDTH + 1e-6 or l > max(MAX_LINES, PAGE2):
            over.append((k, w, l))
        if npage < need:
            still.append((k, need, npage))
        if new != cur:
            changed.append((k, cur, new))
            if a.apply:
                e["kr"] = new

    print(f"페이지 복원: {len(changed)}건 · 방식 {how}")
    print(f"조판 초과: {len(over)}건 · 여전히 원본보다 페이지가 적은 항목: {len(still)}건")
    for k, need, got in still[:10]:
        print(f"  [부족] {k} 원본{need}p → {got}p")
    for k, o, n in changed[:a.samples]:
        print(f"\n--- {k}\n  before: {o[:140]}\n  after : {n[:140]}")

    if a.apply:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = WS_PATH.replace(".json", f".backup_repage_{ts}.json")
        with open(bak, "w", encoding="utf-8") as f:
            json.dump(ws, f, ensure_ascii=False)
        tmp = WS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ws, f, ensure_ascii=False)
        os.replace(tmp, WS_PATH)
        print(f"\n[백업] {os.path.basename(bak)}\n[저장] {len(changed)}건 반영")


if __name__ == "__main__":
    main()
