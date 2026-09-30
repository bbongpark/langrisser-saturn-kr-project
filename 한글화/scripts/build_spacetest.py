#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_spacetest.py — isolate & verify the CORRECT half-width-space mechanism.

RE finding (this session, verified on hardware by register stepping):
  The text renderer is an 8x8-cell VDP2 NBG. A normal glyph advances TWO parallel
  cursors by +2 each: [0x0609ab44] (the horizontal CELL-COLUMN index that actually
  positions the next glyph) and [0x0609ab4c] (a parallel column counter). Korean
  glyphs are 16px = 2 cells wide, so +2 cells = 16px.

  The previous {01} patch advanced [0x0609ab4c] by +8 — but ab4c does NOT position
  glyphs; ab44 does. So {01} produced ZERO visible movement (the "no spacing at all"
  bug). The fix: advance ab44 (the real placement cursor) by +1 cell = 8px = a true
  half-width space.

Patch @ file 0x1b204 (RAM 0x0602b204), 10 bytes, replacing the ab4c+8 variant:
  51 23  mov.l @(3,r2),r1   ; r1 = [0x0609ab44]  (@(3,r2), r2=0x0609ab38)
  71 01  add   #1,r1        ; +1 cell (8px)
  12 13  mov.l r1,@(3,r2)   ; [0x0609ab44] += 1
  a0 1b  bra   0x0602b244   ; rejoin dispatcher
  00 09  nop                ; delay slot

This test writes ONLY seg0 of (20,2,5) as a known spaced string (rest stays
original Japanese) so the prologue's first window isolates the spacing mechanism.
"""
import sys, io, os
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scen_tool, kr_font, kr_encoding, disc_tool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "original")
BUILD = os.path.join(ROOT, "build")
DISCDIR = os.environ.get("LANGRISSER_DISC",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Langrisser - Dramatic Edition (Japan) (1M)"))
TRACK1 = os.path.join(DISCDIR, "Langrisser - Dramatic Edition (Japan) (1M) (Track 1).bin")
TTF = r"C:\Windows\Fonts\malgun.ttf"

LANG1_SCEN_LBA = 136946
LANG1_FONT_LBA = 135070
LANG1_BIN_LBA = 202
SCEN_ALLOC = 659456

PATCH_OFF = 0x1b204
PATCH_ORIG = bytes.fromhex("6133710122126130a01a")     # 10 B we overwrite
PATCH_NEW = bytes.fromhex("5123" + "7101" + "1213" + "a01b" + "0009")  # ab44 += 1

PERIOD = b"\x81\x42"
HW_SPACE = b"\x01"
CTRL_08 = b"\x08"

NEW_SEG0_PIECES = [
    ("kr", "엘사리아에"), ("raw", HW_SPACE), ("kr", "어서"), ("raw", HW_SPACE), ("kr", "오세요"), ("raw", PERIOD),
    ("raw", CTRL_08),
    ("kr", "내"), ("raw", HW_SPACE), ("kr", "이름은"), ("raw", HW_SPACE), ("kr", "루시리스"), ("raw", PERIOD),
    ("raw", CTRL_08),
    ("kr", "지상에선"), ("raw", HW_SPACE), ("kr", "빛의"), ("raw", HW_SPACE), ("kr", "여신"), ("raw", PERIOD),
]


def patch_lang1_bin():
    data = bytearray(open(os.path.join(ORIG, "LANG1.BIN"), "rb").read())
    cur = bytes(data[PATCH_OFF:PATCH_OFF + len(PATCH_ORIG)])
    assert cur == PATCH_ORIG, f"LANG1.BIN @0x{PATCH_OFF:x} unexpected: {cur.hex()} != {PATCH_ORIG.hex()}"
    data[PATCH_OFF:PATCH_OFF + len(PATCH_NEW)] = PATCH_NEW
    print(f"LANG1.BIN patched @0x{PATCH_OFF:x}: {PATCH_ORIG.hex()} -> {PATCH_NEW.hex()} (ab44 += 1)")
    return bytes(data)


def encode_pieces(pieces, table):
    out = bytearray()
    for kind, val in pieces:
        out += kr_encoding.encode_text(val, table) if kind == "kr" else val
    return bytes(out)


def node_at(tree, path):
    n = tree
    for i in path:
        n = n.children[i]
    return n


def build():
    assert len(PATCH_NEW) == 10
    lang1_bin = patch_lang1_bin()

    fd = kr_font.FontDat.load(os.path.join(ORIG, "LANG1_FONT.DAT"))
    syllables = [ch for k, v in NEW_SEG0_PIECES if k == "kr"
                 for ch in v if kr_encoding.is_hangul(ch)]
    table = kr_encoding.build_table(syllables, fontdat=fd)
    print(f"unique syllables: {table['used']}  (empty slots {table['empty_supply']})")
    for syl in table['order']:
        info = table['map'][syl]
        fd.patch_font(fd.block_glyph_offset(info['block'], info['index']),
                      kr_font.bake_glyph(syl, TTF, swap=True))
    font_patched = fd.data

    new_seg0 = encode_pieces(NEW_SEG0_PIECES, table)
    scen_orig = open(os.path.join(ORIG, "LANG1_SCEN.DAT"), "rb").read()
    tree = scen_tool.parse(scen_orig)
    leaf = node_at(tree, (20, 2, 5))
    segs = leaf.raw.split(b"\x00")
    delta = len(new_seg0) - len(segs[0])
    print(f"seg0: {len(segs[0])} -> {len(new_seg0)} B (delta {delta:+d})")
    segs[0] = new_seg0
    leaf.raw = b"\x00".join(segs)
    if delta > 0:
        pad = node_at(tree, (20, 4))
        assert all(b == 0 for b in pad.raw) and len(pad.raw) >= delta
        pad.raw = pad.raw[:len(pad.raw) - delta]
    scen_new = bytes(scen_tool.serialize(tree))
    assert len(scen_new) <= SCEN_ALLOC
    scen_padded = scen_new + b"\x00" * (SCEN_ALLOC - len(scen_new))

    disc = disc_tool.Disc(TRACK1)
    disc.write_file(LANG1_BIN_LBA, lang1_bin)
    disc.write_file(LANG1_FONT_LBA, font_patched)
    disc.write_file(LANG1_SCEN_LBA, scen_padded)
    out = os.path.join(BUILD, "Track 1 (patched).bin")
    disc.save(out)
    d2 = disc_tool.Disc(out)
    assert d2.read_file(LANG1_BIN_LBA, len(lang1_bin))[PATCH_OFF:PATCH_OFF + 10] == PATCH_NEW
    print(f"self-check OK. artifacts -> {out}")
    print("Cold-boot to verify: 엘사리아에 / 어서 / 오세요 should show 8px gaps.")


if __name__ == "__main__":
    print("=== half-width-space (ab44+=1) mechanism test ===")
    build()
