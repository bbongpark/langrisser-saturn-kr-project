#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_page_poc.py — prove in-segment PAGE TURN ({06}{07}) for long Korean text.

Replaces the prologue seg0 (originally 3 lines / 1 page) with a LONG Korean
translation that kr_render.render_segment auto-paginates into TWO pages joined by
{06}{07}, all within a SINGLE segment (no added NUL segments -> script indices
intact). On hardware the window should show page 1 with the ▼ prompt, then clear
and show page 2 on input. Block-20 size kept constant; LANG1.BIN {01} patch applied.
"""
import sys, io, os
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scen_tool, kr_font, kr_encoding, kr_render, kr_markup, disc_tool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "original")
BUILD = os.path.join(ROOT, "build")
DISCDIR = os.environ.get("LANGRISSER_DISC",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Langrisser - Dramatic Edition (Japan) (1M)"))
TRACK1 = os.path.join(DISCDIR, "Langrisser - Dramatic Edition (Japan) (1M) (Track 1).bin")
TTF = r"C:\Windows\Fonts\malgun.ttf"

SCEN_LBA, FONT_LBA, BIN_LBA = 136946, 135070, 202
BIN_PATCH = (0x1b204, bytes.fromhex("6133710122126130a01a"),
             bytes.fromhex("512571081215a01b0009"))

# ~6 lines -> 2 pages of 3 lines, joined by {06}{07}
LONG_KR = ("엘사리아에 어서 오세요 제 이름은 루시리스 지상에서는 빛의 여신이라 "
           "불리고 있습니다 지금 이 세계는 어둠의 위협에 노출되려 하고 있습니다")


def node_at(tree, path):
    n = tree
    for i in path:
        n = n.children[i]
    return n


def build():
    fd = kr_font.FontDat.load(os.path.join(ORIG, "LANG1_FONT.DAT"))
    pieces = kr_render.render_segment(LONG_KR, width=14, window_lines=3)
    assert kr_markup.max_page_lines(pieces) <= 3
    syls = [c for k, v in pieces if k == "kr" for c in v if kr_encoding.is_hangul(c)]
    table = kr_encoding.build_table(syls, fontdat=fd)
    for s in table["order"]:
        info = table["map"][s]
        fd.patch_font(fd.block_glyph_offset(info["block"], info["index"]),
                      kr_font.bake_glyph(s, TTF, swap=True))
    font_patched = fd.data

    scen = open(os.path.join(ORIG, "LANG1_SCEN.DAT"), "rb").read()
    tree = scen_tool.parse(scen)
    before = len(scen_tool.serialize(tree.children[20], bytearray()))

    leaf = node_at(tree, (20, 2, 5))
    segs = leaf.raw.split(b"\x00")
    npages = 1 + kr_markup._raw_bytes(pieces).count(bytes(kr_render.PAGE_BREAK))
    segs[0] = b"".join(kr_encoding.encode_text(v, table) if k == "kr" else v
                       for k, v in pieces)
    leaf.raw = b"\x00".join(segs)

    delta = len(scen_tool.serialize(tree.children[20], bytearray())) - before
    pad = node_at(tree, (20, 4))
    assert all(b == 0 for b in pad.raw)
    if delta > 0:
        assert len(pad.raw) >= delta, f"growth {delta} > padding {len(pad.raw)}"
        pad.raw = pad.raw[:len(pad.raw) - delta]
    elif delta < 0:
        pad.raw = pad.raw + b"\x00" * (-delta)
    assert len(scen_tool.serialize(tree.children[20], bytearray())) == before

    scen_new = bytes(scen_tool.serialize(tree))
    assert len(scen_new) == len(scen)

    disc = disc_tool.Disc(TRACK1)
    disc.write_file(FONT_LBA, font_patched)
    disc.write_file(SCEN_LBA, scen_new)
    off, o, nw = BIN_PATCH
    b = bytearray(open(os.path.join(ORIG, "LANG1.BIN"), "rb").read())
    assert bytes(b[off:off+len(o)]) == o
    b[off:off+len(nw)] = nw
    disc.write_file(BIN_LBA, bytes(b))
    disc.save(os.path.join(BUILD, "Track 1 (patched).bin"))
    print(f"seg0 -> {npages} pages ({{06}}{{07}} in-segment), block20 size preserved.")
    print(f"preview: {kr_render.pieces_preview(pieces)}")


if __name__ == "__main__":
    print("=== in-segment page-turn PoC ===")
    build()
