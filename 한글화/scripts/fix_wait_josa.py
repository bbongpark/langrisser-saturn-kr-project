#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_wait_josa.py — [WAIT]={02} 동적 삽입의 조사 문맥별 교정.

{02}는 문맥에 따라 다른 값이 삽입된다:
  • 대사(2,5)·나레이션(2,7): **플레이어명**(Ep1 레딘/Ep2 엘윈, 둘 다 받침 ㄴ) → 받침형 조사.
    실측 확인: (2,5)/(2,7)의 [WAIT]+을/를은 모두 플레이어 목적어(엘윈을), 아이템 아님.
  • UI 메시지(2,0): **아이템/유닛명**(받침 제각각) → 단일 조사 불가. 조사를 빼 자연스럽게 재작성.

받침형: 는→은, 가→이, 를→을, 와→과 (이미 은/이/을/과인 건 유지).
"""
import os
import io, sys, json, re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
WS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "worksheet_dedup_final.json")

# (2,0) UI 아이템/유닛 메시지: 아이템명 받침 불명 → 조사 제거·재작성(josa-free).
UI_REWRITE = {
    "[WAIT]을 버립니다.": "[WAIT] 버립니다.",
    "[WAIT]을 버렸습니다.": "[WAIT] 버렸습니다.",
    "[WAIT]을[NL]손에 넣었다!": "[WAIT][NL]손에 넣었다!",
    "[WAIT]은[NL][WAIT]을[NL]장비했습니다.": "[WAIT],[NL][WAIT][NL]장비했습니다.",
    "[WAIT]을 고용할 수 있게 됐다": "[WAIT][NL]고용할 수 있게 됐다",
    "[WAIT]을 구입했습니다": "[WAIT][NL]구입했습니다",
    "[WAIT]을 매각했습니다": "[WAIT][NL]매각했습니다",
    "[WAIT]은 장비할 수 없음": "[WAIT][NL]장비할 수 없음",
    # #66 '[WAIT]의 장비', #77 '[WAIT]아이템이…', #91 '…[WAIT]에…', #52/#63/#14 은
    # 유지(의/에/인접/단독은 받침 무관하게 자연스럽거나 파편).
}

_WAIT_JOSA = {"는": "은", "가": "이", "를": "을", "와": "과"}


def leaves_of(e):
    out = set()
    for i in e["ids"]:
        m = re.match(r"L[12]:\d+/(\d+)/(\d+)#", i)
        if m:
            out.add((int(m.group(1)), int(m.group(2))))
    return out


def main(apply):
    ws = json.load(open(WS, encoding="utf-8"))
    n_ui = n_dlg = 0
    for e in ws:
        kr = e.get("kr", "")
        if "[WAIT]" not in kr:
            continue
        leaves = leaves_of(e)
        orig = kr
        if (2, 0) in leaves:
            if kr in UI_REWRITE:
                kr = UI_REWRITE[kr]
        elif any(l in ((2, 5), (2, 7)) for l in leaves):
            # player name (batchim ㄴ) → batchim josa, but only when the josa is a real
            # trailing particle (followed by space/punct/markup/end), not a noun.
            def repl(m):
                return "[WAIT]" + _WAIT_JOSA[m.group(1)]
            kr = re.sub(r"\[WAIT\]([는가를와])(?=[\s.,!?…‥」』)\]]|\[|$)", repl, kr)
        if kr != orig:
            if (2, 0) in leaves:
                n_ui += 1
            else:
                n_dlg += 1
            if (n_ui + n_dlg) <= 40:
                print("---", e["ids"][0])
                print(" 전:", orig.replace("\n", "|")[:80])
                print(" 후:", kr.replace("\n", "|")[:80])
            e["kr"] = kr
    print(f"\nUI 재작성 {n_ui}건, 대사/나레이션 [WAIT] 조사 {n_dlg}건")
    if apply:
        json.dump(ws, open(WS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("적용됨")
    else:
        print("(dry-run)")


if __name__ == "__main__":
    main("--apply" in sys.argv)
