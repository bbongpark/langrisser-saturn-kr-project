#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IMG.DAT 메뉴 그래픽 라벨 한글화 — 兵士配属 → 병사배속 (첫 라벨, end-to-end).

원본 4bpp 글리프는 니블 0(bg)/1(AA)/3(main)만 사용. 한글도 동일 스킴으로 렌더해
게임 팔레트가 동일 색으로 칠하게 한다. Gulim(굴림) 16px 임베디드 비트맵 사용.

라벨 소스: LANG1_IMG.DAT res#29, LANG2_IMG.DAT res#27 (兵士配属 16타일 각 확증).
각 한자(2x2 타일)를 대응 한글 음절로 치환 → compress → build_archive.
"""
import struct, sys, io, os
from PIL import Image, ImageFont, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from img_codec import parse_archive, build_archive, decompress, compress

FONT = "C:/Windows/Fonts/gulim.ttc"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# 兵士配属 각 한자의 VRAM charno (2x2: TL,TR,BL,BR) — Ep1 배틀프렙 라이브 타일맵에서 확증
KANJI_CHARNO = {
    "兵": [0x143c, 0x143d, 0x143e, 0x143f],
    "士": [0x1440, 0x1441, 0x1442, 0x1443],
    "配": [0x1434, 0x1435, 0x1436, 0x1437],
    "属": [0x1444, 0x1445, 0x1446, 0x1447],
}
# 화면 표시 순서(=치환 매핑): 兵→병, 士→사, 配→배, 属→속
LABEL = [("兵", "병"), ("士", "사"), ("配", "배"), ("属", "속")]


def syl_nibbles(ch, size=15):
    """한글 음절 -> 16x16 니블 그리드 (0 bg, 3 main, 1 AA 테두리)."""
    img = Image.new("L", (16, 16), 0)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, size)
    bb = d.textbbox((0, 0), ch, font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((16 - w) // 2 - bb[0], (16 - h) // 2 - bb[1]), ch, fill=255, font=f)
    on = [[1 if img.getpixel((x, y)) >= 128 else 0 for x in range(16)] for y in range(16)]
    nib = [[3 if on[y][x] else 0 for x in range(16)] for y in range(16)]
    for y in range(16):
        for x in range(16):
            if nib[y][x] == 0:
                if any(0 <= x+dx < 16 and 0 <= y+dy < 16 and on[y+dy][x+dx]
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    nib[y][x] = 1
    return nib


def nib_to_tiles(nib):
    """16x16 니블 -> 4 타일 (TL,TR,BL,BR) 각 32B 4bpp."""
    tiles = []
    for qy, qx in ((0, 0), (0, 1), (1, 0), (1, 1)):
        t = bytearray()
        for row in range(8):
            for cx in range(4):
                hi = nib[qy*8+row][qx*8+cx*2]
                lo = nib[qy*8+row][qx*8+cx*2+1]
                t.append((hi << 4) | lo)
        tiles.append(bytes(t))
    return tiles


def patch_resource(raw, kanji_tiles, kr_tiles_by_kanji):
    """decompressed raw에서 각 한자 타일(byte열)을 찾아 대응 한글 타일로 치환."""
    out = bytearray(raw)
    replaced = 0
    for kj, orig4 in kanji_tiles.items():
        kr4 = kr_tiles_by_kanji[kj]
        for q in range(4):
            pos = bytes(out).find(orig4[q])
            if pos < 0:
                raise RuntimeError(f"{kj} tile {q} not found in resource")
            out[pos:pos+32] = kr4[q]
            replaced += 1
    return bytes(out), replaced


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    # VRAM 덤프에서 원본 한자 타일 바이트 확보(정본)
    vram_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(DATA), "..", "..", "..",
        "AppData/Local/Temp/claude")  # fallback; pass explicitly
    # 실제로는 인자로 vdp2vram.bin 경로를 받음
    V = open(sys.argv[1], "rb").read()
    def vtile(c): return V[c*32:c*32+32]
    kanji_tiles = {kj: [vtile(c) for c in ch] for kj, ch in KANJI_CHARNO.items()}

    # 한글 음절 타일 렌더 (한자 위치별)
    kr_tiles_by_kanji = {}
    for kj, kr in LABEL:
        kr_tiles_by_kanji[kj] = nib_to_tiles(syl_nibbles(kr, 15))

    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    for arch_name, idx in [("LANG1_IMG.DAT", 29), ("LANG2_IMG.DAT", 27)]:
        buf = open(os.path.join(DATA, arch_name), "rb").read()
        res = parse_archive(buf)
        raw = decompress(res[idx])
        patched, n = patch_resource(raw, kanji_tiles, kr_tiles_by_kanji)
        assert decompress(compress(patched)) == patched, "round-trip check failed"
        res[idx] = compress(patched)
        newbuf = build_archive(res)
        # verify: reparse+decompress => patched raw intact
        assert decompress(parse_archive(newbuf)[idx]) == patched
        outp = os.path.join(outdir, arch_name)
        open(outp, "wb").write(newbuf)
        print(f"{arch_name}: res#{idx} patched ({n} tiles), "
              f"archive 0x{len(buf):x} -> 0x{len(newbuf):x}, wrote {outp}")
    print("DONE: 兵士配属 -> 병사배속")


if __name__ == "__main__":
    main()
