#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kr_names.py — `[NAME:xx]` 토큰이 런타임에 펼쳐질 **실제 이름의 칸수**를 구한다.

조판기는 지금까지 이름 변수를 `NAME_WIDTH_EST = 4칸`으로 뭉뚱그려 잡았다. 실측해 보면
실제 이름은 **1~6칸**으로 흩어져 있어(2칸 1093회·3칸 1302회·5칸 297회·6칸 18회) 양쪽으로
다 틀린다 — 짧은 이름에선 한두 칸을 헛되게 잡아먹어 줄이 일찍 접히고, 긴 이름
(베른하르트·에그베르트·다크프린세스)에선 **모자라서 실제로 창을 넘긴다**(세션23 실측 62줄).

★ 매핑 정본(세션22): `{09 XX}` = 이름 리프 `(block,2,1)`의 **세그먼트 #(XX+1)**.
  즉 `[NAME:04]` → 세그먼트 5 → L2 헤인 / L1 제시카.

★ 세션23 실측: **이름표는 블록이 달라도 내용이 같다**(같은 게임 안에서 (tag,seg) 171조합
  전부 단일 값). 그래서 게임(L1/L2)당 표 하나면 충분하고, dedup으로 한 항목이 여러 블록에
  쓰여도 폭이 갈리지 않는다. ⚠ 이 전제가 깨지면(블록마다 다른 이름표) 항목별 최댓값을
  써야 한다 — `check_uniform()`이 그걸 검사한다.

`[WAIT]`(`{02}`)은 여기서 다루지 않는다. 플레이어명/아이템명이 들어가는 **진짜 런타임
변수**라 조판 시점에 알 수 없고 계속 추정값을 쓴다.
"""
import re
import unicodedata

NAME_LEAF = (2, 1)
_MARKUP = re.compile(r"\[[^\]]*\]")


def _cells(s):
    """이름 문자열의 칸수. 전각(한글/한자/가나)=1칸, 반각(ASCII·공백)=0.5칸."""
    return sum(1.0 if unicodedata.east_asian_width(c) in "WF" else 0.5 for c in s)


cells = _cells          # public alias — 이름 문자열의 칸수


def _iter_name_segments(ws):
    """워크시트에서 이름 리프 세그먼트를 (tag, block, seg, 이름) 로 흘려준다."""
    for e in ws:
        text = _MARKUP.sub("", e.get("kr", "") or e.get("jp", "") or "")
        if not text:
            continue
        for _id in e["ids"]:
            tag, rest = _id.split(":")
            path_s, seg_s = rest.split("#")
            path = [int(x) for x in path_s.split("/")]
            if len(path) == 3 and tuple(path[1:]) == NAME_LEAF:
                yield tag, path[0], int(seg_s), text


def name_table(ws):
    """{tag: {세그먼트번호: 이름}} — 블록을 가로질러 합친 게임별 이름표."""
    out = {}
    for tag, _blk, seg, text in _iter_name_segments(ws):
        out.setdefault(tag, {})[seg] = text
    return out


def width_map(ws):
    """{tag: {xx: 칸수}} — `[NAME:xx]`의 xx를 바로 찾는 폭 표(xx = 세그먼트-1)."""
    return {tag: {seg - 1: _cells(nm) for seg, nm in segs.items() if seg >= 1}
            for tag, segs in name_table(ws).items()}


def check_uniform(ws):
    """블록마다 이름이 갈리는 (tag,seg)를 찾아 돌려준다(비었으면 전제 성립)."""
    seen = {}
    bad = {}
    for tag, _blk, seg, text in _iter_name_segments(ws):
        prev = seen.setdefault((tag, seg), text)
        if prev != text:
            bad.setdefault((tag, seg), {prev}).add(text)
    return bad


if __name__ == "__main__":
    import collections
    import json
    import os
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ws = json.load(open(os.path.join(ROOT, "build", "worksheet_dedup_final.json"),
                        encoding="utf-8"))
    bad = check_uniform(ws)
    print("블록별 이름 불일치:", len(bad), "(0이어야 게임당 표 1개로 충분)")
    for k, v in list(bad.items())[:10]:
        print("  ", k, sorted(v))
    for tag, m in sorted(width_map(ws).items()):
        dist = collections.Counter(m.values())
        print(f"{tag}: {len(m)}개 · 폭 분포 " +
              " ".join(f"{k:g}칸:{v}" for k, v in sorted(dist.items())))
