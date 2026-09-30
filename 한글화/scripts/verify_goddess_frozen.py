#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_goddess_frozen.py — 여신(루시리스) 블록이 **세션23 이전 조판 그대로**인지 증명한다.

세션21 사용자 확정 규칙 ⑤ = 여신 블록(`L1:20`/`L2:98`) 전면 동결. 세션23에 (2,6) 지오메트리를
바꾸면서 이 블록의 튜토리얼까지 재조판됐고(사용자 지적), `reinsert_text.GODDESS_BLOCKS`로
되돌렸다. 이 스크립트는 그 되돌림이 실제로 먹었는지 **디스크 바이트로** 확인한다.

방법: 워크시트의 여신 블록 항목을 **세션23 이전 파라미터**로 다시 인코딩해, 빌드된 디스크의
같은 세그먼트와 비교한다. 글리프 코드는 폰트 표에 의존하므로 **제어 바이트(<0x20)만** 뽑아
비교한다 — 조판 구조(줄바꿈 {08} · 페이지 {06}{07} · 반각공백 {01} · 색코드)의 지문이다.

  python scripts/verify_goddess_frozen.py
"""
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
import kr_markup as M                                   # noqa: E402
import kr_render                                        # noqa: E402
import reinsert_text as R                               # noqa: E402
import scen_tool                                        # noqa: E402

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
TRACK = os.path.join(ROOT, "build", "disc-krpoc", "track1.bin")
OLD_W, OLD_ML = 14, 3                    # 세션23 이전: 대사 박스 지오메트리
_MARKUP = re.compile(r'\[(NAME|MTE|NL|PAGE|WAIT|C|RAW):?')


def space_of(e, tag):
    """reinsert와 같은 규칙: UI 리프 (2,0)은 전각 space(0x8140), 그 외는 파일 기본(반각 {01})."""
    locs = [tuple(int(x) for x in i.split(":")[1].split("#")[0].split("/")) for i in e["ids"]]
    if any(p[1:3] == R.UI_LEAF for p in locs):
        return M.FW_SPACE
    return R.FILES[tag]["space"]


def old_pieces(e, space):
    """세션23 이전 reinsert가 이 항목에 만들던 encode-pieces를 그대로 재현.

    당시 경로: is_narr=False(전체화면 리프 목록에 (2,6)/(2,9)가 없었다) → absorb 계열은
    대사 박스 규칙을 탄다. is_dialogue(=모든 위치가 (2,5))이고 여신 박스 플래그가 없으면
    2페이지+ 4줄·흡수줄 없음, 그 외에는 흡수줄 있음·균일 줄수. 이름 폭은 추정 4칸."""
    locs = [tuple(int(x) for x in i.split(":")[1].split("#")[0].split("/")) for i in e["ids"]]
    is_dialogue = all(p[1:3] == R.DLG_LEAF for p in locs)
    goddess_box = bool(e.get("absorb_box"))
    if is_dialogue and not goddess_box:
        page2, absorb = R.DLG_PAGE2_LINES, False
    else:
        page2, absorb = None, True
    reflow = is_dialogue and not e.get("manual_layout")
    sentence = bool(e.get("sentence_layout"))
    sc = 0.5 if space == M.HW_SPACE else 1.0
    if _MARKUP.search(e["kr"]):
        fixed = M.rewrap_markup(e["kr"], width=OLD_W, max_lines=OLD_ML, space_cells=sc,
                                absorb=absorb, reflow=reflow, page2_lines=page2,
                                sentence_pages=sentence)      # name_w 없음 = 추정 4칸
        return M.parse_markup(fixed, space=space, absorb=absorb)
    return kr_render.render_segment(e["kr"], width=OLD_W, window_lines=OLD_ML,
                                    space=space, absorb=absorb, page2_lines=page2,
                                    sentence_pages=sentence)


def ctrl_fingerprint_pieces(pieces):
    out = bytearray()
    for kind, val in pieces:
        if kind == "raw":
            out.extend(b for b in val if b < 0x20)
    return bytes(out)


def ctrl_fingerprint_bytes(seg):
    """디스크 세그먼트의 제어 바이트 지문. ⛔ `09 XX`(이름)·`04 XX`(MTE)의 **인자**를
    제어코드로 세면 안 된다 — 세션23에 `[NAME:08]`의 인자가 개행으로 오독됐다."""
    out = bytearray()
    i = 0
    while i < len(seg):
        c = seg[i]
        if c in (0x09, 0x04) and i + 1 < len(seg):
            out.append(c); i += 2; continue
        if c < 0x20:
            out.append(c)
        i += 2 if c >= 0x80 else 1
    return bytes(out)


def main():
    ws = json.load(open(WS_PATH, encoding="utf-8"))
    d = disc_tool.Disc(TRACK)
    trees = {tag: scen_tool.parse(d.read_file(f["scen_lba"], f["alloc"]))
             for tag, f in R.FILES.items()}
    total = same = 0
    bad = []
    for e in ws:
        if not e.get("kr", "").strip():
            continue
        for _id in e["ids"]:
            tag, rest = _id.split(":")
            path_s, seg_s = rest.split("#")
            path = tuple(int(x) for x in path_s.split("/"))
            if (tag, path[0]) not in R.GODDESS_BLOCKS:
                continue
            node = trees[tag]
            for i in path:
                node = node.children[i]
            segs = node.raw.split(b"\x00")
            si = int(seg_s)
            if si >= len(segs):
                continue
            total += 1
            exp = ctrl_fingerprint_pieces(old_pieces(e, space_of(e, tag)))
            got = ctrl_fingerprint_bytes(segs[si])
            if exp == got:
                same += 1
            elif len(bad) < 10:
                bad.append((_id, exp.hex(), got.hex(), e["kr"][:50]))
    print(f"여신 블록 {sorted(R.GODDESS_BLOCKS)} — 검사 세그먼트 {total}개")
    print(f"  세션23 이전 조판과 일치 {same} · 불일치 {total - same}")
    for b in bad:
        print(f"   ! {b[0]}\n      기대 {b[1]}\n      실제 {b[2]}\n      {b[3]}")
    if total and same == total:
        print("  ✅ 동결 확인 — 줄바꿈/페이지 구조가 세션23 이전과 완전히 동일하다.")
    return 0 if total and same == total else 1


if __name__ == "__main__":
    sys.exit(main())
