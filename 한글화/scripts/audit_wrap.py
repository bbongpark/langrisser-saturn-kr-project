#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_wrap.py — **어절이 잘못 끊긴 줄**을 실제 조판에서 찾는다.

  python scripts/audit_wrap.py L2 1      # 한 시나리오
  python scripts/audit_wrap.py L2        # 게임 전체 요약
  python scripts/audit_wrap.py           # L1+L2 전체 요약
  python scripts/audit_wrap.py L2 1 -k 의존명사   # 규칙별로만

게임 엔진은 자동 줄바꿈을 하지 않으므로 줄바꿈은 전부 우리 조판기가 만든다. 그런데 한국어는
**띄어쓰기 자리라고 다 끊어도 되는 게 아니다** — 관형형과 의존명사, 부정 부사와 용언처럼
한 덩어리로 읽히는 쌍을 가르면 눈에 걸린다.

★ 고치는 방법은 `[NL]`을 손으로 박는 게 아니라 **문장을 다듬어 워드랩 위치를 옮기는 것**이다
  (세션21 규칙 ②). 한 어절만 줄이거나 늘리면 대개 해결된다.

검출 규칙(줄 끝 → 다음 줄 머리):
  의존명사   관형형(-ㄹ/-ㄴ/-는/-던) → 수·것·게·줄·리·데·바·뿐·때·터·테니·텐데·듯·척·만큼…
  부정부사   안·못·잘·더·좀·꼭·다시 → (용언)
  관형사     이·그·저·한·두·새·온갖·모든 → (체언)
  경칭       (이름) → 씨·님·양·군·경·전하
  보조용언   -어/-아/-여 → 주다·드리다·보다·버리다·가다·오다·두다·놓다
  외톨이줄   페이지 마지막 줄이 3칸 이하로 혼자 남음
⚠ 후보 목록이다. 원문이 강제한 줄바꿈이나 의도적 호흡은 사람이 판단한다.
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

BOUND_NOUNS = ("수", "것", "게", "거", "걸", "줄", "리", "데", "바", "뿐", "지", "때",
               "터", "테니", "텐데", "듯", "척", "만큼", "대로", "채", "셈", "법",
               "나위", "따름", "즈음", "무렵", "겸", "김")
ADV_NEG = ("안", "못", "잘", "더", "좀", "꼭", "다시", "덜", "막")
DETERMINER = ("이", "그", "저", "한", "두", "세", "네", "새", "온갖", "모든", "각", "전",
              "무슨", "어떤", "어느", "여러", "몇")
# ⚠ 폐하·전하·각하·공 은 **독립 명사**라 접미 경칭이 아니다 — 넣으면 "…하지. / 폐하의 뜻"
#   같은 정상 줄바꿈이 전부 오탐으로 잡힌다(세션24 실측).
HONORIFIC = ("씨", "님", "양", "군", "경")
AUX_VERB = ("주", "드리", "보", "버리", "가", "오", "두", "놓", "지", "대", "내", "말")
_ADNOM_TAIL = ("는", "던", "을", "은", "ㄹ")


def _last_word(line):
    w = line.strip().split(" ")
    return w[-1] if w and w[-1] else ""


def _first_word(line):
    w = line.strip().split(" ")
    return w[0] if w and w[0] else ""


def _is_adnominal(word):
    """관형사형(-ㄹ/-ㄴ/-는/-던)으로 끝나는가."""
    if not word:
        return False
    c = word[-1]
    if c in ("는", "던"):
        return True
    if not ("가" <= c <= "힣"):
        return False
    jong = (ord(c) - 0xAC00) % 28
    return jong in (4, 8)          # ㄴ, ㄹ


def _starts_with(word, cands):
    for c in cands:
        if word.startswith(c):
            rest = word[len(c):]
            if not rest or not ("가" <= rest[0] <= "힣") or rest[0] in "은는이가을를의도만":
                return c
    return None


def _connective(word):
    """-어/-아/-여 로 끝나 보조용언을 부르는 형태인가."""
    if not word or not ("가" <= word[-1] <= "힣"):
        return False
    c = ord(word[-1]) - 0xAC00
    jung, jong = (c // 28) % 21, c % 28
    return jong == 0 and jung in (4, 0, 6)      # ㅓ, ㅏ, ㅕ (받침 없음)


def check_pair(prev, nxt):
    """(앞줄, 뒷줄) -> 규칙명 | None"""
    a, b = _last_word(prev), _first_word(nxt)
    if not a or not b:
        return None
    if _is_adnominal(a) and _starts_with(b, BOUND_NOUNS):
        return "의존명사"
    if a in ADV_NEG:
        return "부정부사"
    if a in DETERMINER:
        return "관형사"
    if _starts_with(b, HONORIFIC) and len(b) <= 3:
        return "경칭"
    if _connective(a) and _starts_with(b, AUX_VERB):
        return "보조용언"
    return None


def analyse(entry, tag):
    """[(규칙, 앞줄, 뒷줄)] — 실제 조판에서 걸린 곳."""
    g = D.geometry(entry, tag)
    fixed = M.rewrap_markup(entry.get("kr", ""), width=g["w"], max_lines=g["ml"],
                            space_cells=g["sc"], absorb=g["absorb"], reflow=g["reflow"],
                            page2_lines=g["page2"], sentence_pages=g["sentence"],
                            name_w=g["name_w"], wait_w=g["wait_w"])
    out = []
    for page in fixed.split("[PAGE]"):
        lines = [re.sub(r"\[C:[0-9a-fA-F]{2}\]", "", l).strip()
                 for l in page.split("[NL]")]
        lines = [l for l in lines if l]
        for i in range(len(lines) - 1):
            r = check_pair(lines[i], lines[i + 1])
            if r:
                out.append((r, lines[i], lines[i + 1]))
        # 외톨이 줄: 마지막 줄이 3칸 이하로 혼자 남음
        if len(lines) >= 2:
            w = M.max_line_width(M.parse_markup(lines[-1]), g["name_w"], g["wait_w"])
            if w <= 3.0:
                out.append(("외톨이줄", lines[-2], lines[-1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?")
    ap.add_argument("block", nargs="?", type=int)
    ap.add_argument("-k", "--kind", help="규칙명으로 걸러 보기")
    a = ap.parse_args()

    ws = D.load()
    D.NAME_W = kr_names.width_map(ws)
    names_all = D.name_tables(ws)
    ttl = D.titles(ws)

    hits = collections.defaultdict(list)
    for e in ws:
        seen = set()
        for tag, blk, leaf, seg in D.parsed_ids(e):
            if leaf != D.DLG:
                continue
            if (a.tag and tag != a.tag) or (a.block is not None and blk != a.block):
                continue
            if (tag, blk, seg) in seen:
                continue
            seen.add((tag, blk, seg))
            for r in analyse(e, tag):
                if a.kind and r[0] != a.kind:
                    continue
                hits[(tag, blk)].append((seg, r))

    total = sum(len(v) for v in hits.values())
    if a.block is not None:
        key = (a.tag, a.block)
        names = names_all.get(a.tag, {})
        rows = sorted(hits.get(key, []))
        print("%s 블록%d 「%s」 — 어절 잘림 후보 %d건"
              % (a.tag, a.block, ttl.get(key, ""), len(rows)))
        for seg, (kind, l1, l2) in rows:
            r = lambda s: D.render(s, names, names.get(1))            # noqa: E731
            print("  #%-4d [%s]  %s / %s" % (seg, kind, r(l1), r(l2)))
        return

    print("어절 잘림 후보: 총 %d건" % total)
    kinds = collections.Counter(k for v in hits.values() for _s, (k, _a, _b) in v)
    for k, c in kinds.most_common():
        print("   %-8s %d" % (k, c))
    print()
    for key in sorted(hits):
        print("  %s 블록%-4d %3d건  「%s」" % (key[0], key[1], len(hits[key]), ttl.get(key, "")))


if __name__ == "__main__":
    main()
