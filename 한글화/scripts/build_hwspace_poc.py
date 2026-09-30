#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_hwspace_poc.py — {01} half-width-space SH-2 patch PoC.

Repurposes the (originally unused) text control code {01} as a half-width (+8px)
cursor advance, so Korean word spacing costs 8px instead of a fullwidth 16px.

RE (verified live on hardware, LANG1.BIN loads at RAM 0x06010000):
  * Text control-code dispatch at RAM 0x0602b1e0 (file 0x1b1e0):
      index = control_code - 1;  jump table base = 0x0602b1ec (file 0x1b1ec).
      valid codes 1..9. table[0]=0x12 -> {01} handler ENTRY 0x0602b1fe (NOT 0x2b204;
      the earlier note claiming table[0]=0x18 was wrong). The bytes at 0x1b204 are
      the 3rd instruction of that handler, so a patch there IS on the {01} path.
  * The renderer is an 8x8-cell VDP2 NBG. Per glyph it advances TWO cursors +2 each:
      [0x0609ab44] = @(3,r2) : horizontal CELL-COLUMN index -> POSITIONS the glyph.
      [0x0609ab4c] = @(5,r2) : a parallel counter that does NOT position glyphs.
      (r2 = struct base 0x0609ab38, a dispatch invariant.) Korean glyph = 16px = 2
      cells, so +2 = 16px. A half-width space = advance ab44 by +1 cell = 8px.
  * The {01} handler tail (file 0x1b204, 10 B) is replaced to bump ab44 by +1.

Patch @ file 0x1b204 (RAM 0x0602b204):
  orig: 61 33 71 01 22 12 61 30 a0 1a
  new : 51 23 71 01 12 13 a0 1b 00 09
        51 23  mov.l @(3,r2),r1   ; r1 = [0x0609ab44] (cell-column cursor)
        71 01  add   #1,r1        ; +1 cell = 8px (half-width)
        12 13  mov.l r1,@(3,r2)   ; [0x0609ab44] += 1
        a0 1b  bra   0x0602b244   ; return (PC+4+0x1b*2)
        00 09  nop                ; delay slot
  WRONG EARLIER PATCH: @(5,r2)=ab4c += 8 bumped the non-positioning counter ->
  zero visible spacing. ab44 is the real placement cursor (cold-boot verified).

Then the Korean translation uses control code {01} (0x01) for word spacing.
Since {01} appears ONLY in our patched text, a wrong handler cannot affect any
original code path.
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
PATCH_ORIG = bytes.fromhex("6133710122126130a01a")   # 10 B we overwrite
# Advance the horizontal CELL-COLUMN cursor [0x0609ab44] = @(3,r2) by +1 cell (8px).
# ab44 is what positions the next glyph (a normal glyph does ab44 += 2 = 16px).
# 51 23 (mov.l @(3,r2),r1) 71 01 (add #1,r1) 12 13 (mov.l r1,@(3,r2))
# a0 1b (bra 0x0602b244)   00 09 (nop, delay slot)
PATCH_NEW = bytes.fromhex("51237101" + "1213" + "a01b" + "0009")

PERIOD = b"\x81\x42"
HW_SPACE = b"\x01"          # {01} = half-width space (our SH-2 patch)
CTRL_08 = b"\x08"

# 3-line prologue window, half-width spaces between words
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
    print(f"LANG1.BIN patched @0x{PATCH_OFF:x}: {PATCH_ORIG.hex()} -> {PATCH_NEW.hex()}")
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
    assert len(PATCH_NEW) == 10, f"patch must be 10 bytes, got {len(PATCH_NEW)}"
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

    # self-check
    d2 = disc_tool.Disc(out)
    assert d2.read_file(LANG1_BIN_LBA, len(lang1_bin))[PATCH_OFF:PATCH_OFF + 10] == PATCH_NEW
    assert d2.read_file(LANG1_FONT_LBA, len(font_patched)) == font_patched
    assert d2.read_file(LANG1_SCEN_LBA, SCEN_ALLOC)[:len(scen_new)] == scen_new
    ok = all((lambda lba: (lambda s: (disc_tool.regen_sector(s) or True) and
             bytes(s) == d2.data[lba*disc_tool.RAW:lba*disc_tool.RAW+disc_tool.RAW])
             (bytearray(d2.data[lba*disc_tool.RAW:lba*disc_tool.RAW+disc_tool.RAW])))(l)
             for l in [LANG1_BIN_LBA, LANG1_FONT_LBA, LANG1_SCEN_LBA])
    print(f"self-check: LANG1.BIN/FONT/SCEN re-extract OK, EDC/ECC valid = {ok}")
    print(f"artifacts -> {out}")


if __name__ == "__main__":
    print("=== {01} half-width-space SH-2 patch PoC ===")
    build()
    print("\nCold-boot to verify half-width spacing (spaces = {01}, 8px each).")
