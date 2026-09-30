#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_classnames.py — Korean class/unit-type names for Langrisser I & II (LANG*.BIN),
16px render path (session 14 battle-safe redesign, 2026-07-18).

SESSION-14 REDESIGN (why the session-12 layout is gone):
  The battle-animation "overlay" of session 13 turned out to be the battle engine
  using several BIN-tail regions as LIVE, MUTABLE DATA at fixed RAM addresses:
    * conv_old's back half is not conversion table at all — it is a live pointer
      array (0x0602xxxx workraml addresses). Caving it = corrupting battle state.
    * every zero-looking "dead zone" in the tail doubles as battle scratch, and
      the non-zero spans are referenced data (90+ absolute pointers each).
    * workraml (IMG.DAT slack) is NOT scene-stable either: the archive floats
      (base 0x00200000 in prep, +0x164 in the Ep2 battle map — live-measured),
      so fixed blob_src/cave addresses there silently break per scene.
  => The ONLY space that is load-base-stable AND battle-untouched is the class
  string region itself ([str_table, ptr_table), minus the battle window
  0x619fc-0x61a7d) plus, for L1, the true dead zeros 0x64c94-0x64d68.
  New layout, touching NOTHING outside game-owned string bytes + 2 literals:
    * conv table copy (512B, Korean entries overwritten) -> conv_dst = str_table.
      conv_old region is left 100% ORIGINAL (it is live data).
    * Korean single strings, suffix-merge packed, -> str_chunks (front slack
      after the table, the region tail past the battle window, and for L1 the
      two dead-zero chunks). ptr_table repointed. Battle windows asserted intact.
    * lit_lead/lit_trail -> conv_dst. No hooks, no caves, no code changes.
  The 8px HUD path (KR_HUD8, DEFAULT ON since late session 14) got its
  battle-safe scene-stable home too: caves resident at CAVE_RAM (0x060FFC00,
  untouched by the game), fed from a payload in the FONT.DAT tail (VDP2-resident
  in every scene) by a loader wrapper hooked via the font-upload literals.

SESSION-22 REDESIGN (the 8px tile blob is gone):
  Sessions 14/15 also shipped the 8px GLYPHS in that payload and healed them
  VDP2->VDP2 into an empty char bank from the caves. Yaba Sanshiro (Android)
  does not reproduce SH-2 writes into VDP2 VRAM, so on the user's handheld the
  bank stayed garbage and every 8px name rendered as mosaic. The glyphs now live
  in IMG.DAT resources (res#0/res#5/res#1) that the game itself decompresses
  into VRAM, and the caves do nothing but turn an index byte into a PND word via
  a 5-entry segment table (see TILE_SEGMENTS / _seg_table / _ktile_prog). No
  heal, no magic check, no blob — only vanilla load paths put pixels in VRAM.

(Original session-12 design notes kept below for the 8px machinery reference;
 addresses there — bank 13, workraml blob — are superseded by the constants.)

Class names are NOT in SCEN. Each name string is consumed by TWO renderers:
  * 16px info panels: index-byte string -> CONVERSION table ((byte+0x60)&0xFF ->
    2-byte SJIS) -> text engine + FONT.DAT. Both pc-relative literals (lead@lit_lead,
    trail@lit_trail) must point at the same table (tech-doc §7.4, session 4).
  * 8px HUD/hire rows: the SAME bytes -> tile classifier at `cls` (>0xb0 -> -112 /
    ==0xb0 -> 110 / ==0xa5 -> 32 / else -53) -> tilemap-shadow primitive. The
    primitive builds the NBG3 pattern-name word as ((tile>>8)+1)<<12 | tile&0xFF —
    i.e. tile's high byte selects the PALETTE, so it can only reach res#0's 256
    tiles.  BUT the layer runs 1-word PND aux mode 1 (live-verified session 12):
    PNT bits [11:0] are ALL charno -> VRAM 0x20000..0x3FFFF is addressable.

Design (session 12, replaces the session-5 dual-string scheme):
  1. Strings are stored SINGLE: [korean index bytes][NUL] in the original string
     region. The 16px converter reads them natively (its session-5 entry hook is
     GONE — entry must be original, asserted). Korean is shorter than katakana,
     so no spill: the old conv table region (512B) is free and hosts the caves.
  2. The 8px classifier entry (12B at `cls`) jumps to CAVE8 which:
       - passes non-class strings (region check on r11) to the original branches,
       - maps index byte -> pool ordinal k (same 3-segment pool as _index_bytes:
         0xe0..0xff -> k=byte-224, 0x21..0x2f -> k=byte-1, 0x3a..0x9f -> k=byte-11),
       - runs the TILE_SEGMENTS lookup: r7 = flag|pal1|charno of that k's IMG.DAT
         tile (session 22; before that it was a flat 0x9E00+k into a healed bank).
  3. The primitive's two PNT-formula sites (16B each at prim_a/prim_b) jump to
     tiny caves: input bit15 set -> PNT = r7 & 0x7FFF (pal from bits [14:12]);
     else the original formula. Existing callers (palette variants 0x1xx..0x6xx)
     are bit15-clear and unaffected.
  4. Tiles themselves are baked by scripts/img_re/gen_hud8.py into the ALL-ZERO
     tiles of IMG.DAT resources 0/5/1, at exactly tile_slots()[k] — the same
     ordering this module assigns index bytes, so the two never drift.

build(binx, font_table, tag) -> (patched_binx, syllables). Round-trip (16px conv
+ 8px byte->tile arithmetic) verified for both files by the selftest.
"""
import sys, io, os, struct, json, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kr_encoding

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = 0x06010000

# === session-22: the 8px Korean tiles live in IMG.DAT, not in a runtime blob ===
# Sessions 14/15 kept an 8164B tile blob in the FONT.DAT payload and "healed" it
# VDP2->VDP2 into an empty char bank (0x3C000) from the classifier caves. That is
# an SH-2 write into VDP2 VRAM, and **Yaba Sanshiro (Android) does not reproduce
# it** — the bank stayed garbage there and the 8px class/character names rendered
# as mosaic (user report on RG34XX SP, session 21). PC mednafen was fine, which is
# exactly the session-20 lesson ("SH-2로 VDP2 VRAM에 직접 쓰면 화면에 안 나온다").
# => The tiles are now baked into IMG.DAT resources that the game decompresses
#    into VRAM over its OWN path (scripts/img_re/gen_hud8.py). No heal, no blob,
#    no magic check: the caves only turn an index byte into a PND word.
#
# PND word (1-word pattern name, aux mode 1 — live-verified session 12):
#     bit15   = our "korean tile" flag, consumed+stripped by the primitive caves
#     [14:12] = palette (1, same as the katakana the HUD normally draws)
#     [11:0]  = charno = (VDP2 VRAM addr - 0x20000) / 32
# Resource -> charno base (session-22 live survey, 100% byte-match in EVERY scene
# that draws 8px names: Ep1 prep / hire list / battle-VS / magic anim, Ep2 map /
# character making, and the user's own battle save state):
RES_CHARNO = {0: 0x000,              # res#0 -> VRAM 0x20000
              5: 0x100,              # res#5 -> VRAM 0x22000
              1: 0x300}              # res#1 -> VRAM 0x26000
# Slots = tiles that are ALL-ZERO in the original resources, so nothing the game
# draws is overwritten. In particular the 8px katakana (res#0 tiles 64-127) is
# left intact: the classifiers still fall through to it for every non-class
# string, and the battle-animation screen (8bpp NBG0, see _scene_guard) keeps
# rendering names the original way. (The user cleared overwriting katakana, but
# there is enough zero space that we do not need to — 221 slots >= 211 pool.)
#
# ⛔ "ALL-ZERO" IS NOT ENOUGH — the game draws some zero tiles as its BLANK.
#    First session-22 build put 토 at res#1 tile 128 and the map HUD's bottom-right
#    filled with 토: charno 0x380 is that panel's blank filler (12-14 refs in EVERY
#    pre-session-22 scene dump, so it is the game's own, not our text). The other
#    one is res#0 tile 0 (charno 0x000). Slots are therefore validated against
#    img_re/data/pnt_refs.json — the charnos observed in the NBG2/NBG3 pattern
#    name tables across 7 captured scenes. Never widen a segment without re-running
#    that scan (scratchpad pnt_scan.py / pick_slots.py, recipe in HANDOFF).
TILE_SEGMENTS = ((0, 174, 18),       # res#0 tiles 174-191
                 (0, 199, 57),       # res#0 tiles 199-255
                 (5, 188, 68),       # res#5 tiles 188-255
                 (1, 113, 15),       # res#1 tiles 113-127  ) 128 = the game's
                 (1, 129, 31),       # res#1 tiles 129-159  ) blank -> skipped
                 (1, 224, 32))       # res#1 tiles 224-255
TILE_CAPACITY = sum(n for _, _, n in TILE_SEGMENTS)      # 221
TILE_FLAG_BASE = 0x9000              # bit15 flag | pal1<<12 (charno added)


def tile_slots():
    """[(res#, tile)] indexed by pool ordinal k — the canonical k -> tile map.
    gen_hud8.py bakes the glyph for k at tile_slots()[k]; the caves compute the
    matching charno arithmetically (see _seg_table)."""
    out = []
    for res, first, n in TILE_SEGMENTS:
        out.extend((res, first + i) for i in range(n))
    return out


def k_to_pnd(k):
    """Python mirror of the caves' segment lookup: pool ordinal -> PND word."""
    res, tile = tile_slots()[k]
    return TILE_FLAG_BASE | (RES_CHARNO[res] + tile)


def _seg_table():
    """Cave lookup table [(bound, delta)]: the FIRST row with k < bound wins and
    yields pnd = (k + delta) & 0xFFFF. Deltas are stored as 16-bit words and get
    sign-extended by mov.w — harmless, the primitives mask the low 16 bits."""
    rows, k = [], 0
    for i, (res, first, n) in enumerate(TILE_SEGMENTS):
        delta = (TILE_FLAG_BASE + RES_CHARNO[res] + first - k) & 0xFFFF
        k += n
        # last row is the loop terminator: it must match any k
        rows.append((0x7FFF if i == len(TILE_SEGMENTS) - 1 else k, delta))
    return rows


def _seg_blob():
    return b"".join(struct.pack(">HH", b, d) for b, d in _seg_table())


# k -> PND, done in 7 instructions + a 20B table. r0 is clobbered by `mova`, so
# the r0-input variant stashes k in r4 first (dead there — the printers' join
# reloads it with `mov r0,r4`).
def _ktile_prog(kreg):
    if kreg == 7:                                # cave8: byte/k lives in r7
        return [("mova", "SEG"),
                ("w", 0x6203),      # mov r0,r2
                ("label", "sl"),
                ("w", 0x6125),      # mov.w @r2+,r1     bound
                ("w", 0x6325),      # mov.w @r2+,r3     delta
                ("w", 0x3713),      # cmp/ge r1,r7      T = k >= bound
                ("bt", "sl"),
                ("w", 0x373C)]      # add r3,r7         r7 = PND
    assert kreg == 0                             # bar/VS printers: k lives in r0
    return [("w", 0x6403),          # mov r0,r4         stash k
            ("mova", "SEG"),
            ("w", 0x6203),          # mov r0,r2
            ("label", "sl"),
            ("w", 0x6125),          # mov.w @r2+,r1
            ("w", 0x6325),          # mov.w @r2+,r3
            ("w", 0x3413),          # cmp/ge r1,r4
            ("bt", "sl"),
            ("w", 0x6043),          # mov r4,r0
            ("w", 0x303C)]          # add r3,r0         r0 = PND

# --- session-14 residency architecture (replaces workraml blob_off) ---
# payload = [cave code 1024B][8px tile blob 8164B] stored in the FONT.DAT tail
#           (the last 288 kanji cells of block 5, reserved out of the Korean bake).
#           FONT.DAT is byte-resident at VDP2 VRAM 0x40000 in EVERY scene
#           (prep / map / battle-VS live-verified) -> fixed scene-stable address.
#           (The old workraml IMG.DAT slack was NOT scene-stable: the archive
#           floats, e.g. +0x164 on the Ep2 battle map — live-measured.)
# caves   = payload[0:1008] copied to work RAM 0x060FFC00 (above the game's
#           initial SP [BIN entry sets SP=0x060FFC00], so game code never
#           reaches it; all scene dumps show it zero except three BIOS flag
#           bytes at 0x060FFFF7/FB/FF, which the 1008B copy cap protects.
#           The session-14 home 0x06004000 was WRONG: 0x06004000-0x06008000
#           is a game object WORKSPACE — the hire-troops flow instantiates a
#           template there [BIN 0x35e40, absolute self-refs to 0x06004000]
#           and clobbered the caves -> PC=0 crash, session 15) by a loader
#           WRAPPER: the boot/reload font-upload call sites fetch the loader
#           address from pc-relative literals, which we repoint to the wrapper
#           (jsr real loader -> copy caves -> rts). Caves refresh right after
#           every font (re)upload, when the payload is guaranteed in VDP2.
# blob    = GONE (session 22). The tile bytes now ride IMG.DAT; the payload is
#           cave code only. PAYLOAD_RESERVE is deliberately left at its
#           session-14 value so PAYLOAD_OFF / PAYLOAD_VDP2 (and therefore the
#           wrapper literal and the FONT.DAT cell reservation in reinsert_text)
#           do not move — the freed 8KB is simply unused font tail.
FONT_SIZE = 220732
CAVES_SIZE = 1024
PAYLOAD_SIZE = CAVES_SIZE                      # session 22: caves only
PAYLOAD_RESERVE = 9216                         # 288 font cells (frozen, see above)
PAYLOAD_OFF = FONT_SIZE - PAYLOAD_RESERVE      # 0x33A3C (4-aligned)
FONT_VDP2 = 0x25E40000
PAYLOAD_VDP2 = FONT_VDP2 + PAYLOAD_OFF
CAVE_RAM = 0x060FFC00                # above initial SP; see block comment
CAVES_LIMIT = 1008                   # RAM copy cap: stop before the BIOS flag
                                     # bytes at 0x060FFFF0+ (payload slot stays
                                     # 1024B so PAYLOAD_OFF/BLOB_SRC are stable)

# Per-episode layout (file offsets; RAM = BASE + offset).
#   ptr_table/str_*: class-name pointer/string tables (unchanged from session 4)
#   conv_old   : original conv table region -> now hosts cave8 + primitive caves
#   conv_new   : relocated conversion table (736B zero tail region)
#   lit_lead/lit_trail: 16px converter literals -> conv_new (unchanged)
#   conv_entry : 16px converter entry — must be ORIGINAL (session-5 hook removed)
#   cls        : 8px classifier '>0xb0' branch (12B) -> jump to cave8
#   prim_a/b   : the two 16B PNT-formula sites inside the shadow primitive
#   blob_off   : fixed IMG.DAT file offset of the 8px tile blob (workraml-resident)
CONFIGS = {
    "L1": dict(ptr_table=0x61c2c, str_table=0x617a0,
               str_lo=0x06071790, str_hi=0x06071c30,
               # session-14: conv table copy sits at the string-region head;
               # strings pack into battle-safe chunks (see module docstring).
               conv_dst=0x617a0,
               str_chunks=((0x619a0, 0x619f0),   # front slack, stops before window
                           (0x61a90, 0x61c2c),   # region tail past battle window
                           (0x64c98, 0x64d08),   # L1-only dead zeros (0 refs,
                           (0x64d10, 0x64d68)),  #  battle-untouched, orig 0)
               conv_old=0x62e78, conv_new=0x64c30,
               lit_lead=0x1b314, lit_trail=0x1b318,
               conv_entry=0x1b274, file_end=0x64f10,
               cls=0x2891c, prim_a=0x2c7ee, prim_b=0x2c808,
               bar_cls=0xc03e, bar_prim=0xbedc,
               vs_cls=0x24cc0, vs_prim=0x24b7a, vs_shadow=0x0609e610,
               char_ptr=0x62314,
               shuusei=(0x26f2c, 0x2e95e),
               # session-14: boot(0x46a)/reload font-upload call sites whose
               # loader literals get repointed to the wrapper; wrapper cave home
               # (original zeros past the battle window; boot-time-only code).
               boot1=0x46a, boot2=0x5f4,
               init_region=(0x64eb0, 0x64f10),
               hw_site=0x1b1fe, hw_queue=0x0604a1e0),
    "L2": dict(ptr_table=0x62674, str_table=0x62218,
               str_lo=0x06072200, str_hi=0x06073600,
               conv_dst=0x62218,
               str_chunks=((0x62418, 0x62674),),  # whole region is battle-safe
               conv_old=0x6388c, conv_new=0x65a28,
               lit_lead=0x1cffc, lit_trail=0x1d000,
               conv_entry=0x1cf5c, file_end=0x65d08,
               cls=0x2a690, prim_a=0x2e4e6, prim_b=0x2e500,
               bar_cls=0xdc6e, bar_prim=0xdb08,
               vs_cls=0x26994, vs_prim=0x26856, vs_shadow=0x060a3b80,
               char_ptr=0x62cc8,
               shuusei=(0x28ce0, 0x303de),
               boot1=0x46a, boot2=0x5e0,
               init_region=(0x65c28, 0x65d08),
               hw_site=0x1cee6, hw_queue=0x06014d1c),
}

# The 16px converter's function entry (must be ORIGINAL — the session-5 dual-string
# skip hook is no longer emitted; single strings feed the converter directly).
_ENTRY_ORIG = bytes.fromhex("2f862fe66144671c27788d40")
# HUD bar / VS-screen 8px printers (session 12b): two MORE independent 8px text
# systems consume the class strings — the bottom-bar printer (compose buffer ->
# live shadow copy loop) and a second printer writing a 64-cell-stride shadow with
# a bank-7 charset (PNT = 0x0700|tile). Each has its own byte->tile classifier and
# its own tiny primitive taking the tile in r4 as a BYTE. Both classifiers get the
# same region-check cave treatment; both primitives get a bit15-flag patch.
#   classifier 12B site: mov.w @(d,pc),r1(=0xb0); cmp/hi r1,r0; bf/s +0xC;
#                        mov r0,r1; bra +0x3C; add #-112,r1
_TXT_CLS_SIG = bytes.fromhex("30168f026103a0187190")   # site+2 .. site+11
#   bar primitive displaced 12B: extu.b r4,r4; extu.b r7,r7; mov #38,r1;
#                                mul.l r1,r6; sts macl,r0; add r5,r0
_BARPRIM_ORIG = bytes.fromhex("644c677ce1260617001a305c")
#   vs primitive displaced 12B:  extu.b r4,r4; shll2 r0 x3; add r5,r0; add r0,r0
_VSPRIM_ORIG = bytes.fromhex("644c400840084008305c300c")
# 8px classifier '>0xb0' branch, displaced into cave8 (identical in both BINs):
#   mov.w @(0x44,pc),r1(=0xb0); cmp/hi r1,r7; bf +2; add #-112,r7; bra join; mov r9,r6
_CLS_ORIG = bytes.fromhex("912237168b027790a00d6693")
# PNT formula site (identical x4 = 2 sites x 2 BINs):
#   mov r7,r2; shlr8; add #1; shll8; shll2; shll2; extu.b r7,r1; or r1,r2
_PRIM_ORIG = bytes.fromhex("627342197201421842084208617c221b")

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "..", "build")

# File-offset windows the battle engine writes at RAM-fixed addresses (session-13
# freeze dump, ±margin). The patch must leave these byte-identical to the
# original in BOTH BINs (same load base) — asserted at the end of build().
_BATTLE_WINDOWS = ((0x60680, 0x60790), (0x619f0, 0x61a90), (0x62ea0, 0x63078),
                   (0x64c8c, 0x64c98), (0x64d08, 0x64d10), (0x64d68, 0x64d70),
                   (0x64e28, 0x64eb0))

# names absent from the steam glossary (Ep1-only monster classes etc.)
_MANUAL = {"バンディッド": "밴디트", "アニキ": "아니키", "ノーブル": "노블",
           "アント": "앤트", "クイーンアント": "퀸앤트"}

# HUD character names (8px only) absent from steam_charnames/glossary — generic
# titles + minor NPCs. Korean must fit the original byte length (in-place strings).
_CHAR_MANUAL = {
    "イッパンヘイ": "일반병", "シキカン": "지휘관", "シサイ": "사제",
    "ムラビト": "주민", "カイゾク": "해적", "ジケイダン": "자경단",
    "テイコクシキカン": "제국지휘관", "アニキ": "아니키", "マジョ": "마녀",
    "シンカン": "신관", "テイコクヘイ": "제국병", "モンスター": "몬스터",
    "ヒーディアス": "히디아스", "ドラフィム": "드라핌",
    "ナゾノキシ": "수수께끼기사", "ギナム": "기남", "セイガル": "세이갈",
    "フォルガー": "포르가",
}


def read_pointers(binx, tag="L2"):
    """Return list of (ptr_file_off, ram_addr) for the contiguous class-name pointer
    table (entries pointing into that episode's string region)."""
    cfg = CONFIGS[tag]
    ptrs, off = [], cfg["ptr_table"]
    while True:
        v = struct.unpack(">I", binx[off:off + 4])[0]
        if cfg["str_lo"] <= v < cfg["str_hi"]:
            ptrs.append((off, v)); off += 4
        else:
            break
    return ptrs


def decode_name(binx, ram):
    """Decode an original (Japanese) class-name string to readable katakana."""
    i = ram - BASE
    j = i
    while binx[j] != 0:
        j += 1
    b = bytes(x for x in binx[i:j] if x >= 0xa0)      # drop control/space bytes
    return unicodedata.normalize("NFKC", b.decode("shift_jis", "replace"))


def _kr_map(binx, ptrs):
    """jp-name -> kr-name, from steam glossary + manual entries. Raises on any
    untranslated name — a blank class name in-game is a blocker (0원칙)."""
    glo = json.load(open(os.path.join(BUILD, "steam_glossary.json"), encoding="utf-8"))
    out, missing = {}, []
    for _, ram in ptrs:
        jp = decode_name(binx, ram)
        if jp and jp not in out:
            kr = glo.get(jp, _MANUAL.get(jp, ""))
            if not kr:
                missing.append(jp)
            out[jp] = kr
    if missing:
        raise ValueError("untranslated class names (add to steam_glossary/_MANUAL): "
                         + " / ".join(missing))
    return out


def _index_bytes():
    """Index-byte pool for Korean class syllables, in the EXACT order cave8's
    arithmetic assumes (k = ordinal here):
      0xe0..0xff -> k = byte-224  (0..31)
      0x21..0x2f -> k = byte-1    (32..46)
      0x3a..0x9f -> k = byte-11   (47..148)
    Excluded: 0xa0..0xdf (conv indices shared with katakana UI), 0x20/0x30-0x39
    (16px converter special-cases), 0xa5/0xb0/0xde/0xdf (8px classifier
    special-cases; all outside the pool ranges anyway). 149 slots."""
    return ([b for b in range(0xe0, 0x100)] +
            [b for b in range(0x21, 0x30)] +
            [b for b in range(0x3a, 0xa0)])


def syllable_list(binx, tag):
    """Unique Korean class-name syllables in index order. Used both here and by
    img_re/gen_hud8.py so the byte->tile and tile->glyph mappings agree."""
    ptrs = read_pointers(binx, tag)
    krmap = _kr_map(bytes(binx), ptrs)
    syllables = []
    for jp in krmap:
        for ch in krmap[jp]:
            if kr_encoding.is_hangul(ch) and ch not in syllables:
                syllables.append(ch)
    return syllables


def _char_ext_bytes():
    """Extension index-byte pool for CHARACTER-name syllables (8px-only strings;
    these bytes are NOT 16px-conv-safe and must never appear in class strings).
    The caves' fall-through arithmetic maps them as k = byte-11 (149..210).
    Excluded: 0xa6 (bar printer consumes it before our hook) and 0xde/0xdf
    (dakuten, consumed by every printer's loop head)."""
    return [b for b in range(0xa0, 0xde) if b != 0xa6]


def read_char_strings(binx, tag):
    """[(ram, raw_bytes)] for each UNIQUE character-name string of the HUD table,
    plus the (lo, hi) file-offset bounds of the string region."""
    cfg = CONFIGS[tag]
    off, ptrs = cfg["char_ptr"], []
    while True:
        v = struct.unpack(">I", binx[off:off + 4])[0]
        if 0x06010000 <= v < 0x06090000:
            ptrs.append(v); off += 4
        else:
            break
    out = []
    for ram in sorted(set(ptrs)):
        i = ram - BASE
        j = i
        while binx[j] != 0:
            j += 1
        out.append((ram, bytes(binx[i:j])))
    lo = min(r for r, _ in out) - BASE
    hi = max(r - BASE + len(raw) + 1 for r, raw in out)   # past last NUL
    assert hi <= cfg["char_ptr"], f"{tag} char strings overrun their pointer table"
    return out, lo, hi


def _char_kr_map(strings):
    """jp char name -> kr (steam_charnames > glossary > _CHAR_MANUAL). Raises on
    any untranslated, non-empty name."""
    charmap = json.load(open(os.path.join(BUILD, "steam_charnames.json"),
                             encoding="utf-8"))
    glo = json.load(open(os.path.join(BUILD, "steam_glossary.json"), encoding="utf-8"))
    out, missing = {}, []
    for _, raw in strings:
        jp = unicodedata.normalize(
            "NFKC", bytes(x for x in raw if x >= 0xa0).decode("shift_jis", "replace"))
        if not jp or jp in out:
            out.setdefault(jp, "")
            continue
        kr = charmap.get(jp) or glo.get(jp) or _CHAR_MANUAL.get(jp, "")
        if not kr:
            missing.append(jp)
        out[jp] = kr
    if missing:
        raise ValueError("untranslated char names (add to _CHAR_MANUAL): "
                         + " / ".join(missing))
    return out


def tile_map(binx, tag):
    """dict[k] = syllable for the 8px tile blob (k = blob tile index): class
    syllables at their pool ordinals (0..148) plus character-name syllables at
    k = ext_byte-11 (149..210, with a hole at 0xa6). gen_hud8.py renders from
    this so byte arithmetic in the caves and glyph positions always agree."""
    binx = bytes(binx)
    out = {}
    cls = syllable_list(binx, tag)
    for k, syl in enumerate(cls):
        out[k] = syl
    strings, _, _ = read_char_strings(binx, tag)
    krmap = _char_kr_map(strings)
    clsset = set(cls)
    ext = _char_ext_bytes()
    n = 0
    for _, raw in strings:
        jp = unicodedata.normalize(
            "NFKC", bytes(x for x in raw if x >= 0xa0).decode("shift_jis", "replace"))
        for ch in krmap.get(jp, ""):
            # ' ' is a legal "syllable" (blank glyph) — steam names like 드 모토프
            if (ch != " " and not kr_encoding.is_hangul(ch)) or ch in clsset:
                continue
            if ch not in out.values():
                if n >= len(ext):
                    raise ValueError(f"{tag} char syllables exceed extension pool")
                out[ext[n] - 11] = ch
                n += 1
    return out


# --------------------------------------------------------------------------
# SH-2 cave builders.  w() = big-endian 16-bit instruction word.
# --------------------------------------------------------------------------

# VDP2 CHCTLA (NBG0/1 char-control) SH-2 address. On prep/map screens NBG0 is
# 4bpp 1-word (CHCTLA bit4=0); on the battle ANIMATION screen NBG0 flips to
# 8bpp (bit4=1) and repurposes VRAM 0x3A000 (our tile bank) as background char
# data. The self-heal must NOT run there — so every classifier cave first tests
# this bit and, when set, falls through to the ORIGINAL katakana handler (no
# heal, no Korean tile). Names on the battle-anim screen stay katakana (safe);
# every other screen renders Korean. r0 clobber only (scratch in all caves).
CHCTLA_ADDR = 0x25F80028


def _w(x):
    return x.to_bytes(2, "big")


def _scene_guard(orig_label, save_r0=False):
    """⛔ 세션22에 **호출을 전부 제거**했다 (아래 CHCTLA 주석의 이유가 사라졌다).
    이 가드는 heal이 8bpp 씬에서 돌지 않게 하려고만 존재했는데, 세션22에 heal이
    없어졌다. 그런데 폴백 경로는 **일본어 카타카나가 아니라 우리 한글 인덱스
    바이트를 원본 산술로 해석**해 res#205를 엉뚱하게 인덱싱한다 → 전투 VS 화면
    병종명이 `LV` 같은 알파벳과 검은 타일로 나왔다(사용자 실기 보고, 세션22).
    예: '파'=0xe0 → 원본타일 112 → res#205 tile 112(작은 점 2개), '레'=0xeb →
    tile 123(전부 0=검정). 사진과 픽셀 단위로 일치했다.
    NBG0의 색상모드만 바뀌므로 우리 텍스트가 있는 NBG2/NBG3는 영향이 없고,
    res#0/#5/#1은 마법(8bpp) 씬에서도 100% 상주한다 — 가드가 필요 없다.
    (참고로 세션13의 전투애니 프리즈는 이 가드가 r3를 클로버한 탓이었다.)
    함수는 이력 보존용으로 남겨 둔다."""
    """prog fragment + lits: if VDP2 NBG0 is 8bpp (battle anim), jump to orig.
    tst #imm only takes R0, so the test needs r0. save_r0=True stashes the input
    byte on the STACK (not a GPR) — the bar/VS printers keep live values in every
    low register (r1..r3 included), so the guard must clobber NOTHING but r0, and
    r0 is restored. (cave8's classifier has r0 as documented scratch, so it omits
    the save.) Clobbering r3 here was the battle-animation freeze (session 13)."""
    pre = [("w", 0x2F06)] if save_r0 else []         # mov.l r0,@-r15  (push byte)
    post = [("w", 0x60F6)] if save_r0 else []         # mov.l @r15+,r0  (pop byte)
    return pre + [
        ("movl", 0, "CHCTLA"),  # mov.l @(..),r0   -> &CHCTLA
        ("w", 0x6001),          # mov.w @r0,r0
        ("w", 0xC810),          # tst #0x10,r0      T=1 if bit4 clear (not battle)
    ] + post + [
        ("bf", orig_label),     # bit4 set -> battle -> original path (byte in r0)
    ], {"CHCTLA": (CHCTLA_ADDR, 4)}


def _build_cave8(ranges, join_ram, resume_ram):
    """Main-renderer classifier cave: scene guard -> 2-range region check ->
    byte->k arithmetic -> segment lookup -> r7 = PND (bit15 flag|pal1|charno).
    Register use: r7=byte (in/out), r11=str ptr(+1); r0,r1,r2,r3 scratch (the
    primitive reloads its own). Session 22: the self-heal AND the 8bpp scene
    guard are GONE — see _scene_guard's docstring."""
    chk, chk_lits = _region_check(0x3B12, ranges, "kr", "orig")   # ptr reg = r11
    return _asm(chk + [
        ("label", "kr"),
        ("w", 0xE1E0),          # mov #-32,r1
        ("w", 0x611C),          # extu.b r1,r1        0xE0
        ("w", 0x3712),          # cmp/hs r1,r7
        ("bf", "s2"),
        ("w", 0x7790),          # add #-112,r7
        ("w", 0x7790),          # add #-112,r7        k = b-224
        ("bra", "tile"),
        ("w", 0x0009),
        ("label", "s2"),
        ("w", 0xE130),          # mov #0x30,r1
        ("w", 0x3712),          # cmp/hs r1,r7
        ("bt", "s3"),
        ("w", 0x77FF),          # add #-1,r7          k = b-1  (0x21..0x2f)
        ("bra", "tile"),
        ("w", 0x0009),
        ("label", "s3"),
        ("w", 0x77F5),          # add #-11,r7         k = b-11 (0x3a..0x9f, 0xa0+ ext)
        ("label", "tile"),
    ] + _ktile_prog(7) + [
        ("w", 0x6693),          # mov r9,r6
        ("movl", 1, "JOIN"),
        ("w", 0x412B),          # jmp @r1
        ("w", 0x0009),
        ("label", "orig"),
        ("w", 0xE1B0),          # mov #-80,r1
        ("w", 0x611C),          # extu.b r1,r1        0xB0 (resume chain expects r1)
        ("w", 0x3716),          # cmp/hi r1,r7
        ("bf", "resume"),
        ("w", 0x7790),          # add #-112,r7
        ("w", 0x6693),          # mov r9,r6
        ("movl", 1, "JOIN"),
        ("w", 0x412B),          # jmp @r1
        ("w", 0x0009),
        ("label", "resume"),
        ("movl", 2, "RES"),     # r1 must keep 0xB0
        ("w", 0x422B),          # jmp @r2
        ("w", 0x0009),
    ], {**chk_lits,
        "JOIN": (join_ram, 4), "RES": (resume_ram, 4),
        "SEG": (_seg_blob(), len(_seg_blob()))})


def _asm(prog, lits):
    """Tiny 2-pass SH-2 assembler for the session-12b caves.
    prog: list of ops — ("w", word) | ("label", name) | ("bf"/"bt"/"bra", name)
          | ("movl", reg, key) | ("movw", reg, key)
    lits: {key: (value, size)} with size 4 or 2. Pool: longs (4-aligned) then words.
    Returns bytes (code + pool, padded to 4)."""
    n = sum(0 if op[0] == "label" else 1 for op in prog)
    code_len = n * 2
    pool_base = (code_len + 3) & ~3
    offs, off = {}, pool_base
    # 4-aligned entries (longs AND multi-longword blobs, e.g. the session-22
    # segment table that `mova` needs 4-aligned) first, then the 2B words.
    for k, (v, sz) in [(k, v) for k, v in lits.items() if v[1] % 4 == 0]:
        offs[k] = off; off += sz
    for k, (v, sz) in [(k, v) for k, v in lits.items() if v[1] % 4 != 0]:
        offs[k] = off; off += sz
    total = (off + 3) & ~3
    # pass 1: label addresses
    labels, pc = {}, 0
    for op in prog:
        if op[0] == "label":
            labels[op[1]] = pc
        else:
            pc += 2
    # pass 2: emit
    out, pc = bytearray(), 0
    for op in prog:
        kind = op[0]
        if kind == "label":
            continue
        if kind == "w":
            w = op[1]
        elif kind in ("bf", "bt"):
            d = (labels[op[1]] - pc - 4) // 2
            assert -128 <= d <= 127, f"branch disp {d}"
            w = (0x8B00 if kind == "bf" else 0x8900) | (d & 0xFF)
        elif kind == "bra":
            d = (labels[op[1]] - pc - 4) // 2
            assert -2048 <= d <= 2047
            w = 0xA000 | (d & 0xFFF)
        elif kind == "movl":
            ea = offs[op[2]]
            d = (ea - ((pc & ~3) + 4)) // 4
            assert 0 <= d <= 255, f"movl disp {d}"
            w = 0xD000 | (op[1] << 8) | d
        elif kind == "movw":
            ea = offs[op[2]]
            d = (ea - (pc + 4)) // 2
            assert 0 <= d <= 255, f"movw disp {d}"
            w = 0x9000 | (op[1] << 8) | d
        elif kind == "mova":                 # mova @(d,pc),r0 — address of a lit
            ea = offs[op[1]]
            assert ea % 4 == 0, f"mova target {op[1]} not 4-aligned"
            d = (ea - ((pc & ~3) + 4)) // 4
            assert 0 <= d <= 255, f"mova disp {d}"
            w = 0xC700 | d
        else:
            raise ValueError(kind)
        out += w.to_bytes(2, "big")
        pc += 2
    # Pad to FULL size before writing the pool: bytearray slice-assignment past
    # the current end silently APPENDS instead of writing at the offset, so
    # writing into a short buffer only worked while dict order == offset order
    # (all longs before all words). Violated by cave8's canary lits -> literal
    # pool scrambled -> runaway heal copy loop (session-15 crash).
    out += b"\x00" * (total - len(out))
    for k, (v, sz) in lits.items():
        raw = bytes(v) if isinstance(v, (bytes, bytearray)) else v.to_bytes(sz, "big")
        assert len(raw) == sz, f"lit {k}: {len(raw)}B != {sz}B"
        out[offs[k]:offs[k] + sz] = raw
    assert len(out) == total
    return bytes(out)


# (session 22: canary_offsets() and _build_heal() are gone — there is no blob to
#  heal any more. The tiles ship inside IMG.DAT; see the TILE_SEGMENTS comment.)


def _build_loader_wrapper(real_loader):
    """File-loader wrapper (session 14): called instead of the game's loader at
    the two font-upload call sites (their loader-address literals are repointed
    here). Calls the real loader, then unconditionally copies the cave payload
    from its VDP2-resident FONT.DAT home to CAVE_RAM, then rts. The final load
    in every boot/reload sequence is the font itself (file #8 -> 0x25E40000),
    so the last copy always runs with the payload present -> caves end correct.
    Clobbers r0-r2 (+T): both call sites reload r1/r2 right after the call and
    never read the loader's r0 (verified by disassembly)."""
    return _asm([
        ("w", 0x4F22),          # sts.l pr,@-r15
        ("w", 0x2F36),          # mov.l r3,@-r15
        ("movl", 3, "REAL"),
        ("w", 0x430B),          # jsr @r3
        ("w", 0x0009),          # nop
        ("movl", 1, "SRC"),     # payload caves @ VDP2 (uncached)
        ("movl", 2, "DST"),     # CAVE_RAM
        ("movw", 3, "CNT"),     # CAVES_SIZE/4 longwords
        ("label", "cp"),
        ("w", 0x6016),          # mov.l @r1+,r0
        ("w", 0x2202),          # mov.l r0,@r2
        ("w", 0x7204),          # add #4,r2
        ("w", 0x4310),          # dt r3
        ("bf", "cp"),
        ("w", 0x63F6),          # mov.l @r15+,r3
        ("w", 0x4F26),          # lds.l @r15+,pr
        ("w", 0x000B),          # rts
        ("w", 0x0009),          # nop
    ], {"REAL": (real_loader, 4), "SRC": (PAYLOAD_VDP2, 4), "DST": (CAVE_RAM, 4),
        "CNT": (CAVES_LIMIT // 4, 2)})


def _region_check(reg_cmp_word, spans, kr_label, orig_label):
    """Region membership check fragment: pointer in ANY [lo, hi) span -> falls
    through / branches to kr_label, else orig_label. spans = list of (lo, hi)
    RAM ranges (session 14: L1 packs overflow strings into the dead-zero chunks
    at 0x64c98+, so the check needs a second span there; L2 needs one).
    reg_cmp_word = cmp/hs encoding against r1 for the string-pointer register
    (0x3812 for r8, 0x3B12 for r11)."""
    prog, lits = [], {}
    for n, (lo, hi) in enumerate(spans):
        last = n == len(spans) - 1
        lits[f"LO{n}"] = (lo + 1, 4)
        lits[f"HI{n}"] = (hi + 1, 4)
        prog += [("movl", 1, f"LO{n}"),
                 ("w", reg_cmp_word),
                 ("bf", orig_label if last else f"nxt{n}"),
                 ("movl", 1, f"HI{n}"),
                 ("w", reg_cmp_word)]
        if last:
            prog += [("bt", orig_label)]           # p >= hi -> orig; else fall->kr
        else:
            prog += [("bf", kr_label), ("label", f"nxt{n}")]
    return prog, lits


def _build_txt_cave(ranges, site_ram):
    """Classifier cave for the bar/VS 8px printers (byte in r0, string ptr r8,
    tile passed to the printer's primitive in r4 via 'mov r0,r4' at the join).
    Joins (site-relative, identical in both printers): +0x3E korean/plain join,
    +0x3C arithmetic join (extu.b r1,r0), +0xC the ==0xb0 chain.
    Session 22: no heal call and no 8bpp scene guard — straight byte->k->PND.
    ★ 가드를 지운 것이 **전투 VS/마법 패널 병종명**을 살린 수정이다(그 화면들이
    바로 8bpp라 가드에 걸려 원본 경로로 빠지고 있었다) — _scene_guard 참조."""
    chk, chk_lits = _region_check(0x3812, ranges, "kr", "orig")
    return _asm(chk + [
        ("label", "kr"),
        ("w", 0xE1E0),          # mov #-32,r1
        ("w", 0x611C),          # extu.b r1,r1   (0xE0)
        ("w", 0x3012),          # cmp/hs r1,r0
        ("bf", "s2"),
        ("w", 0x7090),          # add #-112,r0
        ("w", 0x7090),          # add #-112,r0   k = b-224
        ("bra", "tile"),
        ("w", 0x0009),
        ("label", "s2"),
        ("w", 0xE130),          # mov #0x30,r1
        ("w", 0x3012),          # cmp/hs r1,r0
        ("bt", "s3"),
        ("w", 0x70FF),          # add #-1,r0     k = b-1 (0x21..0x2f)
        ("bra", "tile"),
        ("w", 0x0009),
        ("label", "s3"),
        ("w", 0x70F5),          # add #-11,r0    k = b-11 (0x3a..0x9f)
        ("label", "tile"),
    ] + _ktile_prog(0) + [
        ("movl", 1, "KRJ"),
        ("w", 0x412B),          # jmp @r1
        ("w", 0x0009),
        ("label", "orig"),
        ("w", 0xE1B0),          # mov #-80,r1
        ("w", 0x611C),          # extu.b r1,r1   (0xB0)
        ("w", 0x3016),          # cmp/hi r1,r0
        ("bf", "els"),
        ("w", 0x6103),          # mov r0,r1
        ("w", 0x7190),          # add #-112,r1
        ("movl", 2, "ARJ"),
        ("w", 0x422B),          # jmp @r2
        ("w", 0x0009),
        ("label", "els"),
        ("movl", 2, "ELJ"),
        ("w", 0x422B),          # jmp @r2
        ("w", 0x0009),
    ], {**chk_lits,
        "KRJ": (site_ram + 0x3E, 4), "ARJ": (site_ram + 0x3C, 4),
        "ELJ": (site_ram + 0x0C, 4),
        "SEG": (_seg_blob(), len(_seg_blob()))})


def _build_barprim_cave(back_ram):
    """Bar primitive front half: bit15 flag -> PNT = r4&0x7FFF with pal bits kept
    (r7=0 so the tail's r7<<12 contributes nothing); else original extu.b pair."""
    return _asm([
        ("w", 0x6143),          # mov r4,r1
        ("w", 0x4128),          # shll16 r1
        ("w", 0x4111),          # cmp/pz r1
        ("bf", "flag"),
        ("w", 0x644C),          # extu.b r4,r4
        ("w", 0x677C),          # extu.b r7,r7
        ("bra", "rep"),
        ("w", 0x0009),
        ("label", "flag"),
        ("w", 0x4100),          # shll r1        (r1 = r4<<16 still)
        ("w", 0x4129),          # shlr16 r1
        ("w", 0x4101),          # shlr r1        r1 = r4 & 0x7FFF
        ("w", 0x6413),          # mov r1,r4
        ("w", 0xE700),          # mov #0,r7
        ("label", "rep"),
        ("w", 0xE126),          # mov #38,r1
        ("w", 0x0617),          # mul.l r1,r6
        ("w", 0x001A),          # sts macl,r0
        ("w", 0x305C),          # add r5,r0
        ("movl", 1, "BACK"),
        ("w", 0x412B),          # jmp @r1
        ("w", 0x0009),
    ], {"BACK": (back_ram, 4)})


def _build_vsprim_cave(back_ram, rts_ram, shadow_ram):
    """VS primitive: address calc for both paths, then bit15 flag -> write
    PNT = r4&0xFFF (pal0, matches this screen's native 0x0700|tile text) and
    jump to rts; else original extu.b + back to the 0x0700-or tail."""
    return _asm([
        ("w", 0x4008),          # shll2 r0  (r0 = y, preloaded from r6)
        ("w", 0x4008),
        ("w", 0x4008),
        ("w", 0x305C),          # add r5,r0
        ("w", 0x300C),          # add r0,r0
        ("w", 0x6143),          # mov r4,r1
        ("w", 0x4128),          # shll16 r1
        ("w", 0x4111),          # cmp/pz r1
        ("bf", "flag"),
        ("w", 0x644C),          # extu.b r4,r4
        ("movl", 1, "BACK"),
        ("w", 0x412B),          # jmp @r1
        ("w", 0x0009),
        ("label", "flag"),
        ("w", 0x4108),          # shll2 r1       (r1 = r4<<16)
        ("w", 0x4108),          # shll2 r1       -> r4<<20
        ("w", 0x4129),          # shlr16 r1
        ("w", 0x4109),          # shlr2 r1
        ("w", 0x4109),          # shlr2 r1       r1 = r4 & 0xFFF
        ("w", 0x6413),          # mov r1,r4
        ("movl", 2, "SHDW"),
        ("w", 0x0245),          # mov.w r4,@(r0,r2)
        ("movl", 1, "RTS"),
        ("w", 0x412B),          # jmp @r1
        ("w", 0x0009),
    ], {"BACK": (back_ram, 4), "RTS": (rts_ram, 4), "SHDW": (shadow_ram, 4)})


def _patch12(site_ram, cave_ram):
    """12B in-place jump patch (via r1) for a site of either alignment."""
    if site_ram % 4 == 0:
        # lit at +8: ea = site+4+4
        return (_w(0xD101) + _w(0x412B) + _w(0x0009) + _w(0x0009)
                + cave_ram.to_bytes(4, "big"))
    else:
        # site%4==2 -> lit at +6: ea = (site&~3)+4+4 = site+6
        return (_w(0xD101) + _w(0x412B) + _w(0x0009)
                + cave_ram.to_bytes(4, "big") + _w(0x0009))


def _build_prim_cave(back_ram):
    """Primitive PNT-formula cave: bit15 flag -> PNT = r7 & 0x7FFF, else the
    original ((r7>>8)+1)<<12 | r7&0xFF.  r0/r3 are LIVE (write offset / shadow
    base) — only r1, r2 are touched, like the displaced code."""
    code = b"".join([
        _w(0x6273),  # 00 mov r7,r2
        _w(0x4228),  # 02 shll16 r2
        _w(0x4211),  # 04 cmp/pz r2              ; T=1 -> bit15 clear
        _w(0x8B09),  # 06 bf FLAG(i14)
        _w(0x6273),  # 08 mov r7,r2
        _w(0x4219),  # 0a shlr8 r2
        _w(0x7201),  # 0c add #1,r2
        _w(0x4218),  # 0e shll8 r2
        _w(0x4208),  # 10 shll2 r2
        _w(0x4208),  # 12 shll2 r2
        _w(0x617C),  # 14 extu.b r7,r1
        _w(0x221B),  # 16 or r1,r2
        _w(0xA005),  # 18 bra BACK(i19)
        _w(0x0009),  # 1a nop
        _w(0x6273),  # 1c FLAG: mov r7,r2
        _w(0x4228),  # 1e shll16 r2
        _w(0x4200),  # 20 shll r2
        _w(0x4229),  # 22 shlr16 r2
        _w(0x4201),  # 24 shlr r2               ; r2 = r7 & 0x7FFF
        _w(0xD102),  # 26 BACK: mov.l @(2,pc),r1 ; back addr (lit @48)
        _w(0x412B),  # 28 jmp @r1
        _w(0x0009),  # 2a nop
        _w(0x0009),  # 2c pad
        _w(0x0009),  # 2e pad (lit 4-align)
    ])
    assert len(code) == 48
    blob = code + back_ram.to_bytes(4, "big")
    assert len(blob) == 52
    return blob


# --- session-20: {01} half-width-space residue ----------------------------------
# The text engine allocates one NBG3 char slot per half-width space but never
# writes tile data into it, so whatever pixels that slot held from a previous
# screen bleed through the gap ("4장『사령의5숲』").  reinsert_text's 18B handler
# patch (_HW_NEW there) only advances the two cursors; this cave additionally
# blanks the slot it skips.
#
# Live RE (session 20, L1 uploader 0x0602ab74) gave the VRAM address formula:
#     charno_idx = [struct-8](line) * 64 + [struct+12](cell)
#     dst        = 0x25e30000 + charno_idx * 32      ; top cell
#     dst + 0x400                                    ; bottom cell (0x20 stride)
# Tiles must go through the game's own VRAM transfer queue (cfg["hw_queue"];
# r4=src r5=dst r6=longwords), which appends [type=1][dst][count][data] to a
# command buffer flushed later — an SH-2 store straight to VDP2 VRAM never
# reaches the screen (verified live).  The 32B source tile is appended to the
# cave itself so the engine's shared staging buffer is left untouched.
#
# reinsert_text calls build() twice per episode: once on the ORIGINAL bytes just
# to harvest the cave payload, once on the BIN it actually ships (18B body
# already applied). Both are accepted — the struct pointer is read from the
# literal pool, which is identical either way, so the cave bytes match.
_HW_ORIG = bytes.fromhex("d713d21363226133710122126130a01a2710")
_HW_PATCHED = bytes.fromhex("d214512371011213512571011215a01a0009")


def _hwspace_prog(struct_ram, ret_ram, queue_ram, buf_ram):
    prog = [
        ("movl", 1, "CLRB"),    # r0 = clear byte, replicated to a longword
        ("w", 0x6010),          # mov.b @r1,r0
        ("w", 0x600C),          # extu.b r0,r0
        ("w", 0x6103),          # mov r0,r1
        ("w", 0x4118),          # shll8 r1
        ("w", 0x201B),          # or r1,r0
        ("w", 0x6103),          # mov r0,r1
        ("w", 0x4128),          # shll16 r1
        ("w", 0x201B),          # or r1,r0
        ("movl", 1, "BUF"),     # fill our own 32B blank tile
        ("w", 0xE508),          # mov #8,r5
        ("label", "fill"),
        ("w", 0x2102),          # mov.l r0,@r1
        ("w", 0x7104),          # add #4,r1
        ("w", 0x4510),          # dt r5
        ("bf", "fill"),
        ("movl", 2, "LINE"),    # r7 = VRAM + (line*64 + cell)*32
        ("w", 0x6322),          # mov.l @r2,r3
        ("w", 0x4308),          # shll2 r3
        ("w", 0x4308),          # shll2 r3
        ("w", 0x4308),          # shll2 r3        -> line*64
        ("movl", 2, "CELL"),
        ("w", 0x6422),          # mov.l @r2,r4
        ("w", 0x334C),          # add r4,r3
        ("w", 0x4308),          # shll2 r3
        ("w", 0x333C),          # add r3,r3
        ("w", 0x4308),          # shll2 r3        -> *32
        ("movl", 2, "VRAM"),
        ("w", 0x332C),          # add r2,r3
        ("w", 0x6733),          # mov r3,r7
        ("movl", 1, "QUEUE"),   # queue(src=BUF, dst=top, 8 longwords)
        ("movl", 4, "BUF"),
        ("w", 0x6573),          # mov r7,r5
        ("w", 0x410B),          # jsr @r1
        ("w", 0xE608),          # mov #8,r6       (delay slot)
        ("movw", 0, "D400"),    # queue(src=BUF, dst=top+0x400, 8)
        ("w", 0x370C),          # add r0,r7
        ("movl", 1, "QUEUE"),
        ("movl", 4, "BUF"),
        ("w", 0x6573),          # mov r7,r5
        ("w", 0x410B),          # jsr @r1
        ("w", 0xE608),          # mov #8,r6       (delay slot)
        ("movl", 2, "STRUCT"),  # original body: cell cursor +1, clear width +1
        ("w", 0x5123),          # mov.l @(12,r2),r1
        ("w", 0x7101),          # add #1,r1
        ("w", 0x1213),          # mov.l r1,@(12,r2)
        ("w", 0x5125),          # mov.l @(20,r2),r1
        ("w", 0x7101),          # add #1,r1
        ("w", 0x1215),          # mov.l r1,@(20,r2)
        ("movl", 1, "RET"),     # rejoin the dispatcher epilogue, which restores
        ("w", 0x412B),          # jmp @r1          PR from the stack — so the jsr
        ("w", 0x0009),          # nop              clobber above is harmless
    ]
    lits = {"CLRB": (struct_ram + 0x13, 4), "LINE": (struct_ram - 8, 4),
            "CELL": (struct_ram + 12, 4), "VRAM": (0x25E30000, 4),
            "STRUCT": (struct_ram, 4), "RET": (ret_ram, 4),
            "QUEUE": (queue_ram, 4), "BUF": (buf_ram, 4), "D400": (0x0400, 2)}
    return prog, lits


def _build_hwspace_cave(struct_ram, ret_ram, queue_ram, cave_ram):
    """Cave replacing the {01} handler body. Code length is independent of the
    literal values, so a probe pass fixes where the appended 32B tile lands."""
    probe = _asm(*_hwspace_prog(struct_ram, ret_ram, queue_ram, 0))
    blob = _asm(*_hwspace_prog(struct_ram, ret_ram, queue_ram,
                               cave_ram + len(probe)))
    assert len(blob) == len(probe)
    return blob + b"\x00" * 32


def _hwspace_site_patch(site_ram, cave_ram):
    """10B jump at the handler entry (2-mod-4: literal lands at site+6)."""
    assert site_ram % 4 == 2, f"hw site 0x{site_ram:x} alignment"
    return _w(0xD101) + _w(0x412B) + _w(0x0009) + cave_ram.to_bytes(4, "big")


def _prim_site_patch(site_ram, cave_ram):
    """16B in-place patch of one PNT-formula site: jump to cave via r1 (r3 holds
    the live shadow base and must NOT be clobbered). Layout depends on the site
    address alignment (literal must be 4-aligned)."""
    if site_ram % 4 == 2:
        # lit at +0xA: mov.l @(2,pc),r1 (pc&~3 = site-2; ea = site-2+4+8 = site+10)
        return (_w(0xD102) + _w(0x412B) + _w(0x0009) + _w(0x0009) + _w(0x0009)
                + cave_ram.to_bytes(4, "big") + _w(0x0009))
    else:
        # lit at +0x8: mov.l @(1,pc),r1 (ea = site+4+4 = site+8)
        return (_w(0xD101) + _w(0x412B) + _w(0x0009) + _w(0x0009)
                + cave_ram.to_bytes(4, "big") + _w(0x0009) + _w(0x0009))


def build(binx, font_table, tag="L2"):
    """Rewrite the class-name tables of LANG{1,2}.BIN for Korean 16px+8px render.
    Returns (new_bin, syllables). `font_table` is a kr_encoding.build_table result
    that already includes the class-name syllables (caller merges them before
    baking FONT.DAT). 8px tiles are baked separately by img_re/gen_hud8.py."""
    cfg = CONFIGS[tag]
    b = bytearray(binx)
    ptrs = read_pointers(b, tag)
    krmap = _kr_map(bytes(binx), ptrs)

    # 1) syllable -> index byte + SJIS code (order shared with gen_hud8 blob)
    syllables = syllable_list(binx, tag)
    pool = _index_bytes()
    if len(syllables) > len(pool):
        raise ValueError(f"too many class syllables ({len(syllables)}) for index pool")
    if len(syllables) > TILE_CAPACITY:
        raise ValueError(f"too many class syllables ({len(syllables)}) for IMG tiles")
    syl_byte = {syl: pool[k] for k, syl in enumerate(syllables)}
    assert max(tile_map(bytes(binx), tag)) < TILE_CAPACITY, \
        f"{tag} tile map overflows the IMG.DAT tile segments ({TILE_CAPACITY})"
    # conv table: COPY of the original (katakana entries other UI references stay
    # intact), Korean indices overwritten.
    conv = bytearray(binx[cfg["conv_old"]:cfg["conv_old"] + 512])
    for syl, ib in syl_byte.items():
        idx = (ib + 0x60) & 0xFF
        conv[idx * 2:idx * 2 + 2] = kr_encoding.encode_text(syl, font_table)

    # 2) conv table copy -> conv_dst (string-region head; battle-safe, load-base
    #    stable). conv_old is left ORIGINAL — it doubles as live battle data.
    conv_dst = cfg["conv_dst"]
    conv_dst_ram = BASE + conv_dst
    assert conv_dst % 4 == 0
    b[conv_dst:conv_dst + 512] = conv
    conv_old_ram = BASE + cfg["conv_old"]
    for lit, want, put in ((cfg["lit_lead"], conv_old_ram, conv_dst_ram),
                           (cfg["lit_trail"], conv_old_ram + 1, conv_dst_ram + 1)):
        got = struct.unpack(">I", b[lit:lit + 4])[0]
        assert got == want, f"{tag} conv literal @0x{lit:x}: 0x{got:08x} != 0x{want:08x}"
        b[lit:lit + 4] = struct.pack(">I", put)
    # 16px converter entry must be ORIGINAL (single strings feed it directly).
    got = bytes(b[cfg["conv_entry"]:cfg["conv_entry"] + len(_ENTRY_ORIG)])
    assert got == _ENTRY_ORIG, f"{tag} conv entry @0x{cfg['conv_entry']:x}: {got.hex()}"

    # 3) SINGLE strings [korean idx bytes][NUL], suffix-merge packed into the
    #    battle-safe chunks; ptr_table repointed. Longest first so a short name
    #    can reuse the tail of a longer one (incl. its NUL).
    seen = {}              # original raw bytes -> korean enc
    for off_, ram in ptrs:
        i = ram - BASE
        j = i
        while binx[j] != 0:
            j += 1
        raw = bytes(binx[i:j])
        if raw in seen:
            continue
        jp = decode_name(bytes(binx), ram)
        seen[raw] = bytes(syl_byte[ch] for ch in krmap.get(jp, "") if ch in syl_byte)
    chunks = [list(c) for c in cfg["str_chunks"]]
    chunk_data = [bytearray() for _ in chunks]
    placed = {}            # enc -> RAM addr
    for enc in sorted(set(seen.values()), key=lambda e: (-len(e), e)):
        s = enc + b"\x00"
        addr = None
        for ci, cd in enumerate(chunk_data):
            k = bytes(cd).find(s)
            if k >= 0:
                addr = BASE + chunks[ci][0] + k
                break
        if addr is None:
            for ci, cd in enumerate(chunk_data):
                if chunks[ci][0] + len(cd) + len(s) <= chunks[ci][1]:
                    addr = BASE + chunks[ci][0] + len(cd)
                    cd.extend(s)
                    break
        if addr is None:
            raise ValueError(f"{tag} korean class strings overflow str_chunks")
        placed[enc] = addr
    for ci, cd in enumerate(chunk_data):
        lo, hi = chunks[ci]
        b[lo:lo + len(cd)] = cd
        for i in range(lo + len(cd), hi):
            b[i] = 0
    for off_, ram in ptrs:
        i = ram - BASE
        j = i
        while binx[j] != 0:
            j += 1
        b[off_:off_ + 4] = struct.pack(">I", placed[seen[bytes(binx[i:j])]])

    # 4) hard guard: the battle engine's RAM-fixed scratch windows must be
    #    byte-identical to the original file (both BINs share the load base).
    for lo, hi in _BATTLE_WINDOWS:
        assert bytes(b[lo:hi]) == bytes(binx[lo:hi]), \
            f"{tag} patch entered battle window 0x{lo:x}-0x{hi:x}"

    # === 8px HUD path (session-14 residency architecture) ===
    if os.environ.get("KR_HUD8", "1") == "0":
        return bytes(b), syllables, None

    # 3b) CHARACTER-name strings (HUD 8px only): rewrite each unique string IN
    #     PLACE with extension-pool index bytes (k = byte-11, tiles 149+). The
    #     pointers stay untouched; Korean is never longer than the katakana
    #     (dakuten bytes inflate the originals), asserted per name.
    char_strings, char_lo, char_hi = read_char_strings(bytes(binx), tag)
    char_kr = _char_kr_map(char_strings)
    tmap = tile_map(bytes(binx), tag)
    syl_k = {s: k for k, s in tmap.items()}
    pool_b = {k: pool[k] for k in range(len(pool))}               # k -> byte (<=148)

    def k_to_byte(k):
        return pool_b[k] if k < len(pool) else k + 11
    for ram, raw in char_strings:
        jp = unicodedata.normalize(
            "NFKC", bytes(x for x in raw if x >= 0xa0).decode("shift_jis", "replace"))
        kr = char_kr.get(jp, "")
        if not kr:
            continue
        enc = bytes(k_to_byte(syl_k[ch]) for ch in kr
                    if ch == " " or kr_encoding.is_hangul(ch))
        assert len(enc) <= len(raw), f"{tag} char name too long: {jp!r} -> {kr!r}"
        i = ram - BASE
        b[i:i + len(raw)] = enc + b"\x00" * (len(raw) - len(enc))

    # 5) cave payload: assembled into a 1024B buffer resident at CAVE_RAM
    #    (copied there by the loader wrapper after every font upload). The BIN
    #    only carries 12B jump patches at the printer sites + the wrapper.
    join_ram = BASE + cfg["cls"] + 0x26
    resume_ram = BASE + cfg["cls"] + 0x0C
    assert cfg["ptr_table"] < char_lo, f"{tag} span order broken"
    # span 1 = [class strings][ptr table][char strings] (contiguous);
    # span 2 (L1) = the dead-zero overflow chunks past the ptr table.
    spans = [(BASE + cfg["str_table"], BASE + char_hi)]
    out_chunks = [c for c in cfg["str_chunks"] if c[0] >= cfg["ptr_table"]]
    if out_chunks:
        spans.append((BASE + min(lo for lo, _ in out_chunks),
                      BASE + max(hi for _, hi in out_chunks)))

    caves = bytearray()

    def alloc_cave(blob):
        off = len(caves)
        caves.extend(blob)
        assert len(caves) <= CAVES_LIMIT, f"{tag} caves overflow ({len(caves)}B)"
        return CAVE_RAM + off

    cave8_ram = alloc_cave(_build_cave8(spans, join_ram, resume_ram))
    for site in (cfg["prim_a"], cfg["prim_b"]):
        got = bytes(b[site:site + 16])
        assert got == _PRIM_ORIG, f"{tag} prim site @0x{site:x}: {got.hex()}"
        cave_ram = alloc_cave(_build_prim_cave(BASE + site + 16))
        b[site:site + 16] = _prim_site_patch(BASE + site, cave_ram)
    barprim_ram = alloc_cave(_build_barprim_cave(BASE + cfg["bar_prim"] + 12))
    vsprim_ram = alloc_cave(_build_vsprim_cave(BASE + cfg["vs_prim"] + 12,
                                               BASE + cfg["vs_prim"] + 0x14,
                                               cfg["vs_shadow"]))
    bartxt_ram = alloc_cave(_build_txt_cave(spans, BASE + cfg["bar_cls"]))
    vstxt_ram = alloc_cave(_build_txt_cave(spans, BASE + cfg["vs_cls"]))

    # session-20: {01} half-width space -> also blank the char slot it skips.
    # reinsert_text has already written the 18B cursor-bump body here; we take
    # over its first 10B. Cave literals are all derived from the struct pointer
    # that body loads (line at -8, cell at +12, clear byte at +0x13).
    hw_site = cfg["hw_site"]
    got = bytes(b[hw_site:hw_site + len(_HW_PATCHED)])
    assert got in (_HW_ORIG, _HW_PATCHED), \
        f"{tag} hw-space site @0x{hw_site:x}: {got.hex()}"
    hw_struct = struct.unpack(">I", b[((hw_site & ~3) + 4) + 0x14 * 4:][:4])[0]
    hw_ret = BASE + hw_site + 0x46
    hw_ram = CAVE_RAM + len(caves)          # buffer address must be known upfront
    assert hw_ram % 4 == 0, f"{tag} hw cave 0x{hw_ram:x} must be 4-aligned (literal pool)"
    alloc_cave(_build_hwspace_cave(hw_struct, hw_ret, cfg["hw_queue"], hw_ram))
    b[hw_site:hw_site + 10] = _hwspace_site_patch(BASE + hw_site, hw_ram)

    for site, orig, chk, cave_ram in (
            (cfg["bar_cls"], _TXT_CLS_SIG, "sig", bartxt_ram),
            (cfg["vs_cls"], _TXT_CLS_SIG, "sig", vstxt_ram),
            (cfg["bar_prim"], _BARPRIM_ORIG, "full", barprim_ram),
            (cfg["vs_prim"], _VSPRIM_ORIG, "full", vsprim_ram)):
        if chk == "sig":   # site+0 is a pc-relative mov.w whose disp differs per BIN
            assert b[site] == 0x91 and bytes(b[site + 2:site + 12]) == orig,                 f"{tag} txt cls site @0x{site:x}: {bytes(b[site:site+12]).hex()}"
        else:
            assert bytes(b[site:site + 12]) == orig,                 f"{tag} prim site @0x{site:x}: {bytes(b[site:site+12]).hex()}"
        b[site:site + 12] = _patch12(BASE + site, cave_ram)

    # 5c) 8px hiragana panel labels しきはんい(지휘범위)/しゅうせい(수정): tile-word
    # arrays in the BIN; res#0 tiles 48..55 are re-baked by gen_hud8.py.
    _SHU_OLD = bytes.fromhex("00300035003600370034")
    _SHU_NEW = bytes.fromhex("00350036003400340034")
    for off in cfg["shuusei"]:
        got = bytes(b[off:off + 10])
        assert got == _SHU_OLD, f"{tag} shuusei array @0x{off:x}: {got.hex()}"
        b[off:off + 10] = _SHU_NEW

    # 6) main classifier entry patch -> cave8 (12B)
    cls = cfg["cls"]
    got = bytes(b[cls:cls + 12])
    assert got == _CLS_ORIG, f"{tag} classifier @0x{cls:x}: {got.hex()}"
    assert (BASE + cls) % 4 == 0
    b[cls:cls + 12] = (b"\xd1\x01"            # mov.l @(1,pc),r1  (lit at cls+8)
                       b"\x41\x2b"            # jmp @r1
                       b"\x00\x09\x00\x09" +  # nop (delay) + pad
                       struct.pack(">I", cave8_ram))

    # 7) loader wrapper + literal repoints. Both font-upload call sites fetch
    #    the loader address from pc-relative literal cells; repointing those
    #    cells to the wrapper is transparent to any other user of the cells
    #    (the wrapper is call-compatible: jsr real loader -> copy caves -> rts).
    def _movl_ea(addr):
        wv = struct.unpack(">H", b[addr:addr + 2])[0]
        return (addr & ~3) + 4 + (wv & 0xFF) * 4

    s1 = cfg["boot1"]           # [mov.l ->r5][r7=0][r6=0][jsr @r8][r4=8]
    assert bytes(b[s1 + 2:s1 + 10]) == bytes.fromhex("e700e600480be408"),         f"{tag} boot1 shape @0x{s1:x}: {bytes(b[s1:s1+12]).hex()}"
    r8_load = None
    for a in range(s1 - 2, s1 - 0x60, -2):
        if b[a] == 0xD8:        # mov.l @(d,pc),r8
            r8_load = a
            break
    assert r8_load is not None, f"{tag} boot1 r8 literal load not found"
    ea1 = _movl_ea(r8_load)
    s2 = cfg["boot2"]           # [mov.l ->r5][jsr @r0][r4=8][...]
    assert bytes(b[s2 + 2:s2 + 6]) == bytes.fromhex("400be408"),         f"{tag} boot2 shape @0x{s2:x}: {bytes(b[s2:s2+12]).hex()}"
    assert b[s2 - 4] == 0xD0, f"{tag} boot2 r0 load @0x{s2-4:x}: {b[s2-4]:02x}"
    ea2 = _movl_ea(s2 - 4)
    loader1 = struct.unpack(">I", b[ea1:ea1 + 4])[0]
    loader2 = struct.unpack(">I", b[ea2:ea2 + 4])[0]
    assert loader1 == loader2 and (loader1 >> 20) == 0x060,         f"{tag} loader literals: 0x{loader1:08x} vs 0x{loader2:08x}"
    wrapper = _build_loader_wrapper(loader1)
    ilo, ihi = cfg["init_region"]
    assert not any(binx[ilo:ihi]), f"{tag} init region not zero in original"
    assert len(wrapper) <= ihi - ilo, f"{tag} wrapper {len(wrapper)}B > init region"
    b[ilo:ilo + len(wrapper)] = wrapper
    for ea in (ea1, ea2):
        b[ea:ea + 4] = struct.pack(">I", BASE + ilo)

    caves.extend(b"\x00" * (CAVES_SIZE - len(caves)))
    return bytes(b), syllables, bytes(caves)


def byte_to_tile(ib):
    """Python mirror of cave8's byte->k arithmetic (for selftests/tools)."""
    if ib >= 0xe0:
        k = ib - 0xe0
    elif 0x21 <= ib <= 0x2f:
        k = ib - 1          # 32..46
    else:
        k = ib - 11         # 0x3a..0x9f -> 47..148
    return k


def pnt_refs():
    """charnos the game itself draws (img_re/data/pnt_refs.json — see the
    TILE_SEGMENTS comment). Used to keep glyphs off the game's blank tiles."""
    p = os.path.join(HERE, "img_re", "data", "pnt_refs.json")
    return set(json.load(open(p, encoding="utf-8"))["charnos"])


def assert_slots_unreferenced():
    """No slot may be a charno the game references — that is how session 22's
    first build painted 토 all over the map HUD (res#1 tile 128 = charno 0x380)."""
    refs = pnt_refs()
    bad = [(r, t) for r, t in tile_slots() if (RES_CHARNO[r] + t) in refs]
    assert not bad, ("tile slots collide with charnos the game draws: "
                     + ", ".join(f"res#{r} tile {t} (charno 0x{RES_CHARNO[r]+t:03x})"
                                 for r, t in bad))


def _seg_selftest():
    """Run the caves' segment-lookup loop in Python over the whole ordinal range
    and check it against tile_slots()/k_to_pnd — the two must never drift, and a
    silent drift would put every 8px glyph one tile off."""
    rows = _seg_table()
    slots = tile_slots()
    assert len(slots) == TILE_CAPACITY
    assert len({s for s in slots}) == TILE_CAPACITY, "duplicate tile slot"
    assert_slots_unreferenced()
    for k in range(TILE_CAPACITY):
        for bound, delta in rows:                  # first row with k < bound wins
            if k < bound:
                break
        got = (k + delta) & 0xFFFF
        want = k_to_pnd(k)
        assert got == want, f"k={k}: cave 0x{got:04x} != python 0x{want:04x}"
        res, tile = slots[k]
        assert got == (TILE_FLAG_BASE | (RES_CHARNO[res] + tile))
        assert (got & 0x0FFF) < 0x1000 and got & 0x8000
    print(f"  segment lookup: {TILE_CAPACITY} slots OK "
          f"({', '.join(f'res#{r}:{f}-{f+n-1}' for r, f, n in TILE_SEGMENTS)})")


def _selftest():
    import kr_font
    _seg_selftest()
    for tag, binf, fontf in (("L1", "LANG1.BIN", "LANG1_FONT.DAT"),
                             ("L2", "LANG2.BIN", "LANG1_FONT.DAT")):
        binx = open(os.path.join(HERE, "..", "original", binf), "rb").read()
        ptrs = read_pointers(binx, tag)
        krmap = _kr_map(binx, ptrs)
        syl_order = syllable_list(binx, tag)
        fd = kr_font.FontDat.load(os.path.join(HERE, "..", "original", fontf))
        table = kr_encoding.build_table(sorted(set(syl_order)), fontdat=fd)
        new, used, _pay = build(binx, table, tag)
        assert used == syl_order
        cfg = CONFIGS[tag]
        conv = new[cfg["conv_dst"]:cfg["conv_dst"] + 512]
        # conv_old must be untouched (live battle data) and battle windows intact
        assert new[cfg["conv_old"]:cfg["conv_old"] + 512] == \
            binx[cfg["conv_old"]:cfg["conv_old"] + 512], f"{tag} conv_old touched"
        code2syl = {bytes(kr_encoding.encode_text(s, table)): s for s in syl_order}
        pool = _index_bytes()
        ok = bad = 0
        for off, ram in ptrs:
            jp = decode_name(binx, ram)
            want_kr = krmap.get(jp, "")
            i = struct.unpack(">I", new[off:off + 4])[0] - BASE
            assert any(lo <= i < hi for lo, hi in cfg["str_chunks"]), \
                f"{tag} ptr 0x{i:x} outside str_chunks"
            j = i
            while new[j] != 0:
                j += 1
            got_16 = got_8 = ""
            for x in new[i:j]:
                # 16px: conv table lookup
                sj = bytes(conv[((x + 0x60) & 0xFF) * 2:((x + 0x60) & 0xFF) * 2 + 2])
                got_16 += code2syl.get(sj, "?")
                # 8px: cave arithmetic -> ordinal k -> IMG.DAT tile slot k
                k = byte_to_tile(x)
                assert pool[k] == x, f"{tag} pool/cave mismatch byte 0x{x:02x}"
                assert 0 <= k < TILE_CAPACITY
                got_8 += syl_order[k] if k < len(syl_order) else "?"
            if got_16 == want_kr and got_8 == want_kr:
                ok += 1
            else:
                bad += 1
                if bad <= 5:
                    print(f"  MISMATCH {tag} jp={jp!r} kr={want_kr!r} "
                          f"16px={got_16!r} 8px={got_8!r}")
        # KR_HUD8=0: char strings untouched, no payload
        if os.environ.get("KR_HUD8", "1") == "0":
            assert _pay is None
            strings, char_lo, char_hi = read_char_strings(binx, tag)
            for ram, raw in strings:
                i = ram - BASE
                assert new[i:i + len(raw)] == binx[i:i + len(raw)], \
                    f"{tag} char string touched @0x{i:x}"
        else:
            # HUD8 payload sanity: caves fixed size; wrapper installed; loader
            # literals repointed to the wrapper's RAM address
            assert _pay is not None and len(_pay) == CAVES_SIZE
            ilo, ihi = cfg["init_region"]
            assert any(new[ilo:ihi]), f"{tag} wrapper missing"
            # char roundtrip via tile_map (session-12d logic)
            tmap = tile_map(binx, tag)
            strings, char_lo, char_hi = read_char_strings(binx, tag)
            char_kr = _char_kr_map(strings)
            cok = cbad = 0
            for ram, raw in strings:
                jp = unicodedata.normalize(
                    "NFKC",
                    bytes(x for x in raw if x >= 0xa0).decode("shift_jis", "replace"))
                want = char_kr.get(jp, "")
                if not want:
                    continue
                i = ram - BASE
                j = i
                while new[j] != 0:
                    j += 1
                got = "".join(tile_map(binx, tag).get(byte_to_tile(x), "?")
                              for x in new[i:j])
                if got == want:
                    cok += 1
                else:
                    cbad += 1
                    if cbad <= 5:
                        print(f"  CHAR MISMATCH {tag} {jp!r} want={want!r} got={got!r}")
            print(f"  {tag} HUD8: caves {len(_pay)}B, char {cok}/{cok+cbad}")
            assert cbad == 0
        # str_chunks fill report
        used_b = 0
        for lo, hi in cfg["str_chunks"]:
            seg = new[lo:hi]
            end = len(seg)
            while end and seg[end - 1] == 0:
                end -= 1
            used_b += end
        cap = sum(hi - lo for lo, hi in cfg["str_chunks"])
        print(f"gen_classnames selftest {tag}: class {ok}/{ok+bad}, "
              f"conv@0x{cfg['conv_dst']:x}, strings {used_b}/{cap}B in "
              f"{len(cfg['str_chunks'])} chunks")
        assert bad == 0


if __name__ == "__main__":
    _selftest()
