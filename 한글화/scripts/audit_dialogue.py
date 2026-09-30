#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_dialogue.py — 대사(2,5) 말투/문체 전수 진단.

세션21 사용자 요구 "전수 검사해서 말투 어색한 부분이나 높임말이 필요한 경우 같은 걸 다 정리"의
1차 스캐너. 문맥(화자/청자)이 필요한 판단은 사람이 해야 하므로, 여기서는 문맥 없이도 근거를
댈 수 있는 것만 기계적으로 뽑아 검수 대상을 좁힌다.

검출 항목
  mixed_speech  한 항목 안에서 존댓말 종결과 반말 종결이 섞임 (가장 강한 신호)
  jp_calque     일본어 직역투 (~것이다 / ~인 것인가 / ~해 주었으면 한다 / 하는 것이 좋다 …)
  spacing       이중 공백, 부호 앞 공백, 조사 앞 공백 등 띄어쓰기 사고
  punct         부호 사고 (?. / !. / 중복 마침표 / 부호로만 된 문장)
  unsplit       문장이 안 나뉜 것으로 보이는 줄 (… 뒤에 새 문장이 이어짐)
  glued         종결부호 뒤에 공백 없이 다음 말이 붙음

사용:
  python scripts/audit_dialogue.py                     # 요약 + 항목별 개수
  python scripts/audit_dialogue.py --kind mixed_speech --limit 40
  python scripts/audit_dialogue.py --dump build/audit_dialogue.json
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
DLG_LEAF = (2, 5)
FROZEN_BLOCKS = {("L1", 20), ("L2", 98)}
_ID = re.compile(r"(L\d):(\d+)/(\d+)/(\d+)#(\d+)$")
_TOK = re.compile(r"\[[^\]]*\]")

# ── 종결 어미 ────────────────────────────────────────────────────────────────
# 존댓말(합쇼체/해요체)
POLITE = re.compile(
    r"(?:습니다|ㅂ니다|입니다|십니다|습니까|ㅂ니까|십니까|십시오|세요|셔요|어요|아요|에요|예요"
    r"|이죠|지요|군요|네요|는데요|나요|까요|거든요|잖아요|던가요|деся)$")
# 반말(해라체/해체) — 존댓말 표지와 겹치지 않는 형태만
PLAIN = re.compile(
    r"(?:는다|ㄴ다|었다|았다|겠다|한다|이다|아니다|없다|있다|같다|온다|간다|난다|든다|친다|٭"
    r"|느냐|더냐|는가|은가|을까|ㄹ까|자|거라|어라|아라|해라|마라|는군|는걸|는데|잖아|구나|누나)$")

# 일본어 직역투 (스팀판 한국어에 잘 안 나오는 형태 위주)
CALQUE = [
    (re.compile(r"인\s?것인가"), "~인 것인가 → ~인가"),
    (re.compile(r"[가-힣]는\s것이다"), "~는 것이다 → ~다"),
    (re.compile(r"것이\s?좋겠다"), "것이 좋겠다 → ~하자/~하는 게 낫다"),
    (re.compile(r"해\s?주었으면"), "~해 주었으면 한다 → ~해 다오/~해라"),
    (re.compile(r"[가-힣]지\s?않으면\s?안\s?[된되]"), "~하지 않으면 안 된다 → ~해야 한다"),
    (re.compile(r"에\s?다름\s?아니"), "~에 다름 아니다 → ~나 마찬가지다"),
    (re.compile(r"[가-힣]고\s?있는\s?것"), "~하고 있는 것 → ~하는 것"),
    (re.compile(r"[가-힣]라\s?하는\s?[것자]"), "~라 하는 것 → ~라는 것"),
    (re.compile(r"[가-힣]때문에\s?다"), "어색한 '때문에다'"),
    (re.compile(r"[가-힣]에\s?있어서[는의]?\s"), "~에 있어서 → ~에서/~에게"),
]

SPACING = [
    (re.compile(r"  +"), "이중 공백"),
    (re.compile(r"\s+[,.!?]"), "부호 앞 공백"),
    (re.compile(r"[가-힣]\s+(?:은|는|이|가|을|를|의|에|와|과|도|만|으로|로)\s"), "조사 앞 공백 의심"),
]

PUNCT = [
    (re.compile(r"\?\."), "?. 중복"),
    (re.compile(r"!\."), "!. 중복"),
    (re.compile(r"\.{2}(?!\.)"), ".. (…로 통일 필요)"),
    (re.compile(r"…\."), "….  (말줄임 뒤 마침표)"),
    (re.compile(r"[,]{2,}"), "쉼표 중복"),
]

_FINAL_ENDING = re.compile(r"(?:다|까|요|죠|군|네|냐|는가|은가|던가|인가|을까|겠나|었나|았나|구나)$")


def parse_id(s):
    m = _ID.match(s)
    return (m.group(1), int(m.group(2)), (int(m.group(3)), int(m.group(4))), int(m.group(5))) if m else None


def visible(s):
    """마크업을 '화면에 보이는 모습'으로 치환한 텍스트.

    토큰을 통째로 지우면 "있다.[NL]마셔" 가 "있다.마셔"(글자 붙음)로, "그렇지만, [NAME:06]!"
    이 "그렇지만, !"(부호 앞 공백)으로 오진된다. 줄바꿈은 공백, 이름/치환 토큰은 글자로 본다."""
    s = re.sub(r"\[(?:NL|PAGE)\]", " ", s)
    s = re.sub(r"\[(?:NAME:[0-9A-Fa-f]+|WAIT|MTE:[0-9A-Fa-f]+)\]", "○○", s)
    s = re.sub(r"\[(?:C|RAW):[0-9A-Fa-f]+\]", "", s)     # 0폭 정렬코드
    return _TOK.sub("", s).strip()


def sentences(kr):
    return [visible(s) for s in kr.split("[NL]") if visible(s)]


def speech_level(sent):
    """문장의 종결 말투: 'polite' | 'plain' | None."""
    s = re.sub(r"[\s…\"'」』）)\]”’!?.~〜]+$", "", sent)
    if not s:
        return None
    if POLITE.search(s):
        return "polite"
    if PLAIN.search(s):
        return "plain"
    return None


def audit(entry):
    kr = entry.get("kr") or ""
    hits = []
    sents = sentences(kr)
    levels = [speech_level(s) for s in sents]
    kinds = {l for l in levels if l}
    if len(kinds) > 1:
        hits.append(("mixed_speech", " / ".join(
            f"{s}[{l}]" for s, l in zip(sents, levels) if l)))
    vis = visible(kr)
    for rx, why in CALQUE:
        if rx.search(vis):
            hits.append(("jp_calque", why))
            break
    for rx, why in SPACING:
        if rx.search(vis):
            hits.append(("spacing", why))
            break
    for rx, why in PUNCT:
        if rx.search(vis):
            hits.append(("punct", why))
            break
    for ln in kr.split("[NL]"):
        v = visible(ln)
        if re.search(r"…+ +\S", v):
            stem = re.split(r"…+ ", v)[0]
            if not _FINAL_ENDING.search(re.sub(r"[\s…]+$", "", stem)):
                continue                      # 문장 중간 뜸들임 — 정상
            hits.append(("unsplit", ln))
            break
    if re.search(r"[.!?][가-힣○]", vis):
        hits.append(("glued", kr))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--dump")
    ap.add_argument("--block", help="예: L2:46")
    a = ap.parse_args()

    ws = json.load(open(WS_PATH, encoding="utf-8"))
    found = collections.defaultdict(list)
    n_target = 0
    for idx, e in enumerate(ws):
        ids = [parse_id(i) for i in e["ids"]]
        if not all(ids) or not all(i[2] == DLG_LEAF for i in ids):
            continue
        if any((i[0], i[1]) in FROZEN_BLOCKS for i in ids):
            continue
        if a.block and not any(f"{i[0]}:{i[1]}" == a.block for i in ids):
            continue
        n_target += 1
        for kind, why in audit(e):
            found[kind].append({"i": idx, "id0": e["ids"][0], "kr": e.get("kr", ""), "why": why})

    print(f"대상 대사 {n_target}건 (여신 블록 제외)")
    for k in ("mixed_speech", "jp_calque", "spacing", "punct", "unsplit", "glued"):
        print(f"  {k:13s} {len(found[k]):5d}")
    total = len({h['i'] for v in found.values() for h in v})
    print(f"  ─ 유니크 의심 항목: {total}")

    if a.kind:
        print(f"\n=== {a.kind} ===")
        for h in found[a.kind][:a.limit]:
            print(f"\n{h['id0']}")
            print(f"  kr : {h['kr']}")
            print(f"  why: {h['why']}")
    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as f:
            json.dump(found, f, ensure_ascii=False, indent=1)
        print(f"\n[dump] {a.dump}")


if __name__ == "__main__":
    main()
