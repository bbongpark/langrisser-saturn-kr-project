#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reinsert_text.py — batch reinsertion: filled dedup worksheet -> patched disc.

Reads translation_worksheet_dedup.json (each unique string carries `kr` +
the `ids` of every occurrence), renders each `kr` (kr_markup) to SCEN bytes,
replaces every occurrence, then per file rebuilds FONT + SCEN (variable length,
padding reclaimed to stay within the sector allocation) and writes them + the
LANG.BIN {01} patch into a disc image with EDC/ECC.

Font slots: ONE global table (empty-slot-first) covers every Hangul syllable in
the whole translation; each syllable's glyph is baked into BOTH fonts at the same
code, so a shared SCEN code renders in either episode.

Per-file spacing:
  L1: half-width {01} (verified SH-2 patch @ LANG1.BIN 0x1b204).
  L2: fullwidth 0x8140 (no BIN patch; L2's renderer uses a different RAM layout,
      its {01} patch is not yet reverse-engineered — future work).

Usage:
  python reinsert_text.py [worksheet.json]   # default: build/translation_worksheet_dedup.json
Only entries with a non-empty `kr` are applied; unfilled ones keep the original JP.
"""
import sys, io, os, json
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "img_re"))   # patch_katakana_redirect (BIN tables)
import re
import scen_tool, kr_font, kr_encoding, kr_markup, kr_render, kr_names

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "original")
BUILD = os.path.join(ROOT, "build")
DISCDIR = os.environ.get("LANGRISSER_DISC",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Langrisser - Dramatic Edition (Japan) (1M)"))
TRACK1 = os.path.join(DISCDIR, "Langrisser - Dramatic Edition (Japan) (1M) (Track 1).bin")
# Neo둥근모 (Neodgm) — OFL/public-domain 16px Korean PIXEL font, crisp on the 16x16
# cell (malgun was an anti-aliased prototype, thin at this size). Fixed-baseline
# raster (kr_font.rasterize_ttf) keeps glyph heights consistent; y_offset=0 lands ink
# on rows 1..13 with no top/bottom clipping (measured over all 1132 syllables).
TTF = os.path.join(ROOT, "fonts", "neodgm.ttf")
FONT_YOFF = 0

# {01}->half-width SH-2 patch (per the tech-doc §5.1: 18 bytes at the handler ENTRY
# 0x1b1fe, advancing BOTH cursor variables by +1 tile = +8px). The renderer is an
# 8x8-cell VDP2 NBG3; a normal glyph advances TWO cursors +2 tiles each:
#   [0x0609ab44] = @(3,r2)  horizontal cell column that POSITIONS the next glyph, and
#   [0x0609ab4c] = @(5,r2)  a PARALLEL width counter the per-box window CLEAR reads to
#                           know how many cells to blank before drawing the next box.
# A half-width space must advance BOTH by +1 tile. Advancing only ab44 (an earlier
# 10-byte patch) positioned glyphs correctly but left ab4c short, so the clear blanked
# too few cells and the previous box's glyphs bled through the {01} gaps (residue).
# The handler is byte-identical in both episodes and the r2 literal sits at the same
# entry-relative offset, so the SAME 18 bytes apply to both — L1 @0x1b1fe, L2 @0x1cee6.
#   d2 14  mov.l @(0x14,pc),r2 ; r2 = cursor struct base (0x0609ab38 L1 / 0x060a00a8 L2)
#   51 23  mov.l @(3,r2),r1    ; r1 = [ab44]
#   71 01  add   #1,r1         ; +1 tile (8px)
#   12 13  mov.l r1,@(3,r2)    ; [ab44] += 1
#   51 25  mov.l @(5,r2),r1    ; r1 = [ab4c]
#   71 01  add   #1,r1
#   12 15  mov.l r1,@(5,r2)    ; [ab4c] += 1
#   a0 1a  bra   entry+0x46    ; rejoin dispatcher (L1 0x0602b244)
#   00 09  nop                 ; delay slot
_HW_ORIG = bytes.fromhex("d713d21363226133710122126130a01a2710")
_HW_NEW = bytes.fromhex("d214512371011213512571011215a01a0009")
L1_BIN_PATCH = (0x1b1fe, _HW_ORIG, _HW_NEW)
L2_BIN_PATCH = (0x1cee6, _HW_ORIG, _HW_NEW)

FILES = {
    "L1": dict(scen="LANG1_SCEN.DAT", scen_lba=136946, alloc=659456,
               font="LANG1_FONT.DAT", font_lba=135070,
               binf="LANG1.BIN", bin_lba=202, bin_patch=L1_BIN_PATCH,
               space=kr_markup.HW_SPACE),
    "L2": dict(scen="LANG2_SCEN.DAT", scen_lba=157751, alloc=4517888,
               font="LANG2_FONT.DAT", font_lba=144527,
               binf="LANG2.BIN", bin_lba=404, bin_patch=L2_BIN_PATCH,
               space=kr_markup.HW_SPACE),
}
# 세션18 실기 확정 시나리오 대화 박스 모델:
#   1페이지 = 이름줄 + MAX_LINES(3)줄, 2페이지+ = 이름 없어 DLG_PAGE2_LINES(4)줄, 흡수줄 없음.
#   (일자크 박스=이름+3줄, #0 제시카 2페이지=4줄 다 표시 확인. 여신 박스는 absorb_box 플래그로 예외.)
MAX_LINES = int(os.environ.get("KR_DLG_LINES", "3"))         # 대화 1페이지(이름줄 아래) 줄 수
DLG_PAGE2_LINES = int(os.environ.get("KR_DLG_PAGE2", "4"))   # 대화 2페이지+(이름 없음) 줄 수
# KR_NO_ABSORB=1: 전 대화 흡수줄 제거(디버그용). 시나리오 대화는 기본으로 흡수줄 없음(absorb_box 플래그만 유지).
NO_ABSORB = os.environ.get("KR_NO_ABSORB", "0") == "1"
WIDTH = 14        # dialogue window is 14 fullwidth cells (28 half-cells = 224px) wide
# Full-screen NARRATION renderer (scenario intro, leaf (block,2,7)): measured from the
# original JP at 7 lines x 16 fullwidth cells per page, and — unlike the dialogue box —
# its {06}{07} page clear does NOT eat the first line (pages start directly with
# content). Feeding narration through the 3x14 dialogue geometry shredded each page into
# 1-2 line fragments (user report: "한 줄씩 조금씩 나온다"); this restores the top-to-
# bottom fill.
NARR_LINES = 7
NARR_WIDTH = 16
NARR_LEAF = (2, 7)
COND_LEAF = (2, 6)     # victory/defeat conditions + tutorial pages
END_LEAF = (2, 9)      # ending epilogues
# 세션23 실측 — (2,6)/(2,9)도 나레이션과 **같은 전체화면 텍스트 격자**를 쓴다.
#   · 화면 실측(build/s16_conditions_fixed.png ↔ build/narr_user_check.png): 조건 화면과
#     나레이션의 글자 격자가 완전히 일치한다 — 셀 원점 x≈45px·첫 줄 y=48px·줄 간격 24px.
#     (나레이션 7줄이 y=48,72,…,192에 놓이고 조건 5줄이 y=49,73,121,145,169로 같은 눈금에 앉는다.)
#   · 원본 JP 조판 역산(scratchpad/leafgeom.py: {08}=개행, {06}{07}=페이지 지우기 기준):
#     (2,5) 대사는 14칸에서, (2,7) 나레이션은 16칸에서 정확히 끊긴다(= 알려진 값 재현 → 방법 검증).
#     같은 자로 재면 (2,9) 엔딩은 **16칸에서 딱 끊기고**(16칸 20회, 초과 0회), (2,6)은 최장 15칸이다.
#   · 페이지당 줄 수는 원본이 실제로 그리던 최대치를 쓴다 — (2,7) 7줄 / (2,6)·(2,9) 4줄.
#     격자는 7줄까지 있지만 이 두 리프의 원본은 4줄을 넘긴 적이 없어, 4줄이 실증된 안전한 상한이다.
#   · absorb 없음: 원본에서 {06}{07} 바로 뒤에 본문이 붙는다(`…負ってしまう。{06}{07}そしてそのまま…`)
#     — 나레이션과 같이 페이지 지우기가 첫 줄을 먹지 않는다.
#   (2,6)의 최장 15칸은 일본어 어절 단위 접힘의 여유로 보고 격자 실측값 16을 쓴다. 조건 조각은
#   전부 13.5칸 이하 한 줄이라 영향이 없고, 폭 변화가 실제로 닿는 것은 튜토리얼 본문뿐이다.
FULLSCREEN_GEOM = {
    NARR_LEAF: (NARR_WIDTH, NARR_LINES),
    COND_LEAF: (16, 4),
    END_LEAF: (16, 4),
}
# 산문이라 한국어 줄채움 재배치를 해도 되는 전체화면 리프. (2,6)은 제외한다 — 조건 목록은
# "한 조건 = 여러 세그먼트"라 저작 줄바꿈이 구조이고, 튜토리얼도 저작 줄바꿈을 유지한다
# (폭이 16으로 넓어지면 자동 워드랩만으로 자연스럽게 채워진다).
FULLSCREEN_REFLOW = {NARR_LEAF, END_LEAF}
# ⛔⛔ 여신(루시리스) 블록 — **전면 동결**(세션21 사용자 확정 규칙 ⑤, 세션23 재확인).
# 조판 파라미터를 바꾸는 것도 "건드리는 것"이다. 이 블록의 항목은 리프가 무엇이든
# **세션23 이전 경로 그대로**(대사 박스 14칸x3줄 · 흡수줄 있음 · reflow 없음 ·
# 이름 폭은 추정 4칸) 조판한다.
#   왜: 세션23에 (2,6)을 전체화면 격자로 바꿨더니 **이 블록의 튜토리얼까지 재조판**됐다.
#   그런데 실기(mednafen, 세션23)에서 확인하니 루시리스의 튜토리얼은 전체화면 격자가 아니라
#   **여신 대화창 안에** 그려진다 — 같은 (2,6) 리프라도 조건 화면과 렌더러가 다르다.
#   즉 이 블록에 16칸 조판을 넣으면 박스 밖으로 넘친다. (조건 조각 572개는 무관 — 전부 한 줄.)
GODDESS_BLOCKS = {("L1", 20), ("L2", 98)}
# L2:100의 (2,6)은 여신이 아니라 **유닛 상성표**(`보병ＶＳ창병…`)다. 루시리스 동결과는 별건이지만,
# (2,6) 안에 렌더러가 둘 이상이라는 게 드러난 이상 이 화면의 창도 **미검증**이다 —
# 16칸 조판이 3줄째를 만들어내므로(실측 6항목) 실기 확인 전까지 옛 조판으로 보류한다.
UNVERIFIED_GEOM_BLOCKS = {("L2", 100)}
# 새 전체화면 지오메트리를 적용하지 않을 블록(= 세션23 이전 경로 그대로)
LEGACY_GEOM_BLOCKS = GODDESS_BLOCKS | UNVERIFIED_GEOM_BLOCKS
DLG_LEAF = (2, 5)      # main dialogue leaf — eligible for Korean line re-flow
UI_LEAF = (2, 0)       # menu/UI message leaf — use full-width space (box not blank-filled)
# ── {02}([WAIT])의 폭 ─────────────────────────────────────────────────────────
# {02}는 "스크립트가 밀어 넣은 런타임 인자"라 자리마다 정체가 다르다. 세션24 전수 조사
# (612엔트리·684회):
#   · 대사(2,5) 480 · 나레이션(2,7)+엔딩(2,·) 131 · 조건(2,6) 2  → **전부 주인공 이름**
#     (조건의 `・{02}の死亡`은 84블록이 공유하는 주인공 사망 조건. 동료 사망은 `{09:01}`
#      (리아나)·`{09:13}`(제시카)처럼 이름 토큰이나 생짜 텍스트를 쓴다.)
#   · UI(2,0) 27  → 아이템/병종/캐릭터명(`{02}を手に入れた`·`を購入しました`·`の装備`…).
#     아이템 문맥 6종은 **전부 UI 리프에만** 있다 = 대사/나레이션/조건에는 0건.
# 주인공 이름은 개명 불가(사용자 확인)이고 이름표에도 실측값이 있다 — 엘윈/레딘 = 2칸.
# 그래서 UI 리프만 종전 추정값(4칸)을 유지하고 나머지는 실제 폭을 쓴다.
# ⚠ 만약 개명이 가능하다면(캐릭터 메이킹에서 이름 입력) 2칸 조판이 넘칠 수 있다 —
#    그때는 PLAYER_NAME_CELLS를 다시 4로 올려라(이 상수 하나만 바꾸면 된다).
PLAYER_NAME_CELLS = 2
TITLE_LEAF = (2, 8)    # scenario-title table read by the save/load slot via the {02}
# dynamic-insert path. SESSION 17: root-caused + FIXED (cold-boot verified — slot renders
# "1장『서장』이어서" in clean Korean). The slot template is `{ctrl}면{010e}『{02}{010e}』`;
# the **{010e} control code switched the renderer into a broken title-glyph mode** that
# mangled the inserted title (both Japanese AND Korean — the earlier "keep JP" assumption
# was wrong and was never actually verified, since no save persisted then). gen_menutext
# now strips the two {010e} from all four slot templates → {02} renders via the normal
# FONT.DAT path, so kanji-slot Korean titles render fine. DEFAULT ON now.
# Set KR_SCEN_TITLES=0 to revert to Japanese titles if ever needed.
KEEP_JP_TITLES = os.environ.get("KR_SCEN_TITLES", "1") == "0"


def node_at(tree, path):
    n = tree
    for i in path:
        n = n.children[i]
    return n


def parse_id(id_str):
    tag, rest = id_str.split(":")
    path_s, seg_s = rest.split("#")
    path = tuple(int(x) for x in path_s.split("/"))
    return tag, path, int(seg_s)


def block_size(tree, block_idx):
    """Serialized byte size of a top-level block subtree."""
    return len(scen_tool.serialize(tree.children[block_idx], bytearray()))


def largest_zero_leaf(node):
    """Largest all-zero leaf within a subtree (that block's padding to reclaim)."""
    best = [None]
    for _, leaf in scen_tool.iter_leaves(node):
        if leaf.raw and all(b == 0 for b in leaf.raw):
            if best[0] is None or len(leaf.raw) > len(best[0].raw):
                best[0] = leaf
    return best[0]


def reclaim_block(tree, block_idx, need):
    """ALIGNMENT-PRESERVING reclaim: trim `need` zero bytes from THIS block's own
    padding leaf, keeping the block's total size constant so every later block
    stays at its original offset. The game relies on top-level block positions
    (trimming file-tail padding shifts later blocks and crashes the load). Returns
    bytes reclaimed."""
    leaf = largest_zero_leaf(tree.children[block_idx])
    if leaf is None:
        return 0
    take = min(need, len(leaf.raw))
    leaf.raw = leaf.raw[:len(leaf.raw) - take]
    return take


def build(worksheet):
    entries = [e for e in worksheet if e.get("kr", "").strip()]
    print(f"filled entries: {len(entries)} / {len(worksheet)}")
    if not entries:
        print("nothing to reinsert (fill `kr` fields first).")
        return

    # 세션23: `[NAME:xx]`를 추정 4칸이 아니라 **실제 이름 폭**으로 재서 조판한다
    # (kr_names 모듈 주석 참조 — 실측 1~6칸, 추정 4칸은 양쪽으로 다 틀린다).
    # 이름표는 블록이 달라도 같으므로 게임(L1/L2)당 표 하나면 된다.
    name_w_all = kr_names.width_map(worksheet)
    _bad = kr_names.check_uniform(worksheet)
    if _bad:      # 전제가 깨졌다 — 항목별 최댓값을 써야 하니 조용히 넘어가지 않는다
        raise SystemExit(f"이름표가 블록마다 다르다({len(_bad)}건) — kr_names 주석 참조: "
                         f"{list(_bad)[:5]}")
    print("name widths: " + " · ".join(
        f"{t} {len(m)}개" for t, m in sorted(name_w_all.items())))

    # 1) global font table from all Hangul syllables across all filled kr, PLUS the
    #    Korean class-name syllables (rendered via the LANG2.BIN class-name path, not
    #    SCEN) so their glyphs share the same font slots and get baked in step 3.
    syllables = []
    for e in entries:
        for ch in e["kr"]:
            if kr_encoding.is_hangul(ch):
                syllables.append(ch)
    import gen_classnames, gen_menutext
    for _tag in FILES:
        _bin = open(os.path.join(ORIG, FILES[_tag]["binf"]), "rb").read()
        for jp, kr in gen_classnames._kr_map(
                _bin, gen_classnames.read_pointers(_bin, _tag)).items():
            for ch in kr:
                if kr_encoding.is_hangul(ch):
                    syllables.append(ch)
    syllables.extend(gen_menutext.MENU_SYLLABLES)   # load/save-screen BIN text
    fd1 = kr_font.FontDat.load(os.path.join(ORIG, "LANG1_FONT.DAT"))
    # session-14: the FONT.DAT tail hosts the 8px cave+blob payload (VDP2-resident,
    # scene-stable — see gen_classnames module docstring). Keep the Korean bake
    # out of those cells (block 5 tail, PAYLOAD_OFF..EOF).
    _b5 = fd1.blocks[5]
    _payload_cells = {(5, i) for i in range(
        (gen_classnames.PAYLOAD_OFF - _b5[0]) // kr_font.GLYPH_BYTES, _b5[2])}
    table = kr_encoding.build_table(syllables, fontdat=fd1,
                                    reserved_slots=_payload_cells)
    print(f"unique syllables: {table['used']} (empty {table['empty_supply']}, supply {table['supply']})")

    # 2) parse+encode each entry per its target file's spacing; group edits.
    #    A malformed individual entry (oversize page, un-encodable char) is SKIPPED
    #    (left original/Japanese) and collected — one bad line must not block the batch.
    edits = {tag: {} for tag in FILES}     # tag -> {path -> {seg -> bytes}}
    skipped = []
    for e in entries:
        by_tag = {}
        for id_str in e["ids"]:
            tag, path, seg = parse_id(id_str)
            by_tag.setdefault(tag, []).append((path, seg))
        has_markup = bool(re.search(r'\[(NAME|MTE|NL|PAGE|WAIT|C|RAW):?', e["kr"]))
        # narration leaf (block,2,7) uses the full-screen renderer (7x16, no page-clear
        # absorb) instead of the 3x14 dialogue box. Short fragments that dedup across a
        # narration and a non-narration leaf are single-line, so either geometry yields
        # identical bytes — deciding per entry is safe.
        # ⛔ 여신(루시리스)·미검증 블록에 한 곳이라도 걸치면 세션23 이전 경로로 되돌린다(위 주석).
        is_goddess_block = any((tag, path[0]) in LEGACY_GEOM_BLOCKS
                               for tag, locs in by_tag.items() for (path, seg) in locs)
        fs_leaves = set() if is_goddess_block else {
            path[1:3] for locs in by_tag.values() for (path, seg) in locs
            if path[1:3] in FULLSCREEN_GEOM}
        is_narr = bool(fs_leaves)      # 전체화면 텍스트 격자(대사 박스가 아님)
        # 한 항목이 여러 전체화면 리프에 걸치면 가장 좁은 지오메트리를 따른다.
        # 전체화면 + 비전체화면 혼합(실측 88건)은 전부 한 줄짜리 짧은 조각이라
        # 어느 쪽 지오메트리로 조판해도 같은 바이트가 나온다 — 전체화면을 우선한다.
        # dialogue leaves (block,2,5): re-flow the translator's JP-mirrored [NL] into
        # natural Korean line-fill (word-boundary greedy wrap), so short orphan words
        # no longer sit alone on a line. Narration keeps its authored structure (title
        # colour codes / condition lists) — geometry fix only. UI/condition/name leaves
        # keep exact breaks.
        is_dialogue = not is_narr and all(path[1:3] == DLG_LEAF
                      for locs in by_tag.values() for (path, seg) in locs)
        # reflow both dialogue AND narration to fill lines naturally; _reflow_groups
        # protects the intro title page (「…」/ＳＣＥＮＡＲＩＯ/colour-only lines) and
        # victory/defeat condition bullets from being merged.
        # manual_layout (dialogue_editor.py, 방식 A): the translator hand-placed the line
        # breaks in the review tool and wants them KEPT verbatim — turn reflow off for
        # that entry so its [NL]/[PAGE] ship exactly as authored (over-wide lines are
        # still word-wrapped and over-tall pages still paginate; only the auto re-fill of
        # the translator's own breaks is suppressed).
        fs_reflow = bool(fs_leaves) and fs_leaves <= FULLSCREEN_REFLOW
        do_reflow = (is_dialogue or fs_reflow) and not e.get("manual_layout")
        # 세션21 사용자 규칙: sentence_layout 항목(restyle_dialogue.py가 "문장이 끝나면 줄을
        # 바꾼다 / 그 외 줄바꿈은 넣지 않는다"로 재조판한 대사)은 페이지도 문장 경계에서만
        # 끊는다 — "문장 중간에 페이지가 넘어가면 해당 문장 자체를 다음 페이지로". 플래그가
        # 없는 항목(동결한 여신 블록, 세션18 수동 검수분 등)은 종전 동작 그대로 — 비침투.
        sentence_pages = bool(e.get("sentence_layout"))
        if fs_leaves:
            w = min(FULLSCREEN_GEOM[lf][0] for lf in fs_leaves)
            ml = min(FULLSCREEN_GEOM[lf][1] for lf in fs_leaves)
        else:
            w, ml = WIDTH, MAX_LINES
        # UI leaf (block,2,0): the menu/message boxes are NOT blank-filled before draw,
        # so a half-width {01} space (which advances the cursor without drawing) leaves
        # the previous glyph showing in its cell (user saw a stray 'ㅌ' in "나이프을 구입").
        # Use the FULL-WIDTH space (0x8140, draws a blank cell) for UI leaves — clean.
        is_ui = any(path[1:3] == UI_LEAF
                    for locs in by_tag.values() for (path, seg) in locs)
        # 여신/프롤로그 박스는 흡수줄이 필요(task#6) — absorb_box 플래그로 예외 처리.
        _goddess = bool(e.get("absorb_box"))
        # 시나리오 대화(2,5, 비-여신): 2페이지+ = 4줄, 흡수줄 없음(세션18 실기 확정).
        if is_dialogue and not _goddess:
            _page2 = DLG_PAGE2_LINES
            _absorb = False
        else:                       # 여신 박스/UI/제목 등: 종전 모델(흡수줄, 균일 줄수)
            _page2 = None
            _absorb = (not is_narr)
        if NO_ABSORB:
            _absorb = False
        _cap = max(ml, _page2 or ml)     # 페이지 최대 줄수(1페이지 ml, 2페이지+ page2)
        try:
            per_tag_data = {}
            for tag in by_tag:
                sp = kr_markup.FW_SPACE if is_ui else FILES[tag]["space"]
                sc = 0.5 if sp == kr_markup.HW_SPACE else 1.0
                # 여신 블록은 이름 폭도 옛 추정값(4칸) 그대로 — 동결이므로 바이트가 안 변한다.
                nw = None if is_goddess_block else name_w_all.get(tag)
                # {02}: UI 리프는 아이템/병종명이 들어오므로 추정 4칸 유지(None), 그 밖은
                # 주인공 이름이 확정이라 실제 폭. 여신 블록은 동결이므로 손대지 않는다.
                ww = None if (is_goddess_block or is_ui) else PLAYER_NAME_CELLS
                # {05}는 0폭이 아니라 1칸 들여쓰기다(세션24 실측). 나레이션에서만 센다 —
                # 다른 리프(특히 동결 대상 L2:100 상성표)는 조판을 건드리지 않는다.
                iw = 1.0 if (is_narr and not is_goddess_block) else 0.0
                if has_markup:
                    # enforce the physical window: word-wrap over-wide lines and
                    # re-paginate. Dialogue re-flows [NL] to fill lines naturally;
                    # narration/UI keep the translator's [NL]/[PAGE] structure.
                    kr_fixed = kr_markup.rewrap_markup(e["kr"], width=w, max_lines=ml,
                                                       space_cells=sc, absorb=_absorb,
                                                       reflow=do_reflow, page2_lines=_page2,
                                                       sentence_pages=sentence_pages,
                                                       name_w=nw, wait_w=ww, indent_w=iw)
                    pieces = kr_markup.parse_markup(kr_fixed, space=sp, absorb=_absorb)
                else:
                    # 마크업이 없으면 [NAME]도 없다 — 이름 폭 표가 필요 없는 경로.
                    pieces = kr_render.render_segment(e["kr"], width=w, window_lines=ml,
                                                      space=sp, absorb=_absorb, page2_lines=_page2,
                                                      sentence_pages=sentence_pages)
                if kr_markup.max_page_lines(pieces) > _cap:
                    raise ValueError(f"page > {_cap} lines")
                if kr_markup.max_line_width(pieces, nw, ww, iw) > w:
                    raise ValueError(f"line > {w} 칸")
                per_tag_data[tag] = kr_encoding_encode(pieces, table)
        except Exception as ex:
            skipped.append((e["ids"][0], str(ex)[:40]))
            continue
        for tag, locs in by_tag.items():
            for path, seg in locs:
                # keep the scenario-title table (2,8) Japanese — its {02} render path
                # garbles Korean (see TITLE_LEAF note). Skipping only the (2,8) location
                # leaves any deduped non-title use of the same string translated.
                if KEEP_JP_TITLES and path[1:3] == TITLE_LEAF:
                    continue
                edits[tag].setdefault(path, {})[seg] = per_tag_data[tag]
    if skipped:
        print(f"  skipped {len(skipped)} malformed entries (left original). sample:",
              [s[0] for s in skipped[:6]])

    # 3) bake glyphs into BOTH fonts (shared codes)
    fonts = {}
    for tag in FILES:
        fd = kr_font.FontDat.load(os.path.join(ORIG, FILES[tag]["font"]))
        for syl in table["order"]:
            info = table["map"][syl]
            fd.patch_font(fd.block_glyph_offset(info["block"], info["index"]),
                          kr_font.bake_glyph(syl, TTF, swap=True, y_offset=FONT_YOFF))
        # session-14: 8px cave payload -> FONT.DAT tail (reserved cells).
        # The caves are the SAME bytes gen_classnames emits for this BIN.
        # ★ session-22: the tile blob is GONE from the payload — the glyphs now
        #   ride IMG.DAT (img_re/gen_hud8.py) so no SH-2 write to VDP2 VRAM is
        #   needed. The reserve stays 9216B so PAYLOAD_OFF/cell reservation and
        #   the wrapper literal do not move; the tail 8KB is just unused now.
        if (os.environ.get("KR_CLASSNAMES", "1") != "0"
                and os.environ.get("KR_HUD8", "1") != "0"):
            _binx = open(os.path.join(ORIG, FILES[tag]["binf"]), "rb").read()
            _, _, payload = gen_classnames.build(_binx, table, tag)
            assert len(payload) <= gen_classnames.PAYLOAD_RESERVE
            off = gen_classnames.PAYLOAD_OFF
            fd.data[off:off + len(payload)] = payload
            fd.data[off + len(payload):off + gen_classnames.PAYLOAD_RESERVE] = \
                b"\x00" * (gen_classnames.PAYLOAD_RESERVE - len(payload))
            print(f"  {FILES[tag]['font']}: 8px cave payload {len(payload)}B @0x{off:x}")
        fonts[tag] = fd.data

    # 4) per file: apply edits to SCEN tree, reclaim padding, serialize, write disc
    import disc_tool
    disc = disc_tool.Disc(TRACK1)
    for tag, cfg in FILES.items():
        if not edits[tag]:
            continue
        scen = open(os.path.join(ORIG, cfg["scen"]), "rb").read()
        tree = scen_tool.parse(scen)
        # record per-block sizes before edits (alignment-preserving budget)
        touched_blocks = sorted({path[0] for path in edits[tag]})
        before = {b: block_size(tree, b) for b in touched_blocks}
        for path, segmap in edits[tag].items():
            leaf = node_at(tree, path)
            segs = leaf.raw.split(b"\x00")
            for seg_i, data in segmap.items():
                segs[seg_i] = data
            leaf.raw = b"\x00".join(segs)
        # keep EACH edited block's size EXACTLY constant via its own padding leaf
        # (grow -> trim padding; shrink -> extend padding). A block that changes
        # size shifts every later block and crashes the game's block-offset load.
        for b in touched_blocks:
            delta = block_size(tree, b) - before[b]
            pad = largest_zero_leaf(tree.children[b])
            if pad is None:
                if delta != 0:
                    raise ValueError(f"{tag} block {b}: no padding leaf to absorb {delta}B")
                continue
            if delta > 0:                       # grew -> trim delta zero bytes
                if len(pad.raw) < delta:
                    raise ValueError(f"{tag} block {b}: growth {delta}B exceeds padding "
                                     f"slack {len(pad.raw)}B (need MTE/shorter kr)")
                pad.raw = pad.raw[:len(pad.raw) - delta]
            elif delta < 0:                     # shrank -> extend padding
                pad.raw = pad.raw + b"\x00" * (-delta)
            after = block_size(tree, b) - before[b]
            if after != 0:
                raise ValueError(f"{tag} block {b}: size not preserved (delta {after})")
        if tag == "L2":
            import bugfixes_l2
            print("  L2 원작 버그 수정:", bugfixes_l2.patch_scenario(tree))
        scen_new = bytes(scen_tool.serialize(tree))
        assert len(scen_new) == len(scen), \
            f"{tag}: total size changed {len(scen)}->{len(scen_new)} (block misalignment)"
        scen_pad = scen_new + b"\x00" * (cfg["alloc"] - len(scen_new))
        print(f"{tag}: {len(edits[tag])} leaves edited across blocks {touched_blocks}, "
              f"SCEN size preserved ({len(scen_new)} == {len(scen)})")

        disc.write_file(cfg["font_lba"], fonts[tag])
        disc.write_file(cfg["scen_lba"], scen_pad)
        if cfg["bin_patch"]:
            off, orig, new = cfg["bin_patch"]
            binb = bytearray(open(os.path.join(ORIG, cfg["binf"]), "rb").read())
            assert bytes(binb[off:off+len(orig)]) == orig, f"{cfg['binf']} @0x{off:x} mismatch"
            binb[off:off+len(new)] = new
            # Class/unit-type names: rewrite the LANG{1,2}.BIN tables to Korean.
            # DEFAULT ON as of session 14 — the battle-safe redesign (conv table
            # in the string region, caves resident at 0x060FFC00 fed from the
            # FONT.DAT payload) was verified through the battle-animation screen
            # (prep 솔저/파이터/레딘 8px + battle VS Korean, no freeze).
            # KR_CLASSNAMES=0 reverts to katakana class names if ever needed.
            if os.environ.get("KR_CLASSNAMES", "1") != "0":
                binb = bytearray(gen_classnames.build(bytes(binb), table, tag)[0])
                print(f"  {cfg['binf']} class names -> Korean (gen_classnames)")
            # load/save-screen text strings (面/の続きから/データがありません… in BIN)
            binb = bytearray(gen_menutext.build(bytes(binb), table, tag))
            print(f"  {cfg['binf']} load/save text -> Korean (gen_menutext)")
            # katakana-redirect label tables (게임설정/페이즈종료) live in the BIN —
            # rebuilding from originals silently reverts them (session-12 regression),
            # so apply the table patch here every time. The matching glyphs are in
            # IMG.DAT (disc-carried; patch_katakana_redirect.py's IMG half).
            import patch_katakana_redirect as _pkr
            binb = bytearray(_pkr.patch_bin(bytes(binb), _pkr.CONFIGS[tag], tag))
            print(f"  {cfg['binf']} katakana-redirect tables (게임설정/페이즈종료)")
            if tag == "L2":
                import bugfixes_l2
                binb = bytearray(bugfixes_l2.patch_bin(bytes(binb)))
                print("  L2 퇴각 횟수·용병 증가·엘레멘탈 고용 수정")
            disc.write_file(cfg["bin_lba"], bytes(binb))
            print(f"  {cfg['binf']} {{01}} patch applied @0x{off:x}")

    out = os.path.join(BUILD, "Track 1 (patched).bin")
    disc.save(out)

    # 5) validate: re-extract SCEN, EDC/ECC on a changed sector per file
    d2 = disc_tool.Disc(out)
    for tag, cfg in FILES.items():
        if not edits[tag]:
            continue
        re_scen = d2.read_file(cfg["scen_lba"], cfg["alloc"])
        scen_tool.parse(re_scen)  # must parse without error
        lba = cfg["scen_lba"]
        sec = bytearray(d2.data[lba*disc_tool.RAW:lba*disc_tool.RAW+disc_tool.RAW])
        ref = bytes(sec); disc_tool.regen_sector(sec)
        assert bytes(sec) == ref, f"{tag} EDC/ECC mismatch"
    print(f"self-check: SCEN re-parse OK, EDC/ECC valid.  artifacts -> {out}")


def kr_encoding_encode(pieces, table):
    out = bytearray()
    for kind, val in pieces:
        out += kr_encoding.encode_text(val, table) if kind == "kr" else val
    return bytes(out)


if __name__ == "__main__":
    ws = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "translation_worksheet_dedup.json")
    print(f"=== reinsertion from {ws} ===")
    build(json.load(open(ws, encoding="utf-8")))
