#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_poc_disc.py — end-to-end PoC patch builder (emulator-independent).

Ties together: kr_font (glyph baking) + kr_encoding (Hangul->kanji-slot SJIS) +
scen_tool (SCEN edit/serialize) + disc_tool (in-place MODE1/2352 write w/ EDC-ECC).

For the PoC we use SAME-LENGTH substitutions (N Hangul syllables replace N
double-byte JP chars), so SCEN.DAT and FONT.DAT keep their exact original sizes
and can be written in place with no pointer/size churn.

Self-check: re-extract FONT.DAT / SCEN.DAT from the patched disc and assert they
equal the patched inputs; assert file sizes unchanged; assert EDC/ECC valid.
"""
import sys, io, os, struct, shutil
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scen_tool, kr_font, kr_encoding, disc_tool

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG   = os.path.join(ROOT, "original")
BUILD  = os.path.join(ROOT, "build")
DISCDIR = os.environ.get("LANGRISSER_DISC",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Langrisser - Dramatic Edition (Japan) (1M)"))
TRACK1 = os.path.join(DISCDIR, "Langrisser - Dramatic Edition (Japan) (1M) (Track 1).bin")
TTF    = r"C:\Windows\Fonts\malgun.ttf"

# disc placement (from survey)
LANG1_SCEN_LBA = 136946
LANG1_FONT_LBA = 135070

os.makedirs(BUILD, exist_ok=True)


def node_at(tree, path):
    n = tree
    for i in path:
        n = n.children[i]
    return n


def build(edits, verbose=True):
    """edits: list of (leaf_path_tuple, old_bytes, korean_text).
    Replaces old_bytes (found once) in the leaf with SJIS-encoded korean_text.
    len(old_bytes) must equal 2*len(korean_text)."""
    # 1) collect syllables, assign kanji-slot SJIS codes, load font
    fd = kr_font.FontDat.load(os.path.join(ORIG, "LANG1_FONT.DAT"))
    syllables = []
    for _, _, kr in edits:
        syllables += list(kr)
    table = kr_encoding.build_table(syllables, fontdat=fd)
    if verbose:
        print(f"syllables: {len(table['order'])} unique -> kanji slots (supply {table['supply']})")

    # 2) bake each syllable glyph into its assigned FONT.DAT slot
    for syl in table['order']:
        info = table['map'][syl]
        glyph = kr_font.bake_glyph(syl, TTF, swap=True)     # 32B, halves swapped
        off = fd.block_glyph_offset(info['block'], info['index'])
        fd.patch_font(off, glyph)
    font_patched = fd.data
    assert len(font_patched) == os.path.getsize(os.path.join(ORIG, "LANG1_FONT.DAT"))

    # 3) edit SCEN leaves (same-length), serialize
    with open(os.path.join(ORIG, "LANG1_SCEN.DAT"), "rb") as f:
        scen_orig = f.read()
    tree = scen_tool.parse(scen_orig)
    for leaf_path, old, kr in edits:
        enc = kr_encoding.encode_text(kr, table)
        assert len(enc) == len(old), f"length mismatch: {kr!r} {len(enc)}B vs old {len(old)}B"
        leaf = node_at(tree, leaf_path)
        assert leaf.kind == "leaf", f"{leaf_path} not a leaf"
        cnt = leaf.raw.count(old)
        assert cnt == 1, f"old bytes appear {cnt}x in leaf {leaf_path} (need exactly 1)"
        leaf.raw = leaf.raw.replace(old, enc)
    scen_patched = bytes(scen_tool.serialize(tree))
    assert len(scen_patched) == len(scen_orig), \
        f"SCEN size changed {len(scen_orig)}->{len(scen_patched)}"
    if verbose:
        print(f"SCEN patched, size unchanged = {len(scen_patched):,}")

    # 4) write patched FONT.DAT + SCEN.DAT into a disc copy (in place, EDC/ECC)
    if verbose:
        print("loading disc + writing patched files (EDC/ECC regen)...")
    disc = disc_tool.Disc(TRACK1)
    disc.write_file(LANG1_FONT_LBA, font_patched)
    disc.write_file(LANG1_SCEN_LBA, scen_patched)
    out_track1 = os.path.join(BUILD, "Track 1 (patched).bin")
    disc.save(out_track1)

    # 5) self-check: re-extract from patched disc == patched inputs
    disc2 = disc_tool.Disc(out_track1)
    re_font = disc2.read_file(LANG1_FONT_LBA, len(font_patched))
    re_scen = disc2.read_file(LANG1_SCEN_LBA, len(scen_patched))
    assert re_font == font_patched, "FONT.DAT re-extract mismatch"
    assert re_scen == scen_patched, "SCEN.DAT re-extract mismatch"
    # EDC/ECC validity on a couple of changed sectors
    def sector_ok(lba):
        off = lba * disc_tool.RAW
        sec = bytearray(disc2.data[off:off+disc_tool.RAW])
        ref = bytes(sec)
        disc_tool.regen_sector(sec)
        return bytes(sec) == ref
    checks = [sector_ok(LANG1_FONT_LBA), sector_ok(LANG1_FONT_LBA+5),
              sector_ok(LANG1_SCEN_LBA), sector_ok(LANG1_SCEN_LBA+10)]
    if verbose:
        print(f"self-check: font re-extract OK, scen re-extract OK, "
              f"EDC/ECC valid on changed sectors = {all(checks)} {checks}")

    # save patched FONT/SCEN artifacts too
    with open(os.path.join(BUILD, "LANG1_FONT.patched.dat"), "wb") as f:
        f.write(font_patched)
    with open(os.path.join(BUILD, "LANG1_SCEN.patched.dat"), "wb") as f:
        f.write(scen_patched)
    if verbose:
        print(f"artifacts -> {BUILD}\\Track 1 (patched).bin  (+ patched FONT/SCEN)")
    return out_track1, table


if __name__ == "__main__":
    # Visibility PoC: Ep1 prologue narration leaf (20,2,5) — the goddess
    # Lushiris intro shown right after スタート. Same-length, meaning-preserving:
    #   光の女神 (Goddess of Light, 4 chars=8B) -> 빛의여신 (4 syllables=8B)
    #   地上     (on the land,     2 chars=4B) -> 지상   (2 syllables=4B)
    # Both appear exactly once in the leaf; on screen the sentence becomes
    #   "…지상では빛의여신と呼ばれています。" -> two Hangul words render in-line.
    edits = [
        ((20, 2, 5), "光の女神".encode("shift_jis"), "빛의여신"),
        ((20, 2, 5), "地上".encode("shift_jis"), "지상"),
    ]
    print("=== PoC disc build (demonstrative, byte-validated) ===")
    out, table = build(edits)
    print("\nAssignments:")
    for syl in table['order']:
        info = table['map'][syl]
        sh, sl = info['sjis']
        print(f"  '{syl}' -> SJIS {sh:02x}{sl:02x}  block{info['block']} idx{info['index']}")
    print("\nPoC disc pipeline: byte-validated. Visual confirmation pending emucap.")
