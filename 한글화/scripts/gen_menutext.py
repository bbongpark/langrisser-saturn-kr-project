#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_menutext.py — translate the load/save-screen TEXT strings that live directly in
LANG{1,2}.BIN (not SCEN, not IMG graphics). These render through the normal dialogue
text path (SJIS -> FONT.DAT glyph on NBG3), so Korean encoded into the shared font slots
renders like any dialogue. Each patch replaces the Japanese bytes in place and zero-fills
the remainder up to the original NUL (Korean is shorter). Control codes / {02} title
inserts / 『』 brackets around them are left untouched.

PATCHES[tag] = [(offset, jp_str, kr_str), ...]. build(binx, font_table, tag) applies them.
The Korean syllables must be in `font_table` (caller adds MENU_SYLLABLES before baking).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kr_encoding

# JP text (exact bytes) -> KR, with the file offset of the JP bytes in each BIN.
# Korean is <= JP byte length so it fits in place (zero-filled tail).
PATCHES = {
    "L1": [
        (0x2a209, "面", "장"),
        (0x2a219, "面", "장"),
        (0x2a29a, "の続きから", ""),      # 세션17: 슬롯 접미 "이어서" 제거 (긴 제목이 잘리지 않게)
        (0x2a2a8, "データがありません", "데이터없음"),
        (0x2b4fc, "データが壊れています", "데이터손상"),
        (0x2b4e8, "セーブできません", "저장할수없음"),
        (0x2b9d1, "面から", "장부터"),
        (0x2b9e1, "面から", "장부터"),
        # 세션19: 전과보고(전투 결과) 화면 하단 프롬프트(점멸 표시). LANG SCEN의 ＢかＣ판(워크시트 #149)과
        # 별개로 BIN에 직접 박힌 Ａ포함판. 반각 space는 인코더가 거부 → 전각 space U+3000.
        # ⚠ **바이트 예산(32B)이 아니라 창 폭이 제약** — 이 창은 약 13칸이라 원문과 같은 16칸을 넣으면
        #   뒷부분이 줄 앞으로 되돌아와 덮어쓴다(1차 시도 `Ａ나　Ｂ나　Ｃ　버튼을　누르세요`=16칸이 그랬다).
        #   현재 11칸. 라이브 RAM 주입으로 10칸판이 정상 렌더됨을 확인했고 `／`(0x815E) 글리프도 폰트에 존재.
        (0x39010, "ＡかＢかＣボタンを押してください", "Ａ／Ｂ／Ｃ를　누르세요"),
    ],
    "L2": [
        (0x2bf45, "面", "장"),
        (0x2bf55, "面", "장"),
        (0x2bfd6, "の続きから", ""),      # 세션17: 슬롯 접미 "이어서" 제거 (긴 제목이 잘리지 않게)
        (0x2bfe4, "データがありません", "데이터없음"),
        (0x2d238, "データが壊れています", "데이터손상"),
        (0x2d224, "セーブできません", "저장할수없음"),
        (0x2d739, "面から", "장부터"),
        (0x2d749, "面から", "장부터"),
        (0x3ac68, "ＡかＢかＣボタンを押してください", "Ａ／Ｂ／Ｃ를　누르세요"),  # 세션19: L1 0x39010과 동일
    ],
}

# --- 세션17: 로드/세이브 슬롯 제목 렌더 수정 ---------------------------------
# 슬롯 문자열 = 런타임 조립 `{ctrl}面{010e}『{02}{010e}』` + strcat "이어서".
# 안쪽 {02}=시나리오 제목 삽입(SCEN (2,8) leaf). **{010e}(=01 0e) 컨트롤 코드가 렌더러를
# "깨진 제목-글립 모드"로 전환**시켜 제목(일본어든 한글이든)을 파편으로 그린다(라이브 RE로 실증).
# 두 {010e}를 제거하면 {02}가 정상 FONT.DAT 경로로 렌더 → kanji-slot 한글 제목이 제대로 나온다.
# 슬롯 위치·구조는 L1/L2 공통. 16바이트 슬롯을 in-place로 재작성(面은 오프셋+1 유지 → 위 面→장
# 패치가 그대로 동작; strcpy는 첫 0x00에서 멈추므로 꼬리 `…09` 마커는 보존).
_TPL_ORIG_TAIL = bytes.fromhex("96ca 010e 8177 02 010e 8178 00 00 00 09".replace(" ", ""))
_TPL_NEW_TAIL  = bytes.fromhex("96ca 8177 02 8178 00 00 00 00 00 00 00 09".replace(" ", ""))
TEMPLATE_SLOTS = {
    "L1": [0x2a208, 0x2a218],   # A ({03}면…) / B ({02}면…)
    "L2": [0x2bf44, 0x2bf54],
}


def _rewrite_templates(b, tag):
    """로드/세이브 슬롯 템플릿에서 {010e} 코드를 제거한다(ctrl 바이트·면 위치 보존)."""
    for slot in TEMPLATE_SLOTS.get(tag, []):
        ctrl = b[slot]                                   # 03(A) / 02(B) — 보존
        cur = bytes(b[slot + 1:slot + 1 + len(_TPL_ORIG_TAIL)])
        assert cur == _TPL_ORIG_TAIL, \
            f"{tag} template @0x{slot:x}: expected {_TPL_ORIG_TAIL.hex()}, got {cur.hex()}"
        b[slot + 1:slot + 1 + len(_TPL_NEW_TAIL)] = _TPL_NEW_TAIL
        b[slot] = ctrl

MENU_SYLLABLES = sorted({ch for lst in PATCHES.values() for (_, _, kr) in lst
                         for ch in kr if kr_encoding.is_hangul(ch)})


def build(binx, font_table, tag):
    """Apply the load/save text patches to LANG{1,2}.BIN. Returns new bytes."""
    b = bytearray(binx)
    _rewrite_templates(b, tag)          # 세션17: {010e} 제거 (面→장 패치 전; 面 위치 보존)
    for off, jp, kr in PATCHES.get(tag, []):
        jb = jp.encode("cp932")
        assert bytes(b[off:off + len(jb)]) == jb, \
            f"{tag} @0x{off:x}: expected {jp!r} ({jb.hex()}), got {bytes(b[off:off+len(jb)]).hex()}"
        kb = b"".join(bytes(kr_encoding.encode_text(ch, font_table)) for ch in kr)
        assert len(kb) <= len(jb), f"{tag} @0x{off:x}: {kr!r} ({len(kb)}B) > {jp!r} ({len(jb)}B)"
        b[off:off + len(kb)] = kb
        for i in range(off + len(kb), off + len(jb)):
            b[i] = 0
    return bytes(b)


def _selftest():
    import kr_font
    fd = kr_font.FontDat.load(os.path.join(os.path.dirname(__file__), "..", "original", "LANG1_FONT.DAT"))
    table = kr_encoding.build_table(MENU_SYLLABLES, fontdat=fd)
    for tag, binf in (("L1", "LANG1.BIN"), ("L2", "LANG2.BIN")):
        binx = open(os.path.join(os.path.dirname(__file__), "..", "original", binf), "rb").read()
        new = build(binx, table, tag)
        assert len(new) == len(binx)
        print(f"gen_menutext selftest {tag}: {len(PATCHES[tag])} patches OK")
    print("menu syllables:", "".join(MENU_SYLLABLES))


if __name__ == "__main__":
    _selftest()
