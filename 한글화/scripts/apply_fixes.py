#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_fixes.py — 검수 교정안(JSON)을 워크시트에 반영한다.

세션21 말투·맞춤법 전수 검수의 적용 경로. 교정안 파일은 {"<id0>": "<새 kr>", ...} 형태로,
id0는 워크시트 항목의 첫 번째 id(예 "L2:18/2/5#58")다. dedup 워크시트라 한 항목을 고치면
그 텍스트가 쓰인 모든 위치에 함께 반영된다.

반영 절차(항목마다):
  1. id0로 항목을 찾고, 여신 블록(L1:20 / L2:98)이면 거부한다.
  2. 새 kr을 restyle_dialogue의 조판 규칙으로 정규화한다(문장 끝 줄바꿈 · 반각 부호).
  3. rewrap/parse로 칸수(≤14)·페이지 줄수(≤4)를 검증한다. 실패하면 그 항목은 건너뛰고 보고한다.
  4. 통과분만 워크시트에 쓰고 manual_layout/sentence_layout 플래그를 유지한다.

사용:
  python scripts/apply_fixes.py build/fixes/xxx.json            # 검증만(dry-run)
  python scripts/apply_fixes.py build/fixes/xxx.json --apply    # 백업 후 반영
"""
import argparse
import datetime
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
sys.path.insert(0, HERE)
import kr_markup as M                                   # noqa: E402
from restyle_dialogue import restyle, check, FROZEN_BLOCKS, WIDTH, MAX_LINES, PAGE2_LINES  # noqa: E402

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
_ID = re.compile(r"(L\d):(\d+)/(\d+)/(\d+)#(\d+)$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixes")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    fixes = json.load(open(a.fixes, encoding="utf-8"))
    ws = json.load(open(WS_PATH, encoding="utf-8"))
    by_id = {e["ids"][0]: (i, e) for i, e in enumerate(ws)}

    ok, bad, frozen, same = [], [], [], []
    for id0, new_kr in fixes.items():
        if id0 not in by_id:
            bad.append((id0, "id 없음"))
            continue
        i, e = by_id[id0]
        blocks = set()
        for s in e["ids"]:
            m = _ID.match(s)
            if m:
                blocks.add((m.group(1), int(m.group(2))))
        if blocks & FROZEN_BLOCKS:
            frozen.append(id0)
            continue
        styled = restyle(new_kr)
        try:
            w, l = check(styled)
        except Exception as ex:
            bad.append((id0, f"파싱 실패: {ex}"))
            continue
        if w > WIDTH + 1e-6 or l > max(MAX_LINES, PAGE2_LINES):
            bad.append((id0, f"조판 초과 {w}칸/{l}줄"))
            continue
        if styled == (e.get("kr") or ""):
            same.append(id0)
            continue
        ok.append((i, id0, e.get("kr") or "", styled))

    print(f"교정안 {len(fixes)}건 → 반영가능 {len(ok)} · 변화없음 {len(same)} · "
          f"여신동결거부 {len(frozen)} · 실패 {len(bad)}")
    for id0, why in bad:
        print(f"  [실패] {id0}: {why}")
    for id0 in frozen:
        print(f"  [거부] {id0}: 여신 블록은 동결 대상")

    if a.apply and ok:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = WS_PATH.replace(".json", f".backup_fixes_{ts}.json")
        with open(bak, "w", encoding="utf-8") as f:
            json.dump(ws, f, ensure_ascii=False)
        for i, id0, old, new in ok:
            ws[i]["kr"] = new
            ws[i]["manual_layout"] = True
            ws[i]["sentence_layout"] = True
        tmp = WS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ws, f, ensure_ascii=False)
        os.replace(tmp, WS_PATH)
        print(f"\n[백업] {os.path.basename(bak)}\n[저장] {len(ok)}건 반영")
    elif ok:
        for i, id0, old, new in ok[:10]:
            print(f"\n{id0}\n  old: {old[:110]}\n  new: {new[:110]}")
        print("\n(--apply 를 주면 실제로 반영합니다)")


if __name__ == "__main__":
    main()
