#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_register.py — **원문의 존대/평어와 번역의 말투가 어긋난 대사**를 찾는다.

  python scripts/audit_register.py L2 1     # 한 시나리오
  python scripts/audit_register.py L2       # 게임 전체 요약
  python scripts/audit_register.py L2 1 -v  # 판정 근거(걸린 어미)까지

일본어는 문말 형태로 **정중체(です·ます체)**와 **보통체(だ·である체)**가 뚜렷이 갈린다.
번역이 그 층위를 뒤집으면 캐릭터 관계가 어긋난다(부하가 상관에게 반말 등).

★ 판정은 **세그먼트 단위**다. 대사 하나 안에서 층위가 섞이는 일은 드물고, 문장별로 보면
  감탄사("옛!"·"음.")가 전부 평어로 잡혀 오탐이 쏟아진다.
⚠ **후보 목록일 뿐이다.** 다음은 구조적으로 못 잡는다 —
  · 겸양어(`申す`·`参る`)는 **정중하지만 문말이 보통체**다(`レオンと申す者。`).
  · 독백·나레이션성 대사는 원문이 보통체라도 한국어로는 경어가 자연스러울 수 있다.
  · 짧은 감탄사만 있는 세그먼트는 판정을 건너뛴다(`skip`).
  마지막 판단은 사람이 한다.
"""
import argparse
import collections
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dump_scenario_kr as D                                        # noqa: E402
import kr_names                                                     # noqa: E402

# ── 일본어 정중체 표지 ────────────────────────────────────────────────────────
# ⚠ `なさい`는 넣지 않는다 — 명령형 존댓말이지만 **손아랫사람에게** 쓰는 말이라
#    (로렌이 아들·엘윈에게) 한국어로는 '-거라/-게'가 맞다. 넣으면 전부 오탐이 된다.
# ⛔ `です`/`ます`를 맨몸으로 걸면 안 된다 — 「戦い**です**まない」처럼 **어절이 우연히 겹쳐**
#    오탐이 난다(세션24 실제 오탐). 뒤에 문말 경계가 오는 경우만 센다.
_B = r"[。！？、よねわなぞぜがかけ\s]|$"      # 문말 조사·구두점까지 경계로 본다
JP_POLITE = re.compile(
    r"です(?:%s)|ですか|ですね|ですが|でした|でしょう"
    r"|ます(?:%s)|ますか|ました|ません|ましょ|ましたら|まして"
    r"|ください|下さい|ございま|いたし|致し|おります|参りま|申しま" % (_B, _B))
# 보통체(반말) 표지 — 문말에 오는 것들
JP_PLAIN = re.compile(
    r"だ[。！？…‥\s]|だぞ|だぜ|だな[。！]|だろう|のか[？！]|ないか|しろ|やがれ|ぞ[！。]"
    r"|ぜ[！。]|かよ|のだ|でくれ|てくれ|ねぇ|ねえ|だが|わ[。！]|よ[。！]|さ[。！]|かい[？]")

# ── 한국어 경어 판정 ──────────────────────────────────────────────────────────
# 한국어 경어의 핵심 표지는 딱 둘이다:
#   ① **-요 종결**(해요체)  ② **-ㅂ니다/-ㅂ니까**(합쇼체)
# ⛔ `니다`/`니까`만 보면 안 된다 — '귀찮아지니까.'(평어)까지 걸린다.
#    합쇼체는 `니` 앞 음절의 **종성이 ㅂ**이다(습·십·합·입…). 그걸로 가른다.
KR_POLITE_TAIL = re.compile(r"([가-힣])(?:니(?:다|까)|시다)[.!?…~]*$")
KR_YO_TAIL = re.compile(r"(요|죠)[.!?…~]*$")     # 해요체 · '-죠'(=지요)
# 하오체(예사높임)도 존대다 — 로렌 같은 어른이 엘윈에게 쓴다.
KR_POLITE_ETC = re.compile(
    r"(세요|셔요|십시오|십시다|시죠|드립니다|주십시오|하오|시오|구려|소서|외다)[.!?…]*$")
_JONG_B = 17                      # 종성 ㅂ 의 인덱스


def _is_hapsyo(s):
    """'…ㅂ니다/ㅂ니까/ㅂ시다'로 끝나는가 (합쇼체·존대 청유).

    ⛔ `니다`/`니까`만 보면 '귀찮아지니까.'(평어)까지 걸린다. 합쇼체는 `니`(또는 `시다`)
    앞 음절의 **종성이 ㅂ**이다 — 습·십·합·입·냅…. 그 종성으로 가른다."""
    m = KR_POLITE_TAIL.search(s)
    if not m:
        return False
    ch = m.group(1)
    return (ord(ch) - 0xAC00) % 28 == _JONG_B


KR_PLAIN = re.compile(
    r"(다|냐|자|라|야|어|지|군|걸|까|래|든|네|마|봐|줘|해|돼|군|걸|나)[.!?…~]*$")

# 판정을 건너뛸 짧은 감탄/호명
SKIP = re.compile(r"^[가-힣ぁ-んァ-ヶ一-龥ＡＢＣ…‥,、.。!！?？~〜\s\[\]:0-9a-fA-F]{0,6}$")


def strip_markup(s):
    return re.sub(r"\[[^\]]*\]|\{[^}]*\}|<[0-9a-fA-F]{2}>", "", s or "")


def jp_register(jp):
    """'polite' | 'plain' | None"""
    t = strip_markup(jp)
    if len(t.strip()) < 6:
        return None
    p = len(JP_POLITE.findall(t))
    q = len(JP_PLAIN.findall(t))
    if p and not q:
        return "polite"
    if q and not p:
        return "plain"
    if p and q:
        return "polite" if p >= q else "plain"
    return None


def kr_register(kr):
    """'polite' | 'plain' | None — 문장별로 보고 다수결."""
    t = strip_markup(kr)
    sents = [s for s in re.split(r"(?<=[.!?…])\s*", t) if s.strip()]
    pol = pla = 0
    for s in sents:
        s = s.strip()
        if SKIP.match(s):
            continue
        if _is_hapsyo(s) or KR_YO_TAIL.search(s) or KR_POLITE_ETC.search(s):
            pol += 1
        elif KR_PLAIN.search(s):
            pla += 1
    if not (pol or pla):
        return None
    return "polite" if pol > pla else ("plain" if pla > pol else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?", help="L1 | L2")
    ap.add_argument("block", nargs="?", type=int)
    ap.add_argument("-v", "--verbose", action="store_true", help="판정 근거 표시")
    a = ap.parse_args()

    ws = D.load()
    D.NAME_W = kr_names.width_map(ws)
    names_all = D.name_tables(ws)
    ttl = D.titles(ws)

    hits = collections.defaultdict(list)
    for e in ws:
        seen = set()
        for tag, blk, leaf, seg in D.parsed_ids(e):
            if leaf != D.DLG:
                continue
            if (a.tag and tag != a.tag) or (a.block is not None and blk != a.block):
                continue
            if (tag, blk, seg) in seen:
                continue
            seen.add((tag, blk, seg))
            j, k = jp_register(e.get("jp", "")), kr_register(e.get("kr", ""))
            if j and k and j != k:
                hits[(tag, blk)].append((seg, j, k, e))

    total = sum(len(v) for v in hits.values())
    if a.block is not None:
        key = (a.tag, a.block)
        rows = sorted(hits.get(key, []))
        print("%s 블록%d 「%s」 — 원문과 말투 층위가 어긋난 후보 %d건"
              % (a.tag, a.block, ttl.get(key, ""), len(rows)))
        names = names_all.get(a.tag, {})
        for seg, j, k, e in rows:
            lab = {"polite": "정중체", "plain": "보통체"}
            print("\n  #%-4d 원문 %s → 번역 %s" % (seg, lab[j], lab[k]))
            print("       JP: %s" % e["jp"].replace("\n", "/"))
            print("       KR: %s" % D.render(e.get("kr", ""), names, names.get(1)))
            if a.verbose:
                t = strip_markup(e["jp"])
                print("       근거: JP %s / %s" % (JP_POLITE.findall(t), JP_PLAIN.findall(t)))
        return

    print("원문과 말투 층위가 어긋난 후보: 총 %d건" % total)
    for key in sorted(hits):
        print("  %s 블록%-4d %3d건  「%s」" % (key[0], key[1], len(hits[key]), ttl.get(key, "")))


if __name__ == "__main__":
    main()
