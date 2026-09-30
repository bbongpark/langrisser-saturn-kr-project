#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_translate_poc.py — VARIABLE-LENGTH Korean translation PoC (disc-in-place).

Proves the real translation path (not just same-length substitution):
  * a SCEN leaf segment is replaced with a natural Korean token stream whose
    byte length DIFFERS from the original;
  * scen_tool.serialize() recomputes every offset in the tree (block 20's
    subtree grows/shrinks -> later blocks shift -> root offsets shift);
  * the rebuilt SCEN is padded back to the file's 322-sector (659,456 B)
    allocation and written in place with EDC/ECC — no ISO9660 change needed
    as long as total <= 659,456 (LANG1/SCEN.DAT is exactly sector-full, but the
    demo keeps the edited segment <= original so total never exceeds budget).

Target: Ep1 prologue leaf (20,2,5), segment 0 (the goddess Lushiris intro).
Original (64 B):
  エルサリアへようこそ。{08}私の名は{09 45}。地上では{08}光の女神と呼ばれて{04 71}
New (pure Korean, control codes {08} line breaks preserved, name/MTE dropped):
  엘사리아에어서오세요。{08}내이름은루시리스。지상에서는{08}빛의여신이라불려요。
"""
import sys, io, os
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scen_tool, kr_font, kr_encoding, disc_tool, kr_render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "original")
BUILD = os.path.join(ROOT, "build")
DISCDIR = os.environ.get("LANGRISSER_DISC",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Langrisser - Dramatic Edition (Japan) (1M)"))
TRACK1 = os.path.join(DISCDIR, "Langrisser - Dramatic Edition (Japan) (1M) (Track 1).bin")
TTF = r"C:\Windows\Fonts\malgun.ttf"

LANG1_SCEN_LBA = 136946
LANG1_FONT_LBA = 135070
SCEN_ALLOC = 659456          # 322 sectors, exact file size (no ISO9660 change)

# Full render-driven pipeline: a plain Korean translation string (words separated
# by spaces, punctuation attached) -> kr_render.render_message auto-typesets it
# into window(s) of encode-pieces (line wrap at 14 cells, {08} breaks). The
# prologue message fits one window (3 lines), so window 0 replaces seg0.
KOREAN_SEG0 = "엘사리아에 어서 오세요。 내 이름은 루시리스。 지상에선 빛의 여신。"
NEW_SEG0 = kr_render.render_message(KOREAN_SEG0, width=14, max_lines=3)[0]


def node_at(tree, path):
    n = tree
    for i in path:
        n = n.children[i]
    return n


def encode_pieces(pieces, table):
    out = bytearray()
    for kind, val in pieces:
        if kind == "kr":
            out += kr_encoding.encode_text(val, table)
        else:
            out += val
    return bytes(out)


def build(verbose=True):
    # 1) collect Korean syllables, assign empty-slot-first, load font
    fd = kr_font.FontDat.load(os.path.join(ORIG, "LANG1_FONT.DAT"))
    # only Hangul syllables need a baked slot; punctuation/space pass through as SJIS
    syllables = [ch for kind, val in NEW_SEG0 if kind == "kr"
                 for ch in val if kr_encoding.is_hangul(ch)]
    table = kr_encoding.build_table(syllables, fontdat=fd)
    if verbose:
        print(f"unique syllables: {table['used']}  (empty slots avail {table['empty_supply']})")

    # 2) bake each syllable glyph into its assigned slot
    for syl in table['order']:
        info = table['map'][syl]
        glyph = kr_font.bake_glyph(syl, TTF, swap=True)
        fd.patch_font(fd.block_glyph_offset(info['block'], info['index']), glyph)
    font_patched = fd.data
    assert len(font_patched) == os.path.getsize(os.path.join(ORIG, "LANG1_FONT.DAT"))

    # 3) build new segment bytes, splice into leaf (20,2,5) segment 0
    new_seg0 = encode_pieces(NEW_SEG0, table)
    with open(os.path.join(ORIG, "LANG1_SCEN.DAT"), "rb") as f:
        scen_orig = f.read()
    tree = scen_tool.parse(scen_orig)
    leaf = node_at(tree, (20, 2, 5))
    segs = leaf.raw.split(b"\x00")
    old_seg0 = segs[0]
    delta = len(new_seg0) - len(old_seg0)
    if verbose:
        print(f"seg0: {len(old_seg0)} B -> {len(new_seg0)} B  (delta {delta:+d})")
    segs[0] = new_seg0
    leaf.raw = b"\x00".join(segs)

    # 3b) growth reclaim: LANG1/SCEN.DAT is exactly sector-full (no ISO9660 room to
    #     grow the file). Leaf (20,4) is a dedicated 1,580-byte all-zero padding leaf
    #     holding the file's tail. Trim `delta` zero bytes from it so the rebuilt
    #     total stays within the 322-sector allocation.
    if delta > 0:
        pad = node_at(tree, (20, 4))
        assert all(b == 0 for b in pad.raw), "padding leaf (20,4) is not all-zero"
        assert len(pad.raw) >= delta, f"growth {delta} exceeds padding slack {len(pad.raw)}"
        pad.raw = pad.raw[:len(pad.raw) - delta]
        if verbose:
            print(f"reclaimed {delta} B from padding leaf (20,4) -> {len(pad.raw)} B left")

    # 4) serialize (recomputes ALL offsets), assert within budget, pad to alloc
    scen_new = bytes(scen_tool.serialize(tree))
    if verbose:
        print(f"SCEN total: {len(scen_orig):,} -> {len(scen_new):,}  (budget {SCEN_ALLOC:,})")
    assert len(scen_new) <= SCEN_ALLOC, f"SCEN {len(scen_new)} exceeds 322-sector alloc"
    scen_padded = scen_new + b"\x00" * (SCEN_ALLOC - len(scen_new))
    assert len(scen_padded) == SCEN_ALLOC

    # 5) write patched FONT + SCEN into a disc copy (in place, EDC/ECC)
    disc = disc_tool.Disc(TRACK1)
    disc.write_file(LANG1_FONT_LBA, font_patched)
    disc.write_file(LANG1_SCEN_LBA, scen_padded)
    out_track1 = os.path.join(BUILD, "Track 1 (patched).bin")
    disc.save(out_track1)

    # 6) self-check: re-extract and re-parse from the patched disc
    disc2 = disc_tool.Disc(out_track1)
    re_font = disc2.read_file(LANG1_FONT_LBA, len(font_patched))
    re_scen = disc2.read_file(LANG1_SCEN_LBA, SCEN_ALLOC)
    assert re_font == font_patched, "FONT re-extract mismatch"
    assert re_scen[:len(scen_new)] == scen_new, "SCEN re-extract mismatch"
    tree2 = scen_tool.parse(re_scen)
    seg0_rt = node_at(tree2, (20, 2, 5)).raw.split(b"\x00")[0]
    assert seg0_rt == new_seg0, "round-trip seg0 mismatch after re-parse"

    def sector_ok(lba):
        off = lba * disc_tool.RAW
        sec = bytearray(disc2.data[off:off + disc_tool.RAW])
        ref = bytes(sec)
        disc_tool.regen_sector(sec)
        return bytes(sec) == ref
    checks = [sector_ok(LANG1_SCEN_LBA), sector_ok(LANG1_SCEN_LBA + 10),
              sector_ok(LANG1_SCEN_LBA + 321)]  # last sector of the file
    if verbose:
        print(f"self-check: font OK, scen re-parse seg0 OK, EDC/ECC on changed "
              f"sectors (incl. last) = {all(checks)} {checks}")

    with open(os.path.join(BUILD, "LANG1_SCEN.translated.dat"), "wb") as f:
        f.write(scen_padded)
    if verbose:
        print(f"artifacts -> {out_track1}")
    return out_track1, table


if __name__ == "__main__":
    print("=== variable-length Korean translation PoC ===")
    out, table = build()
    print("\nAssignments (empty-slot-first):")
    for syl in table['order']:
        info = table['map'][syl]
        sh, sl = info['sjis']
        print(f"  '{syl}' -> SJIS {sh:02x}{sl:02x}  block{info['block']} idx{info['index']}")
    print("\nVariable-length pipeline: byte-validated. Cold-boot confirmation pending emucap.")
