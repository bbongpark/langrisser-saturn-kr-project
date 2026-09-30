#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kr_font.py — 랑그릿사 I&II 드라마틱 에디션 (Sega Saturn) FONT.DAT
             글리프 래스터화 / SWAP_HALVES / 슬롯 베이킹 기계.

FONT.DAT 실측 구조 (LANG1/LANG2 동일, sha1 e530fb07...):
  - 헤더: 7 x u32 (big-endian) 블록 오프셋. 마지막(7번째)은 EOF 센티널.
  - 블록: 6개. 각 글리프 32바이트 = 16행 x 2바이트(16px, 1bpp, MSB-first).
  - 저장 시 각 행의 좌8px/우8px 바이트가 스왑되어 있음(SWAP_HALVES).
    렌더러가 되돌려 읽으므로, 굽는 쪽도 스왑해 저장해야 정상 표시.
  - 블록 4/5 = JIS 한자(ku16.1 '亜' = block4[0] = SJIS 0x889F), 94점/구,
    kuten 연속. 한글 재할당의 주 대상(공급 6,396 슬롯).

이 모듈은 인코딩(코드↔슬롯)을 모른다. SJIS↔슬롯 매핑은 kr_encoding.py 소유.
좌표/오프셋 계산만 담당하고, 원본 파일은 절대 덮어쓰지 않는다.
"""
import struct
from pathlib import Path

GLYPH_BYTES = 32          # 16행 x 2바이트
CELL = 16                 # 16x16 픽셀
HEADER_ENTRIES = 7        # u32 big-endian 블록 오프셋 (마지막은 EOF)
_ZERO = bytes(GLYPH_BYTES)


# --------------------------------------------------------------------------
# FONT.DAT 파싱
# --------------------------------------------------------------------------
class FontDat:
    """FONT.DAT 컨테이너. 원본 바이트를 보존하고 슬롯 단위로 읽고/굽는다."""

    def __init__(self, data: bytes):
        self.data = bytearray(data)
        self.offsets = [struct.unpack_from('>I', data, i * 4)[0]
                        for i in range(HEADER_ENTRIES)]
        # 블록 [i] = offsets[i] .. offsets[i+1]  (i = 0..5), offsets[6]=EOF
        self.blocks = []
        for i in range(HEADER_ENTRIES - 1):
            start, end = self.offsets[i], self.offsets[i + 1]
            self.blocks.append((start, end, (end - start) // GLYPH_BYTES))

    @classmethod
    def load(cls, path) -> "FontDat":
        return cls(Path(path).read_bytes())

    def save(self, path):
        Path(path).write_bytes(bytes(self.data))

    def block_count(self) -> int:
        return len(self.blocks)

    def glyph_count(self, block: int) -> int:
        return self.blocks[block][2]

    def block_glyph_offset(self, block: int, index: int) -> int:
        """블록 내 index번째 글리프의 파일 오프셋."""
        start, end, n = self.blocks[block]
        if not (0 <= index < n):
            raise IndexError(f"block {block} index {index} out of range 0..{n-1}")
        return start + index * GLYPH_BYTES

    def read_glyph_at(self, offset: int) -> bytes:
        """파일 오프셋에서 32바이트 원시 글리프(스왑된 저장형)를 읽는다."""
        return bytes(self.data[offset:offset + GLYPH_BYTES])

    def read_glyph(self, block: int, index: int) -> bytes:
        return self.read_glyph_at(self.block_glyph_offset(block, index))

    def is_empty_at(self, offset: int) -> bool:
        return self.data[offset:offset + GLYPH_BYTES] == _ZERO

    def patch_font(self, offset: int, glyph32: bytes):
        """32바이트 글리프(이미 저장형=스왑 적용됨)를 파일 오프셋에 굽는다.

        offset 은 kr_encoding.py 의 sjis→offset 결과나 block_glyph_offset() 로 얻는다.
        glyph32 는 bake_glyph(...) 산출물(SWAP_HALVES 이미 적용)이어야 한다.
        """
        if len(glyph32) != GLYPH_BYTES:
            raise ValueError(f"glyph must be {GLYPH_BYTES} bytes, got {len(glyph32)}")
        if offset % 1 or offset < HEADER_ENTRIES * 4:
            # 헤더 영역 보호
            raise ValueError(f"refusing to patch header region at {offset:#x}")
        self.data[offset:offset + GLYPH_BYTES] = glyph32


# --------------------------------------------------------------------------
# SWAP_HALVES : 각 행의 두 바이트(좌8px / 우8px)를 서로 바꾼다
# --------------------------------------------------------------------------
def swap_halves(glyph32: bytes) -> bytes:
    """행마다 byte[0]<->byte[1] 스왑. 저장형<->렌더형 상호 변환(자기역함수)."""
    out = bytearray(GLYPH_BYTES)
    for r in range(CELL):
        out[r * 2] = glyph32[r * 2 + 1]
        out[r * 2 + 1] = glyph32[r * 2]
    return bytes(out)


# --------------------------------------------------------------------------
# 비트맵(논리 픽셀) <-> 글리프 바이트
#   bitmap = 16개 정수(각 16비트, bit15 = 좌측 픽셀, MSB-first)
# --------------------------------------------------------------------------
def bitmap_to_glyph(rows16, swap: bool = True) -> bytes:
    """논리 비트맵(왼→오, MSB-first) -> 32바이트 저장형 글리프.

    swap=True 이면 SWAP_HALVES 를 적용해 게임 저장형으로 굽는다(정상 경로).
    """
    if len(rows16) != CELL:
        raise ValueError("bitmap must have 16 rows")
    g = bytearray(GLYPH_BYTES)
    for r in range(CELL):
        word = rows16[r] & 0xFFFF
        left = (word >> 8) & 0xFF   # 좌측 8px
        right = word & 0xFF         # 우측 8px
        if swap:
            g[r * 2] = right
            g[r * 2 + 1] = left
        else:
            g[r * 2] = left
            g[r * 2 + 1] = right
    return bytes(g)


def glyph_to_bitmap(glyph32: bytes, swap: bool = True):
    """32바이트 글리프 -> 논리 비트맵(16 x 16비트, bit15=좌측).

    swap=True : 저장형(스왑됨)을 렌더형으로 되돌려 읽는다(정상 표시 경로).
    """
    rows = []
    for r in range(CELL):
        b0 = glyph32[r * 2]
        b1 = glyph32[r * 2 + 1]
        if swap:
            left, right = b1, b0
        else:
            left, right = b0, b1
        rows.append((left << 8) | right)
    return rows


# --------------------------------------------------------------------------
# TTF 래스터화 -> 16x16 1bpp 비트맵
# --------------------------------------------------------------------------
def rasterize_ttf(char: str, ttf_path: str, px: int = 16, threshold: int = 128,
                  y_offset: int = 0, x_offset: int = 0, font_index: int = 0):
    """한 글자를 16x16 논리 비트맵으로 래스터화(1bpp, MSB-first, 좌측=bit15).

    세로는 폰트의 **고정 베이스라인**으로 그린다(y_offset만 더함). 예전엔 글자마다
    ink-top을 -bbox[1]로 0행에 맞춰(top-align) 그렸는데, 그러면 받침 없는 짧은 글자
    (로/프 등)가 위로 떠 "높낮이가 들쭉날쭉"해진다(픽셀폰트 Neo둥근모에서 두드러짐).
    가로는 셀 중앙 정렬 유지(-bbox[0]).  반환: 16개 정수 리스트. Pillow 필요.
    """
    from PIL import Image, ImageFont, ImageDraw
    font = ImageFont.truetype(ttf_path, px, index=font_index)
    img = Image.new('L', (CELL, CELL), 0)
    draw = ImageDraw.Draw(img)
    # 가로만 중앙 정렬, 세로는 폰트 자연 베이스라인(고정 오프셋)
    try:
        bbox = draw.textbbox((0, 0), char, font=font)
        w = bbox[2] - bbox[0]
        ox = (CELL - w) // 2 - bbox[0] + x_offset
        oy = y_offset
    except Exception:
        ox, oy = x_offset, y_offset
    draw.text((ox, oy), char, fill=255, font=font)
    px_ = img.load()
    rows = []
    for y in range(CELL):
        word = 0
        for x in range(CELL):
            if px_[x, y] >= threshold:
                word |= (1 << (15 - x))
        rows.append(word)
    return rows


def bake_glyph(char: str, ttf_path: str, swap: bool = True, **rast_kw) -> bytes:
    """편의 함수: 글자 -> (래스터화 -> SWAP_HALVES) -> 32바이트 저장형 글리프."""
    rows = rasterize_ttf(char, ttf_path, **rast_kw)
    return bitmap_to_glyph(rows, swap=swap)


# --------------------------------------------------------------------------
# PNG 렌더 (검증용)
# --------------------------------------------------------------------------
def render_glyph_png(glyph32: bytes, path, swap: bool = True, scale: int = 8):
    """단일 글리프를 PNG로 저장. swap=True 는 게임 렌더러와 동일하게 표시."""
    from PIL import Image
    rows = glyph_to_bitmap(glyph32, swap=swap)
    img = Image.new('L', (CELL * scale, CELL * scale), 40)
    px = img.load()
    for r in range(CELL):
        for c in range(CELL):
            if (rows[r] >> (15 - c)) & 1:
                for sy in range(scale):
                    for sx in range(scale):
                        px[c * scale + sx, r * scale + sy] = 255
    img.save(path)
    return path


def render_montage_png(glyphs, path, swap: bool = True, scale: int = 4, cols: int = 16):
    """여러 글리프를 격자 PNG로. glyphs = 32바이트 글리프 iterable."""
    from PIL import Image
    glyphs = list(glyphs)
    rows_n = (len(glyphs) + cols - 1) // cols
    cw = CELL * scale + 2
    img = Image.new('L', (cols * cw, rows_n * cw), 60)
    px = img.load()
    for gi, g in enumerate(glyphs):
        bx = (gi % cols) * cw
        by = (gi // cols) * cw
        bm = glyph_to_bitmap(g, swap=swap)
        for r in range(CELL):
            for c in range(CELL):
                if (bm[r] >> (15 - c)) & 1:
                    for sy in range(scale):
                        for sx in range(scale):
                            px[bx + c * scale + sx, by + r * scale + sy] = 255
    img.save(path)
    return path


# --------------------------------------------------------------------------
# 자체 검증 (무변경 라운드트립 + swap 자기역함수)
# --------------------------------------------------------------------------
def _selftest():
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    orig = root / 'original' / 'LANG1_FONT.DAT'
    fd = FontDat.load(orig)
    # 1) 무변경 라운드트립: 재직렬화 == 원본 바이트
    assert bytes(fd.data) == orig.read_bytes(), "roundtrip mismatch"
    # 2) swap 자기역함수
    g = fd.read_glyph(4, 0)             # 亜
    assert swap_halves(swap_halves(g)) == g
    # 3) 헤더/블록 요약
    print("blocks:", [(b[2]) for b in fd.blocks], "total", sum(b[2] for b in fd.blocks))
    print("selftest OK")


if __name__ == '__main__':
    _selftest()
