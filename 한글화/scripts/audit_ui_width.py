#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_ui_width.py — UI 리프 `(block,2,0)` 의 한글이 원문보다 넓은 항목을 뽑는다.

  python scripts/audit_ui_width.py            # 'KR > JP' 목록
  python scripts/audit_ui_width.py --all      # 전 항목 폭 비교

원본 JP SCEN(**MTE 전개 후**) ↔ 빌드된 디스크 바이트를 같은 자로 잰다.
칸수: 2바이트 코드 = 1칸 · 1바이트 문자 = 0.5칸 · 제어코드 = 0칸 · `{09 XX}`(이름) = 4칸 추정.

⚠ **"원문보다 넓다 ≠ 무조건 깨짐"**(세션19 규칙). 창이 원문 길이로 코드에 고정된 자리에서만
  넘친다(세이브 결과창 8칸이 그 실증). 이 목록은 **후보**이고 실기 확인이 최종이다.
⚠ JP는 반드시 MTE를 전개하고 재라 — 안 하면 원문이 짧게 나와 오탐이 쏟아진다.
⚠ 워크시트 문자열로 세지 마라 — UI 리프는 재삽입 때 반각 space가 **전각(1칸)** 이 된다.
   폭은 반드시 **디스크 바이트**로 재고, 사람이 읽을 텍스트만 워크시트에서 가져온다.
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
sys.path.insert(0, HERE)
import disc_tool                                        # noqa: E402
import scen_text                                        # noqa: E402
import scen_tool                                        # noqa: E402
import reinsert_text as R                               # noqa: E402

TRACK = os.path.join(ROOT, "build", "disc-krpoc", "track1.bin")
WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
UI_LEAF = (2, 0)
ARG_CODES = {0x04, 0x09}      # 뒤에 1바이트 인자가 붙는 제어코드 (MTE / 이름)


def cells(seg):
    """세그먼트 바이트 -> 칸수. MTE는 미리 전개돼 있어야 한다."""
    w, i, n = 0.0, 0, len(seg)
    while i < n:
        c = seg[i]
        if c in ARG_CODES and i + 1 < n:
            w += 4 if c == 0x09 else 0        # {09 XX} 이름 변수는 추정 4칸
            i += 2
        elif c < 0x20:
            i += 1
        elif c < 0x80:
            w += 0.5
            i += 1
        else:
            w += 1.0
            i += 2
    return w


def ui_segments(tree):
    """{(block, seg#): MTE 전개된 바이트} — path[1:3] == (2,0) 리프."""
    out = {}
    for path, leaf in scen_tool.iter_leaves(tree):
        if tuple(path[1:3]) != UI_LEAF:
            continue
        d = scen_text.get_block_dict(tree, path[0])
        for i, seg in enumerate(leaf.raw.split(b"\x00")):
            out[(path[0], i)] = scen_text.expand_mte(seg, d) if d else seg
    return out


def ws_index():
    m = {}
    with open(WS_PATH, encoding="utf-8") as f:
        for e in json.load(f):
            for i in e["ids"]:
                m[i] = e
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="넓어지지 않은 항목도 전부")
    a = ap.parse_args()

    wsmap = ws_index()
    disc = disc_tool.Disc(TRACK)
    for tag, cfg in R.FILES.items():
        jp_path = os.path.join(ROOT, "original", cfg["scen"])
        with open(jp_path, "rb") as f:
            jp = ui_segments(scen_tool.parse(f.read()))
        kr = ui_segments(scen_tool.parse(disc.read_file(cfg["scen_lba"], cfg["alloc"])))

        seen, rows, total = set(), [], 0
        for key in sorted(set(jp) & set(kr)):
            j, k = jp[key], kr[key]
            if not j.strip(b"\x00") or not k.strip(b"\x00"):
                continue
            total += 1
            e = wsmap.get("%s:%d/2/0#%d" % (tag, key[0], key[1]))
            dedup = (e["jp"], e["kr"]) if e else (bytes(j), bytes(k))
            if dedup in seen:                 # 블록마다 반복되는 같은 문자열은 한 번만
                continue
            seen.add(dedup)
            wj, wk = cells(j), cells(k)
            if a.all or wk > wj:
                rows.append((wk - wj, wj, wk, key[1],
                             e["jp"] if e else j.decode("cp932", "replace"),
                             e["kr"] if e else "?"))
        rows.sort(key=lambda r: (-r[0], -r[2]))
        print("=" * 78)
        print("%s — UI 고유 %d종(세그먼트 %d) · %s %d건"
              % (tag, len(seen), total, "전체" if a.all else "한글 > 원문", len(rows)))
        print("=" * 78)
        for dw, wj, wk, seg, jt, kt in rows:
            print("  #%-4d JP %4.1f -> KR %4.1f (%+.1f)   %s   →   %s"
                  % (seg, wj, wk, dw, jt.replace("\n", "/"), kt.replace("\n", "/")))


if __name__ == "__main__":
    main()
