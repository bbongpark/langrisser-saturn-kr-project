#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kr_encoding.py — 한글 음절 -> 한자 슬롯(SJIS) 동적 배정 + SJIS<->글리프슬롯 매핑.

FONT.DAT 한자 블록(실측):
  - block4 : JIS ku16..62, 94점/구, block4[0] = '亜' = SJIS 0x889F.
  - block5 : JIS ku63..84, 94점/구(연속).
  - SJIS 한자코드 -> JIS kuten -> (block, glyph index) -> 파일 오프셋.

배정 정책:
  - build_table(syllables): 한글 음절을 한자 SJIS 코드에 1:1 배정한다.
  - 기본 후보 순서 = JIS kanji kuten 오름차순(block4 → block5).
  - 배정한 SJIS 코드로 본문을 인코딩하고, 같은 슬롯에 한글 글리프를 구우면
    (kr_font.bake_glyph + patch_font) 엔진 무수정으로 한글이 렌더된다.

주의: SJIS→슬롯의 *런타임* 인덱싱 공식은 정적 증거(레이아웃=JIS kuten 연속,
'亜'@block4[0])로 확정했으나, 최종 확증은 emucap 라이브 RAM 검증(별도 트랙)이다.
디코드/인코드/폰트빌더가 모두 이 파일의 매핑을 단일 소비한다(data-formats §7).
"""
from pathlib import Path

# --- 한자 블록 JIS 구(ku) 범위 (kr_font 헤더 실측과 일치) ---------------------
BLOCK4_KU_START = 16     # block4[0] = ku16.1 = 亜
BLOCK5_KU_START = 63     # block5[0] = ku63.1
KU_POINTS = 94           # 점(ten) per 구(ku)
BLOCK4_INDEX = 4
BLOCK5_INDEX = 5


# --------------------------------------------------------------------------
# SJIS <-> JIS kuten  (표준 JIS X 0208 / Shift-JIS 2바이트)
# --------------------------------------------------------------------------
def kuten_to_sjis(ku: int, ten: int) -> tuple:
    """JIS 구(1..94)/점(1..94) -> (하위리드, 하위트레일) 2바이트 SJIS."""
    if ku < 63:
        sh = (ku + 1) // 2 + 0x80
    else:
        sh = (ku + 1) // 2 + 0xC0
    if ku % 2:                      # 홀수 구
        sl = ten + 0x3F + (1 if ten >= 64 else 0)
    else:                           # 짝수 구
        sl = ten + 0x9E
    return sh, sl


def sjis_to_kuten(sh: int, sl: int) -> tuple:
    """SJIS 2바이트(리드, 트레일) -> (ku, ten)."""
    if 0x81 <= sh <= 0x9F:
        ku_hi = (sh - 0x81) * 2
    elif 0xE0 <= sh <= 0xEF:
        ku_hi = (sh - 0xC1) * 2
    else:
        raise ValueError(f"lead byte {sh:#x} not in kanji/JIS range")
    if sl >= 0x9F:                  # 짝수 구
        ku = ku_hi + 2
        ten = sl - 0x9E
    else:                           # 홀수 구
        ku = ku_hi + 1
        ten = sl - 0x3F - (1 if sl >= 0x80 else 0)
    return ku, ten


# --------------------------------------------------------------------------
# kanji SJIS <-> FONT.DAT (block, glyph index)
# --------------------------------------------------------------------------
def kuten_to_slot(ku: int, ten: int) -> tuple:
    """(ku, ten) -> (block, glyph_index). 한자 블록 4/5 만 유효."""
    g = (ku - BLOCK4_KU_START) * KU_POINTS + (ten - 1)
    if BLOCK4_KU_START <= ku < BLOCK5_KU_START:
        return BLOCK4_INDEX, g
    if BLOCK5_KU_START <= ku <= 84:
        return BLOCK5_INDEX, (ku - BLOCK5_KU_START) * KU_POINTS + (ten - 1)
    raise ValueError(f"ku {ku} outside kanji blocks (16..84)")


def sjis_to_slot(sh: int, sl: int) -> tuple:
    ku, ten = sjis_to_kuten(sh, sl)
    return kuten_to_slot(ku, ten)


def sjis_bytes_to_offset(fontdat, sh: int, sl: int) -> int:
    """SJIS 한자 2바이트 -> FONT.DAT 파일 오프셋 (kr_font.FontDat 필요)."""
    block, index = sjis_to_slot(sh, sl)
    return fontdat.block_glyph_offset(block, index)


def iter_kanji_sjis(fontdat=None):
    """배정 후보(한자 SJIS 코드)를 kuten 오름차순으로 yield: (sh, sl, block, index).

    fontdat(kr_font.FontDat) 를 주면 실제 블록 글리프 수를 넘는 (존재하지 않는)
    슬롯을 건너뛴다 — block5 는 94의 배수가 아니어서(1978) 마지막 구가 부분적이다.
    fontdat 없으면 kuten 이론 범위(ku16..84) 전체를 yield 한다.
    """
    for ku in range(BLOCK4_KU_START, 85):
        for ten in range(1, KU_POINTS + 1):
            block, index = kuten_to_slot(ku, ten)
            if fontdat is not None and index >= fontdat.glyph_count(block):
                continue
            sh, sl = kuten_to_sjis(ku, ten)
            yield sh, sl, block, index


# --------------------------------------------------------------------------
# KS X 1001 완성형 한글 2,350 음절
# --------------------------------------------------------------------------
def ksx1001_hangul():
    """KS X 1001 완성형 한글 음절 2,350자를 표준 순서로 반환(euc-kr 디코드)."""
    out = []
    for lead in range(0xB0, 0xC9):          # 완성형 한글 리드 바이트
        for trail in range(0xA1, 0xFF):
            try:
                ch = bytes([lead, trail]).decode('euc-kr')
            except UnicodeDecodeError:
                continue
            if '가' <= ch <= '힣':
                out.append(ch)
    return out


# --------------------------------------------------------------------------
# 동적 코드 배정
# --------------------------------------------------------------------------
def empty_kanji_slots(fontdat):
    """FONT.DAT 한자 블록에서 비어(전부 0) 있는 슬롯을 kuten 오름차순으로 반환.

    실측: LANG1/LANG2 공히 block4 말미의 연속 43슬롯(SJIS 0x9873..0x989e)이 비어 있다.
    여기에 한글을 구우면 실제 한자 글리프를 하나도 훼손하지 않는다(잔존 일본어 안전).
    """
    out = []
    for sh, sl, b, i in iter_kanji_sjis(fontdat):
        if fontdat.is_empty_at(fontdat.block_glyph_offset(b, i)):
            out.append((sh, sl, b, i))
    return out


def build_table(syllables, reserved_slots=None, fontdat=None, prefer_empty=True):
    """한글 음절 리스트 -> 배정 테이블.

    syllables : 배정할 한글 음절(빈도순 권장). 중복은 첫 등장만 사용.
    reserved_slots : 건드리면 안 되는 (block, index) 집합(원본 유지 필요 한자).
    fontdat : kr_font.FontDat. 주면 실제 존재하는 슬롯만 후보로 쓴다(권장).
    prefer_empty : True(기본)이고 fontdat이 있으면 **빈 슬롯을 먼저** 소진한 뒤
                   점유된 한자 슬롯으로 오버플로한다 — 잔존 일본어 한자 훼손을 최소화.
                   (빈 슬롯은 43개뿐이라 그보다 많은 음절은 한자 슬롯을 덮어쓴다;
                    전면 번역에선 무해하나, 부분 번역 땐 코퍼스에 없는 한자를 우선
                    쓰도록 향후 확장 여지.)
    반환 dict:
      {'map': {음절: {'sjis':(sh,sl), 'block':b, 'index':i}},
       'order': [음절...], 'supply': int, 'used': int, 'empty_supply': int}
    필요 > 공급이면 ValueError.
    """
    reserved = set(reserved_slots or [])
    uniq = []
    seen = set()
    for s in syllables:
        if s not in seen:
            seen.add(s)
            uniq.append(s)

    all_cand = [(sh, sl, b, i) for (sh, sl, b, i) in iter_kanji_sjis(fontdat)
                if (b, i) not in reserved]
    empty_supply = 0
    if prefer_empty and fontdat is not None:
        empties, occupied = [], []
        for c in all_cand:
            _, _, b, i = c
            (empties if fontdat.is_empty_at(fontdat.block_glyph_offset(b, i))
             else occupied).append(c)
        empty_supply = len(empties)
        cand = empties + occupied     # 빈 슬롯 먼저, 그다음 점유 한자
    else:
        cand = all_cand
    supply = len(cand)
    if len(uniq) > supply:
        raise ValueError(f"need {len(uniq)} syllables > supply {supply} kanji slots")

    mapping = {}
    for syl, (sh, sl, b, i) in zip(uniq, cand):
        mapping[syl] = {'sjis': (sh, sl), 'block': b, 'index': i}
    return {'map': mapping, 'order': uniq, 'supply': supply, 'used': len(uniq),
            'empty_supply': empty_supply}


def is_hangul(ch: str) -> bool:
    """완성형 한글 음절(가~힣)인지."""
    return '가' <= ch <= '힣'


# normalize Unicode punctuation the translators may use to SJIS-encodable forms
_PUNCT = {
    '—': '―',   # em dash — -> ― (SJIS 0x815C)
    '–': '―',   # en dash – -> ―
    '·': '・',   # middle dot · -> ・ (SJIS 0x8145)
    '‧': '・', '•': '・', '゠': '・',
    '‘': "'", '’': "'", '“': '"', '”': '"',
    ' ': '　',   # nbsp -> ideographic space
}


# 전각형(U+FF01..FF5E)이 Shift-JIS에 없는 ASCII의 대체 전각 글리프
_FW_SPECIAL = {
    '"': '”',   # U+201D  SJIS 0x8168
    "'": '’',   # U+2019  SJIS 0x8166
    '-': '−',   # U+2212  SJIS 0x817C (전각 마이너스)
    '~': '〜',   # U+301C  SJIS 0x8160 (물결)
}


def _to_fullwidth(ch: str) -> str:
    """ASCII 0x21..0x7E -> 대응 전각(U+FF01..FF5E). 그 밖은 그대로.

    이 게임의 텍스트 렌더러는 0x20 이상 바이트를 **2바이트 SJIS 글자**로 읽는다
    (원본 일본어도 영숫자·구두점을 전부 전각으로 씀 — 1바이트 ASCII를 안 받는다).
    반각 ASCII 한 글자가 들어가면 SJIS 정렬이 깨져 **뒤따르는 제어코드({08} 줄바꿈
    등)나 다음 글자 바이트를 삼켜** 줄이 붙거나 글자가 깨진다. 그래서 전각으로 승격한다.
    ',' -> '，'(0x8143), '.' -> '．'(0x8144), '!' -> '！'(0x8149), '?' -> '？'(0x8148) 등.
    전각형이 SJIS에 없는 " ' - ~ 는 _FW_SPECIAL의 등가 전각 글리프로 보낸다."""
    if ch in _FW_SPECIAL:
        return _FW_SPECIAL[ch]
    o = ord(ch)
    if 0x21 <= o <= 0x7E:
        return chr(o - 0x21 + 0xFF01)
    return ch


def encode_text(text: str, table: dict, passthrough: bool = True) -> bytes:
    """한글 문자열 -> 배정된 SJIS 바이트열.

    배정 테이블에 있는 음절은 그 슬롯 코드로, 그 밖의 문자(문장부호·영숫자)는
    **전각(2바이트)으로 승격**한 뒤 passthrough=True면 Shift-JIS로 통과시킨다.
    반각 ASCII는 게임 렌더러(2바이트 전제)에서 정렬을 깨 제어코드/글자를 삼키므로
    반드시 전각화한다(_to_fullwidth). 이미 전각인 부호(。、！？, 전각공백)는 유지.
    """
    out = bytearray()
    m = table['map']
    for ch in text:
        ch = _PUNCT.get(ch, ch)
        if ch in m:
            sh, sl = m[ch]['sjis']
            out += bytes([sh, sl])
            continue
        ch = _to_fullwidth(ch)               # ASCII 구두점·영숫자 -> 전각 2바이트
        if passthrough:
            try:
                b = ch.encode('shift_jis')
            except UnicodeEncodeError:
                raise KeyError(f"cannot encode {ch!r} (U+{ord(ch):04X}; add to _PUNCT)")
            if len(b) != 2:                  # 1바이트로 남으면 렌더러가 오정렬 -> 금지
                raise KeyError(f"{ch!r} encodes to {len(b)} byte(s), need 2 (fullwidth)")
            out += b
        else:
            raise KeyError(ch)
    return bytes(out)


# --------------------------------------------------------------------------
# 자체 검증
# --------------------------------------------------------------------------
def _selftest():
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    # 1) '亜' = SJIS 889F = block4[0]
    assert kuten_to_sjis(16, 1) == (0x88, 0x9F), kuten_to_sjis(16, 1)
    assert sjis_to_kuten(0x88, 0x9F) == (16, 1)
    assert kuten_to_slot(16, 1) == (4, 0)
    assert sjis_to_slot(0x88, 0x9F) == (4, 0)
    # 2) round-trip kuten<->sjis 전 범위
    for ku in range(16, 85):
        for ten in range(1, 95):
            sh, sl = kuten_to_sjis(ku, ten)
            assert sjis_to_kuten(sh, sl) == (ku, ten), (ku, ten, hex(sh), hex(sl))
    # 3) 완성형 개수
    syl = ksx1001_hangul()
    print("KS X 1001 완성형 음절 수:", len(syl), "예:", ''.join(syl[:10]))
    import kr_font
    fd = kr_font.FontDat.load(Path(__file__).resolve().parents[1] / 'original' / 'LANG1_FONT.DAT')
    t = build_table(syl, fontdat=fd)
    print("real kanji supply:", t['supply'], "(=block4+block5)  used:", t['used'])
    print("가 ->", t['map']['가']['sjis'], "block", t['map']['가']['block'], "idx", t['map']['가']['index'])
    print("selftest OK")


if __name__ == '__main__':
    _selftest()
