#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_titlemenu.py — 에피소드 타이틀 화면의 메뉴(スタート/ロード/バックアップRAM)를 한글로.

세션22. 이 메뉴는 **문자열이 아니라 통짜 픽셀 그림**이다:
  * 타이틀 화면은 NBG 4개가 전부 비어 있고 VDP1 스프라이트 2개로만 그려진다
    (실기 커맨드 테이블 확인): 320x224 배경 아트 + **80x40 메뉴 상자**(화면 213,152).
  * 그 80x40 4bpp 스프라이트의 원본은 IMG.DAT **L1 res#28 / L2 res#26 의 오프셋
    0x164**(1600B). 두 파일의 리소스는 **바이트 동일**하다.
  * 그래서 BIN에서 문자열/타일배열을 찾아도 안 나온다(세션22에 헛삽질 함).

원본 글리프 스타일(팔레트 실측 — colr=0x00f0, CRAM 0x0f0+):
    색인 1 #d0e8e0(거의 흰색) · 2 #88f090(연녹) · 3 #58c060(녹) · 11 #003850(상자
    배경) · **14 #200020(거의 검정)**
  * 본체 = **1/2/3 세로 그라데이션**(셀 행 r=0,1 → 1 · r=2,3 → 2 · r≥4 → 3),
    그림자 = **색인 14를 (+1,+1) 오프셋**으로 본체가 없는 칸에만.
  * ⛔ 세션22에 이걸 **거꾸로** 읽어(본체=14) 글자가 새까맣게 나왔다. 밝은 쪽이
    본체다 — 팔레트를 안 보고 픽셀 패턴만 보면 뒤집힌다.
  * 본체 7x7, 셀 간격 세로 11(본체 행 6/17/28), 본문 좌단 x=16.
  * ⚠ x<16 은 **커서(▶) 자리**라 비워 둬야 한다. 커서는 이 스프라이트에 없다.

한글은 달무리 8x8(gen_hud8과 같은 폰트/렌더러)을 쓰고, 글리프마다 실제 잉크 폭으로
붙여 쓴다(원본 카나가 7px 간격으로 촘촘한 것에 맞춤).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import gen_hud8                                                    # noqa: E402

SPRITE_OFF = 0x164          # 리소스 안 스프라이트 시작
W, H = 80, 40               # 4bpp -> 1600B
RES = {"L1": 28, "L2": 26}

FILL = 11                   # 상자 안쪽 배경 색인
BODY = (1, 1, 2, 2, 3, 3, 3, 3)           # 셀 행별 본체 색인 (밝은 세로 그라데이션)
SHADOW = 14                 # 그림자 (본체를 +1,+1 오프셋)

TEXT_X = 16                 # 본체 좌단 (그림자가 +1)
LINE_Y = (6, 17, 28)        # 본체 상단 (그림자가 +1)
CLEAR_X0 = 16               # 이보다 왼쪽은 커서(▶) 자리 — 절대 안 건드린다
CLEAR_ROWS = range(6, 37)   # 원본 세 줄이 차지하던 행
GLYPH_COLORS = {1, 2, 3, 14}
# ⚠ 상자 테두리도 1·2·6을 쓰므로 "색인으로 글자 판별"은 못 한다. 대신 각 행에서
#   **배경색(11)이 처음/마지막 나오는 x**로 안쪽 구간을 잡는다(테두리는 그 밖).

LINES = ("시작", "불러오기", "백업 RAM")


def _get(buf, x, y):
    b = buf[SPRITE_OFF + (y * W + x) // 2]
    return (b >> 4) if x % 2 == 0 else (b & 0xF)


def _put(buf, x, y, v):
    i = SPRITE_OFF + (y * W + x) // 2
    b = buf[i]
    buf[i] = ((v << 4) | (b & 0x0F)) if x % 2 == 0 else ((b & 0xF0) | v)


def _mask(font, ch):
    """달무리 8x8 -> [(x,y)] 잉크 좌표. 공백은 빈 마스크."""
    if ch == " ":
        return []
    tile = gen_hud8.render_glyph8(font, ch)      # 4bpp, 잉크=1
    out = []
    for y in range(8):
        for x in range(8):
            b = tile[y * 4 + x // 2]
            v = (b >> 4) if x % 2 == 0 else (b & 0xF)
            if v:
                out.append((x, y))
    return out


def patch_sprite(raw, lines=LINES, verbose=False):
    """리소스 압축해제본을 받아 메뉴 스프라이트만 한글로 다시 그린다."""
    buf = bytearray(raw)
    # 1) 기존 글자 지우기 — 행마다 배경색 구간을 구해 그 안만 배경으로 덮는다
    # CLEAR_X0에서 오른쪽으로 "배경 또는 글자색"이 이어지는 만큼만. 상자 모서리
    # 장식(색인 6/0)이 안쪽 행에도 들어와 있어서(예: 행 36의 x=70) 단순 min..max로
    # 잡으면 테두리를 지운다.
    span = {}
    for y in CLEAR_ROWS:
        assert _get(buf, CLEAR_X0, y) == FILL, f"({CLEAR_X0},{y}) is not background"
        hi = CLEAR_X0
        while hi + 1 < W and _get(buf, hi + 1, y) in (FILL, *GLYPH_COLORS):
            hi += 1
        span[y] = (CLEAR_X0, hi)
        for x in range(CLEAR_X0, hi + 1):
            _put(buf, x, y, FILL)
    # 2) 한글 그리기
    font = gen_hud8._font8()
    for li, text in enumerate(lines):
        by = LINE_Y[li]
        bx = TEXT_X
        for ch in text:
            m = _mask(font, ch)
            if not m:                                  # 공백
                bx += 3
                continue
            wid = max(x for x, _ in m) + 1
            body = {(bx + x, by + y) for x, y in m}
            shadow = {(x + 1, y + 1) for x, y in body} - body
            for px, py in sorted(body | shadow):
                lo, hi = span.get(py, (1, 0))
                assert lo <= px <= hi, \
                    f"{text!r} spills out of the box interior at ({px},{py})"
                _put(buf, px, py,
                     BODY[py - by] if (px, py) in body else SHADOW)
            bx += wid + 1
        if verbose:
            print(f"  line{li+1} {text!r}: x {TEXT_X}..{bx-2}")
    return bytes(buf)


def preview(raw, path):
    """실측 CRAM(0x0f0+, RGB555) 색으로 렌더한다 — 임의 색으로 미리보면 본체/그림자를
    거꾸로 만들어도 눈치채지 못한다(세션22에 그랬다)."""
    from PIL import Image
    pal = {0: (0x00, 0x00, 0x00), 1: (0xd0, 0xe8, 0xe0), 2: (0x88, 0xf0, 0x90),
           3: (0x58, 0xc0, 0x60), 4: (0x48, 0xa0, 0x50), 5: (0x28, 0x80, 0x30),
           6: (0x30, 0x58, 0x30), 11: (0x00, 0x38, 0x50), 14: (0x20, 0x00, 0x20)}
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = pal.get(_get(bytearray(raw), x, y), (255, 0, 255))
    im.resize((W * 5, H * 5), Image.NEAREST).save(path)


def main():
    from img_codec import parse_archive, decompress
    orig = os.path.join(ROOT, "original")
    out = os.path.join(ROOT, "build")
    for tag in ("L1", "L2"):
        buf = open(os.path.join(orig, f"LANG{tag[1]}_IMG.DAT"), "rb").read()
        raw = decompress(parse_archive(buf)[RES[tag]])
        print(f"{tag} res#{RES[tag]} ({len(raw)}B)")
        new = patch_sprite(raw, verbose=True)
        preview(raw, os.path.join(out, f"titlemenu_{tag}_before.png"))
        preview(new, os.path.join(out, f"titlemenu_{tag}_after.png"))
        print(f"  -> build/titlemenu_{tag}_before.png / _after.png")


if __name__ == "__main__":
    main()
