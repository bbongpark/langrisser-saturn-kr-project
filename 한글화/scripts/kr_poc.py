#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kr_poc.py — PoC: 한글 음절을 한자 슬롯에 구워 수정 FONT.DAT 생성 + 육안검증 PNG.

산출물(kr-patch/build/):
  - LANG1_FONT.kr.dat        : 한글이 구워진 수정 FONT.DAT (원본 미변경)
  - poc_baked_rendered.png   : 구운 슬롯을 게임 렌더러와 동일(swap 되돌림)하게 표시
  - poc_baked_raw.png        : swap 없이 표시(저장형 그대로) — 대조용
검증: 무변경 라운드트립(원본 재직렬화=원본 바이트) 먼저 통과 후 굽는다.
"""
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))

import kr_font as F
import kr_encoding as E

ROOT = Path(__file__).resolve().parents[1]
ORIG = ROOT / 'original' / 'LANG1_FONT.DAT'
BUILD = ROOT / 'build'
TTF = r'C:\Windows\Fonts\malgun.ttf'   # 프로토타입 폰트(품질용 Neo둥근모는 조달 대기)

SAMPLE = "가나다라마바사아엘윈한글"


def main():
    BUILD.mkdir(exist_ok=True)
    fd = F.FontDat.load(ORIG)

    # 게이트 0: 무변경 라운드트립
    assert bytes(fd.data) == ORIG.read_bytes(), "roundtrip failed"

    # 배정 테이블(샘플 음절 -> 한자 슬롯, 실제 슬롯만)
    table = E.build_table(SAMPLE, fontdat=fd)

    baked = []
    for ch in table['order']:
        info = table['map'][ch]
        sh, sl = info['sjis']
        off = fd.block_glyph_offset(info['block'], info['index'])
        glyph = F.bake_glyph(ch, TTF, swap=True, px=16)     # SWAP_HALVES 적용 저장형
        fd.patch_font(off, glyph)
        baked.append(glyph)
        print(f"{ch}  SJIS={sh:02X}{sl:02X}  block{info['block']}[{info['index']}] @ {off:#07x}")

    out = BUILD / 'LANG1_FONT.kr.dat'
    fd.save(out)
    # 원본 크기 보존 확인
    assert out.stat().st_size == ORIG.stat().st_size, "size changed!"

    # 렌더: swap 되돌림(정상) vs 저장형 그대로(대조)
    F.render_montage_png(baked, BUILD / 'poc_baked_rendered.png', swap=True, scale=6, cols=len(baked))
    F.render_montage_png(baked, BUILD / 'poc_baked_raw.png', swap=False, scale=6, cols=len(baked))

    # 굽힌 파일을 다시 로드해 실제 슬롯을 렌더(왕복 무결성)
    fd2 = F.FontDat.load(out)
    reload_glyphs = []
    for ch in table['order']:
        info = table['map'][ch]
        reload_glyphs.append(fd2.read_glyph(info['block'], info['index']))
    F.render_montage_png(reload_glyphs, BUILD / 'poc_from_saved.png', swap=True, scale=6, cols=len(reload_glyphs))

    print("\nsaved:", out)
    print("PNG:", BUILD / 'poc_baked_rendered.png')
    print("PNG:", BUILD / 'poc_from_saved.png')
    print("PNG(raw):", BUILD / 'poc_baked_raw.png')


if __name__ == '__main__':
    main()
