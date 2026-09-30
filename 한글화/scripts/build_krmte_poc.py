#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_krmte_poc.py — prove the game's {04} MTE decoder renders KOREAN fragments.

Repurposes one unused block-20 MTE dict entry (idx 36 = {04:37}, 6 bytes) with a
3-syllable Korean fragment "여신님" (also 6 bytes -> dict leaf size unchanged), and
references it via {04:37} in the prologue. If the goddess line shows "여신님" via the
MTE code, the {04} decoder does verbatim byte substitution on Korean too -> kr_mte
(Korean dictionary compression) is viable for budget-tight blocks.

Block-20 size is kept constant (alignment-preserving); LANG1.BIN {01} half-width
patch applied so spaces render at 8px.
"""
import sys, io, os
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scen_tool, kr_font, kr_encoding, kr_markup, disc_tool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "original")
BUILD = os.path.join(ROOT, "build")
DISCDIR = os.environ.get("LANGRISSER_DISC",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Langrisser - Dramatic Edition (Japan) (1M)"))
TRACK1 = os.path.join(DISCDIR, "Langrisser - Dramatic Edition (Japan) (1M) (Track 1).bin")
TTF = r"C:\Windows\Fonts\malgun.ttf"

SCEN_LBA, FONT_LBA, BIN_LBA, ALLOC = 136946, 135070, 202, 659456
BIN_PATCH = (0x1b204, bytes.fromhex("6133710122126130a01a"),
             bytes.fromhex("512571081215a01b0009"))
DICT_IDX = 36                       # {04:37}, 6-byte unused entry in block 20
FRAGMENT = "여신님"                  # 3 syllables = 6 bytes (matches entry length)
# prologue line 3 references the fragment via [MTE:25] (hex 0x25 = 37 = idx 36 + 1)
SEG0_KR = "엘사리아에 어서 오세요。[NL]내 이름은 루시리스。[NL]지상에선 빛의 [MTE:25]。"


def node_at(tree, path):
    n = tree
    for i in path:
        n = n.children[i]
    return n


def enc_pieces(pieces, table):
    return b"".join(kr_encoding.encode_text(v, table) if k == "kr" else v
                    for k, v in pieces)


def build():
    fd = kr_font.FontDat.load(os.path.join(ORIG, "LANG1_FONT.DAT"))
    syls = [c for k, v in kr_markup.parse_markup(SEG0_KR) if k == "kr"
            for c in v if kr_encoding.is_hangul(c)] + list(FRAGMENT)
    table = kr_encoding.build_table(syls, fontdat=fd)
    for s in table["order"]:
        info = table["map"][s]
        fd.patch_font(fd.block_glyph_offset(info["block"], info["index"]),
                      kr_font.bake_glyph(s, TTF, swap=True))
    font_patched = fd.data

    scen = open(os.path.join(ORIG, "LANG1_SCEN.DAT"), "rb").read()
    tree = scen_tool.parse(scen)
    before = len(scen_tool.serialize(tree.children[20], bytearray()))

    # (a) swap dict entry 36 -> encoded Korean fragment (same 6-byte length)
    frag_bytes = kr_encoding.encode_text(FRAGMENT, table)
    dict_leaf = node_at(tree, (20, 2, 4))
    entries = dict_leaf.raw.split(b"\x00")
    assert len(entries[DICT_IDX]) == len(frag_bytes), \
        f"length mismatch {len(entries[DICT_IDX])} vs {len(frag_bytes)}"
    entries[DICT_IDX] = frag_bytes
    dict_leaf.raw = b"\x00".join(entries)

    # (b) prologue seg0 -> Korean with [MTE:37] reference
    leaf = node_at(tree, (20, 2, 5))
    segs = leaf.raw.split(b"\x00")
    segs[0] = enc_pieces(kr_markup.parse_markup(SEG0_KR), table)
    leaf.raw = b"\x00".join(segs)

    # (c) keep block-20 size constant via its padding leaf (20,4)
    delta = len(scen_tool.serialize(tree.children[20], bytearray())) - before
    pad = node_at(tree, (20, 4))
    assert all(b == 0 for b in pad.raw)
    if delta > 0:
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
    print(f"{{04:37}} dict entry -> {FRAGMENT!r} ({frag_bytes.hex()}), block20 size "
          f"preserved, seg0 uses [MTE:37]. Cold-boot: line 3 should read '빛의 여신님。'")


if __name__ == "__main__":
    print("=== kr_mte {04}->Korean fragment PoC ===")
    build()
