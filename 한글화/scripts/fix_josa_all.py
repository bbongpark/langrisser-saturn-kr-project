#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_josa_all.py — [NAME:XX] 및 리터럴 고유명사 뒤 조사/서술격 allomorph 전수 교정.

이름 뒤에 '붙어서' 오는 조사·서술격 어미의 형태(받침 유무)를 실제 이름 기준으로 맞춘다.
[NAME:XX]는 같은 블록 (block,2,1) 세그먼트 XX(hex)로 해석(블록별 일관 확인됨).
리터럴 고유명사(스팀 이름/지명)도 동일 규칙으로 처리하되, 조사 뒤가 '경계'(공백/문장부호/
개행/마크업/끝)일 때만 손대 오탐을 막는다([NAME]은 변수라 붙은 형태소는 곧 조사이므로
경계 요건 없이 처리).

받침: has=최종 자모 받침 유무, rieul=ㄹ받침. dry-run은 --apply 없이 diff만 출력.
"""
import os
import io, sys, json, re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
WS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "worksheet_dedup_final.json")


def batchim(name):
    for ch in reversed(name):
        if 0xAC00 <= ord(ch) <= 0xD7A3:
            return (ord(ch) - 0xAC00) % 28
    return None


# boundary AFTER a trailing particle: end / space / sentence-or-clause punctuation /
# markup token. Used to avoid mangling a following NOUN/VERB that merely starts with a
# josa syllable (e.g. "[NAME]가슴" must stay — 가슴 is a noun, not name+가).
_B = r"(?=[\s.,!?。、…‥」』）)\]％〜~·]|\[|$)"
# 과/와 뒤에 올 수 있는 연결 보조사(와도/과의/와는/과만…) 또는 일반 경계
_AUX = r"(?=도|의|는|만|[\s.,!?。、…‥」』）)\]％〜~·]|\[|$)"

# 이름 바로 뒤 형태소를 (has, rieul)에 맞는 형태로. 순서 중요(긴 것/복합 먼저).
# 각 항목: (정규식, lambda has,rieul -> 치환 템플릿(\1 그룹 참조 가능)).
_RULES = [
    # 서술격/인용 복합 (이-계열): 받침 있으면 '이'+X, 없으면 X
    (re.compile(r"이?(야말로)"), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(다)(?=[\s.!?」』\]]|$|만|고|는)"), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(야)" + _B), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(여)" + _B), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(냐)"), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(라)(?=고|는|서|도|[\s.!?」』\]]|$)"), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(란)" + _B), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(나)" + _B), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(랑)"), lambda h, r: ("이" if h else "") + r"\1"),
    (re.compile(r"이?(든)"), lambda h, r: ("이" if h else "") + r"\1"),
    # 방향격 (으)로: 받침 있고 ㄹ아니면 '으로', ㄹ받침/받침없음이면 '로'
    (re.compile(r"으?(로)(?=[\s.!?」』\]]|$|는|도|만|의|서)"),
     lambda h, r: ("으로" if (h and not r) else "로")),
    # 호격 아/야 (경계 뒤에서만)
    (re.compile(r"[아야]" + _B), lambda h, r: "아" if h else "야"),
    # 단순 조사 — 반드시 경계 뒤에서만(뒤에 한글 명사/동사면 손대지 않음)
    (re.compile(r"[은는]" + _B), lambda h, r: "은" if h else "는"),
    (re.compile(r"[이가]" + _B), lambda h, r: "이" if h else "가"),
    (re.compile(r"[을를]" + _B), lambda h, r: "을" if h else "를"),
    # 과/와 — 경계 또는 연결 보조사(도/의/는/만) 앞에서 교정(와도/과의…)
    (re.compile(r"[과와]" + _AUX), lambda h, r: "과" if h else "와"),
]


def normalize_after(text, has, rieul):
    """text가 이름 직후 문자열일 때, 선두 조사 allomorph 하나를 교정한 text 반환."""
    for rx, repl in _RULES:
        m = rx.match(text)
        if m:
            new = m.expand(repl(has, rieul)) if "\\1" in repl(has, rieul) else repl(has, rieul)
            return new + text[m.end():]
    return text


def load_names(ws):
    # CRITICAL: {09 XX} (markup [NAME:XX]) resolves to name-leaf segment #(XX+1), NOT
    # #XX — reverse-engineered from the LANG1.BIN {09} handler (@0x0601bfd0) and
    # cold-boot confirmed (Ep1 {09:06}->#7 호킹, {09:01}->#2 나암; Ep2 {09:01}->#2
    # 리아나, the player name being the dynamic {02}/[WAIT], not {09}). We key names
    # here by the RESOLVED index so callers look up by the raw XX directly.
    names = {}
    for e in ws:
        for i in e["ids"]:
            m = re.match(r"(L[12]):(\d+)/2/1#(\d+)$", i)
            if m and e.get("kr", "").strip():
                resolved = int(m.group(3))
                if resolved >= 1:            # store as XX = resolved-1
                    names[(m.group(1), int(m.group(2)), resolved - 1)] = e["kr"].strip()
    return names


def main(apply):
    ws = json.load(open(WS, encoding="utf-8"))
    names = load_names(ws)
    # literal proper nouns
    steam = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "steam_charnames.json"),
                            encoding="utf-8"))
    literals = set()
    for jp, kr in steam.items():
        if kr and len(kr) >= 2 and re.fullmatch(r"[가-힣]+", kr):
            literals.add(kr)
    literals |= {"다르시스", "발디아", "에스톨", "살라스", "벨제리아", "엘사리아",
                 "랑그릿사", "알하자드", "칼자스"}
    NAME_RX = re.compile(r"\[NAME:([0-9a-fA-F]{2})\]")   # 대문자 표기도 잡는다(세션24)
    changed = 0
    for e in ws:
        kr = e.get("kr", "")
        if not kr.strip():
            continue
        blks = set()
        for i in e["ids"]:
            mm = re.match(r"(L[12]):(\d+)/", i)
            if mm:
                blks.add((mm.group(1), int(mm.group(2))))
        orig = kr

        # 1) [NAME:XX] + 조사 — 오른쪽부터 처리(치환 길이 변화가 앞 인덱스에 영향 없게)
        for m in reversed(list(NAME_RX.finditer(kr))):
            xx = int(m.group(1), 16)
            nm = None
            for tag, blk in blks:
                nm = names.get((tag, blk, xx))
                if nm:
                    break
            if not nm:
                continue
            b = batchim(nm)
            if b is None:
                continue
            tail_start = m.end()
            fixed = normalize_after(kr[tail_start:], b != 0, b == 8)
            kr = kr[:tail_start] + fixed

        # (리터럴 고유명사 패스는 제거 — 짧은 캐릭터명 '바란/란스/남/나가' 등이 동사·
        #  일반어("바란다"=바라다)와 충돌해 오탐. [NAME:XX] 변수 뒤는 반드시 실제 조사라
        #  안전하므로 그 경우만 교정한다.)

        # [WAIT]={02} 동적 삽입은 대화에서 플레이어명(레딘/엘윈, 둘 다 받침 ㄴ)이다.
        # 단, 상점/아이템 문맥에선 아이템명이라 받침 불명 → 오직 '줄 시작의 [WAIT]야'
        # (명백한 호격, 아이템명은 줄머리에 "[아이템]야."로 오지 않음)만 안전하게 교정.
        kr = re.sub(r"(^|\[NL\]|\[PAGE\])\[WAIT\]야(?=[\s.!?…‥」』]|$)",
                    r"\1[WAIT]아", kr)

        if kr != orig:
            changed += 1
            if changed <= 60:
                print("---", e["ids"][0])
                print(" 전:", orig.replace("\n", "|")[:100])
                print(" 후:", kr.replace("\n", "|")[:100])
            e["kr"] = kr
    print(f"\n교정 {changed}건")
    if apply:
        json.dump(ws, open(WS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("적용됨:", WS)
    else:
        print("(dry-run — --apply로 저장)")
    return int(changed > 0 and not apply)


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
