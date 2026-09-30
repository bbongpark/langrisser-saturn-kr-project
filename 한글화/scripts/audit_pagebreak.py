#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_pagebreak.py — **페이지 경계가 원문과 어긋난 곳**을 찾는다.

  python scripts/audit_pagebreak.py L2 22    # 한 시나리오
  python scripts/audit_pagebreak.py L2       # 게임 전체
  python scripts/audit_pagebreak.py          # L1+L2 전체
  python scripts/audit_pagebreak.py L2 -n 40 # 상위 40건만

⛔ `[PAGE]`는 조판이 아니라 **음성 재생 구간의 경계**다. 페이지 **수**가 맞아도
   경계가 한 칸 밀리면 그 자리에서 음성과 자막이 어긋난다.
   `audit_pages.py` 는 페이지 수만 보므로 이 유형을 못 잡는다(세션24 실측).

실제로 나온 어긋남:
  · 원문 p3+p4를 한 페이지에 합치고 p4 자리를 `…` 하나로 채워 수만 맞춘 것
  · 다음 페이지 첫 어절을 앞 페이지 꼬리로 끌어와 문장이 페이지를 걸친 것
  · 페이지 하나가 통째로 빠지고 다른 페이지를 둘로 쪼개 수만 맞춘 것

검출법: 페이지 수가 같은 항목에 대해, 원문/번역의 **페이지별 분량 비율**을 견준다.
        한쪽이 몰려 있으면 경계가 밀린 것이다.
⚠ 후보 목록이다. 한국어가 일본어보다 짧아지는 자리도 있으니 사람이 판단한다.
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WS = os.path.join(ROOT, "build", "worksheet_dedup_final.json")

# 제어코드·구두점·공백을 지운 "알맹이" 길이만 센다
_JP_STRIP = re.compile(r"\{[^}]*\}|<[0-9a-fA-F]{2}>|[\s‥…、。！？「」・]")
_KR_STRIP = re.compile(r"\[[^\]]*\]|[\s…·、。，,.!?！？「」]")


def pages(text, strip):
    parts = re.split(r"\{06\}\{07\}", text) if strip is _JP_STRIP else text.split("[PAGE]")
    return [len(strip.sub("", p)) for p in parts]


def skew(jp, kr):
    """페이지별 분량 비율이 얼마나 어긋났나 (0=완전 일치, 1=완전히 다름)."""
    tj, tk = sum(jp), sum(kr)
    if tj == 0 or tk == 0:
        return 0.0, []
    per = [abs(a / tj - b / tk) for a, b in zip(jp, kr)]
    return sum(per) / 2, per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?")
    ap.add_argument("block", nargs="?", type=int)
    ap.add_argument("-n", "--num", type=int, default=25, help="보여줄 건수")
    ap.add_argument("-t", "--threshold", type=float, default=0.18,
                    help="이 값을 넘으면 후보 (기본 0.18)")
    a = ap.parse_args()

    ws = json.load(open(WS, encoding="utf-8"))
    hits = []
    for e in ws:
        jp, kr = e.get("jp") or "", e["kr"]
        if "{06}{07}" not in jp:
            continue
        ids = [i for i in e["ids"]
               if (not a.tag or i.startswith(a.tag + ":"))
               and (a.block is None or re.match(r"^\w+:%d/" % a.block, i))]
        if not ids:
            continue
        pj, pk = pages(jp, _JP_STRIP), pages(kr, _KR_STRIP)
        if len(pj) != len(pk) or len(pj) < 2:
            continue                      # 페이지 수가 다른 건 audit_pages.py 담당
        s, per = skew(pj, pk)
        if s >= a.threshold:
            hits.append((s, ids[0], pj, pk, per))

    hits.sort(reverse=True)
    where = "%s 블록%s" % (a.tag or "L1+L2", a.block if a.block is not None else "전체")
    print("%s — 페이지 경계가 어긋난 후보 %d건" % (where, len(hits)))
    for s, idd, pj, pk, per in hits[:a.num]:
        worst = max(range(len(per)), key=lambda i: per[i]) + 1
        print("  %-20s 어긋남 %.2f  (p%d 부근)" % (idd, s, worst))
        print("      JP %s" % " / ".join("%d" % x for x in pj))
        print("      KR %s" % " / ".join("%d" % x for x in pk))
    if len(hits) > a.num:
        print("  … 그 밖 %d건 (-n 으로 더 보기)" % (len(hits) - a.num))


if __name__ == "__main__":
    main()
