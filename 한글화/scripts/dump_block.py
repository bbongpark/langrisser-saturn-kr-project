#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dump_block.py — 시나리오 블록의 대사를 진행 순서대로 덤프한다(말투·높임말 검수용).

워크시트에는 화자 정보가 없다. 말투/높임말은 "누가 누구에게" 말하는지 알아야 판단할 수 있으므로,
블록(시나리오) 안의 대사를 **세그먼트 번호 순서**로 늘어놓아 대화 흐름에서 화자를 추정한다.

사용:
  python scripts/dump_block.py L1:0              # 한 블록
  python scripts/dump_block.py L1:0 L1:1 L1:2    # 여러 블록
  python scripts/dump_block.py --list            # 블록 목록 + 대사 수
  python scripts/dump_block.py L2:46 --jp        # 일본어 원문도 함께
"""
import argparse
import collections
import json
import os
import re
import sys

# 콘솔 인코딩: sys.stdout.buffer를 TextIOWrapper로 다시 감싸면, 한 프로세스에서 두 모듈이
# 각자 감쌌을 때 먼저 만든 래퍼가 GC되며 buffer를 닫아 "I/O operation on closed file"이 난다
# (apply_fixes → restyle_dialogue import 조합에서 실제로 터졌다). reconfigure는 감싸지 않는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
_ID = re.compile(r"(L\d):(\d+)/(\d+)/(\d+)#(\d+)$")
DLG_LEAF = (2, 5)
NARR_LEAF = (2, 7)
FROZEN = {("L1", 20), ("L2", 98)}


def load():
    ws = json.load(open(WS_PATH, encoding="utf-8"))
    # (game, block) -> [(seg, entry, id0)]
    by_block = collections.defaultdict(list)
    titles = {}
    for e in ws:
        for s in e["ids"]:
            m = _ID.match(s)
            if not m:
                continue
            game, blk, leaf, seg = m.group(1), int(m.group(2)), (int(m.group(3)), int(m.group(4))), int(m.group(5))
            if leaf == DLG_LEAF:
                by_block[(game, blk)].append((seg, e, e["ids"][0]))
            elif leaf == NARR_LEAF and seg == 0:
                t = re.search(r"「([^」]*)」", e.get("kr") or "")
                if t:
                    titles[(game, blk)] = t.group(1)
    return ws, by_block, titles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("blocks", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--jp", action="store_true")
    a = ap.parse_args()

    ws, by_block, titles = load()
    if a.list or not a.blocks:
        for (g, b) in sorted(by_block, key=lambda k: (k[0], k[1])):
            mark = " [동결]" if (g, b) in FROZEN else ""
            print(f"{g}:{b:<3} {len(by_block[(g,b)]):4d}건  「{titles.get((g,b),'')}」{mark}")
        return

    for spec in a.blocks:
        g, b = spec.split(":")
        key = (g, int(b))
        rows = sorted(by_block.get(key, []), key=lambda r: r[0])
        if not rows:
            print(f"=== {spec} — 대사 없음")
            continue
        frozen = " ※여신 블록(동결)" if key in FROZEN else ""
        print(f"\n=== {spec} 「{titles.get(key,'')}」 · 대사 {len(rows)}건{frozen} ===")
        for seg, e, id0 in rows:
            shared = "" if id0.startswith(f"{spec}/") else f"  ⟨공유 {id0}⟩"
            kr = (e.get("kr") or "").replace("[NL]", " ⏎ ")
            print(f"#{seg:<4}{kr}{shared}")
            if a.jp:
                print(f"      JP: {e.get('jp','')}")


if __name__ == "__main__":
    main()
