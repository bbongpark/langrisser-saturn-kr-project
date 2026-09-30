#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
leaf_geometry_probe.py — **원본 JP 조판에서 리프별 창 지오메트리(폭/줄수)를 역산**한다.

이 게임의 텍스트 엔진은 자동 줄바꿈을 하지 않는다 — 원문에 `{08}`(개행)·`{06}{07}`(페이지
지우기)이 박혀 있고 엔진은 그대로 그릴 뿐이다. 즉 **원본 조판의 최장 줄 = 그 창의 실제 폭**이다.
새 리프의 지오메트리를 정할 때 에뮬레이터를 띄우기 전에 먼저 이걸 돌려라.

★ 방법 검증이 내장돼 있다: 이미 확정된 (2,5)=14칸 / (2,7)=16칸이 재현되지 않으면
  그 실행 결과 전체를 믿지 말 것(워크시트 형식이 바뀐 것이다).

사용:
  python scripts/leaf_geometry_probe.py               # 기본 리프 묶음
  python scripts/leaf_geometry_probe.py 2,6 2,9       # 리프 지정
"""
import collections
import json
import os
import re
import sys
import unicodedata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")

# ⚠ `{09:82}`(인자 있는 제어코드)와 `<a0>`(MTE 오전개 잔재)까지 반드시 걷어내야 한다.
# `\{[0-9a-f]{2,4}\}` 만 지우면 이런 줄이 21.5칸으로 잡혀 최댓값을 통째로 오염시킨다.
TOKEN = re.compile(r"\{[^}]*\}|\[[^\]]*\]|<[0-9a-fA-F]{2}>")
KNOWN = {(2, 5): 14, (2, 7): 16}          # 실기 확정값 — 방법 검증용


def cells(s):
    """토큰을 뺀 칸수. 전각=1칸, 반각=0.5칸."""
    return sum(1.0 if unicodedata.east_asian_width(c) in "WF" else 0.5
               for c in TOKEN.sub("", s))


def analyze(ws, leaf):
    widths, linecnt, worst, n = collections.Counter(), collections.Counter(), [], 0
    for e in ws:
        keys = {tuple(int(x) for x in i.split(":")[1].split("#")[0].split("/")[1:])
                for i in e["ids"]}
        if leaf not in keys:
            continue
        n += 1
        for page in re.split(r"\{06\}\{07\}", e["jp"]):
            lines = [l for l in re.split(r"\{08\}", page) if TOKEN.sub("", l).strip()]
            if lines:
                linecnt[len(lines)] += 1
            for l in lines:
                w = cells(l)
                widths[w] += 1
                worst.append((w, TOKEN.sub("", l)))
    worst.sort(key=lambda x: -x[0])
    # ★ 생짜 최댓값을 쓰면 안 된다 — 다른 리프와 dedup된 항목·오전개 잔재가 꼬리를 만든다.
    # 실제 창 폭은 원문이 **반복적으로 닿는** 값이다: 전체 줄의 0.5%(최소 3줄) 이상이
    # 걸린 폭 중 가장 큰 것을 한도로 본다. ((2,5)의 14.5칸 55회 같은 꼬리를 잘라낸다.)
    total = sum(widths.values())
    floor = max(3, total * 0.005)
    solid = [w for w, c in widths.items() if c >= floor]
    top = max(solid) if solid else (max(widths) if widths else 0)
    print(f"\n===== leaf {leaf}  (항목 {n})")
    print("  줄 폭:", " ".join(f"{k:g}:{v}" for k, v in sorted(widths.items())))
    print("  페이지당 줄수:", dict(sorted(linecnt.items())))
    print(f"  → 최장 {top:g}칸(꼬리 제외; 생최댓값 {max(widths) if widths else 0:g}) "
          f"· 페이지 최대 {max(linecnt) if linecnt else 0}줄")
    for w, l in worst[:3]:
        print(f"     {w:5g}칸  {l[:44]}")
    if leaf in KNOWN:
        ok = "OK" if top == KNOWN[leaf] else "!! 불일치 — 결과 신뢰 금지"
        print(f"  [방법 검증] 알려진 폭 {KNOWN[leaf]}칸 ↔ 측정 {top:g}칸 … {ok}")
    return top


def main():
    args = sys.argv[1:]
    leaves = ([tuple(int(x) for x in a.split(",")) for a in args] if args
              else [(2, 5), (2, 7), (2, 6), (2, 9)])
    ws = json.load(open(WS_PATH, encoding="utf-8"))
    for lf in leaves:
        analyze(ws, lf)
    print("\n⚠ 원문이 폭 한도까지 꽉 채우지 않았을 수 있으니, 이 값은 **하한**이다."
          "\n  화면 격자(셀 원점·줄 간격)까지 스크린샷으로 대조해 확정할 것"
          "\n  — 세션23 (2,6) 사례: 역산 15칸 · 격자 대조로 16칸 확정.")


if __name__ == "__main__":
    main()
