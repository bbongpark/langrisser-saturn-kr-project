#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dump_tiles.py — IMG.DAT 리소스를 4bpp 8x8 타일 시트 PNG로 뽑는다.

세션22 준비: 8px HUD 병종명(솔져/하피…)을 **런타임 VRAM 트릭 없이** 한글화하려면
그 타일이 실제로 어느 리소스의 몇 번 타일인지 눈으로 확인해야 한다. res#0이
256타일(8196B)이고 gen_hud8이 이미 res#0 타일 48~55(히라가나)를 한글로 재구운 전례가
있으므로 res#0이 8px 타일셋으로 유력하다.

사용:
  python scripts/img_re/dump_tiles.py            # L1/L2 res#0 시트
  python scripts/img_re/dump_tiles.py --res 0 1 27 --tag L2
  python scripts/img_re/dump_tiles.py --index    # 타일 번호 눈금 포함(기본 ON)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from img_codec import parse_archive, decompress          # noqa: E402
from PIL import Image, ImageDraw                          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ORIG = os.path.join(ROOT, "original")
OUT = os.path.join(ROOT, "build", "tiles")
FILES = {"L1": "LANG1_IMG.DAT", "L2": "LANG2_IMG.DAT"}
SCALE = 4            # 타일 확대 배율
COLS = 16            # 한 줄에 타일 16개


def tile_pixels(b):
    """4bpp 8x8 타일 32B -> 8x8 색인(0..15) 2차원 배열."""
    out = []
    for y in range(8):
        row = []
        for byte in b[y * 4:(y + 1) * 4]:
            row.append(byte >> 4)
            row.append(byte & 0xF)
        out.append(row)
    return out


def sheet(data, cols=COLS, scale=SCALE, label=True):
    n = len(data) // 32
    rows = (n + cols - 1) // cols
    cw, ch = 8 * scale, 8 * scale
    pad = 12 if label else 0
    img = Image.new("RGB", (cols * (cw + 2) + 24, rows * (ch + 2 + pad) + 12), (24, 24, 28))
    d = ImageDraw.Draw(img)
    for t in range(n):
        px = tile_pixels(data[t * 32:(t + 1) * 32])
        ox = 20 + (t % cols) * (cw + 2)
        oy = 8 + (t // cols) * (ch + 2 + pad)
        for y in range(8):
            for x in range(8):
                v = px[y][x]
                # 색인 0 = 투명/배경. 나머지는 명도로 (실 팔레트는 씬마다 다름)
                c = (40, 40, 48) if v == 0 else (255, 255, 255) if v == 1 else (90 + v * 10,) * 3
                d.rectangle([ox + x * scale, oy + y * scale,
                             ox + x * scale + scale - 1, oy + y * scale + scale - 1], fill=c)
        if label:
            d.text((ox, oy + ch + 1), f"{t}", fill=(150, 150, 160))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", nargs="*", default=["L1", "L2"])
    ap.add_argument("--res", nargs="*", type=int, default=[0])
    ap.add_argument("--scale", type=int, default=SCALE)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    for tag in a.tag:
        buf = open(os.path.join(ORIG, FILES[tag]), "rb").read()
        res = parse_archive(buf)
        for i in a.res:
            if i >= len(res) or not res[i]:
                print(f"{tag} res#{i}: 없음")
                continue
            data = decompress(res[i])
            p = os.path.join(OUT, f"{tag}_res{i:03d}.png")
            sheet(data, scale=a.scale).save(p)
            print(f"{tag} res#{i}: {len(data)}B / 타일 {len(data)//32}개 -> {p}")


if __name__ == "__main__":
    main()
