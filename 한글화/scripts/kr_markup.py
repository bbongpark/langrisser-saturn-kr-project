#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kr_markup.py — parse a translator's Korean string (with inline control markup)
into encode-pieces for reinsertion.

A worksheet `kr` entry is Korean text plus bracketed control tokens that map back
to the game's SCEN control codes (which must be preserved for the engine to work).

Markup tokens:
  [NAME:XX]  -> {09 XX}  character-name variable (XX = hex, e.g. [NAME:45])
  [MTE:XX]   -> {04 XX}  keep an original MTE reference (rare; usually dropped)
  [NL]       -> {08}     in-window line break  (also: a literal '\\n' in kr)
  [PAGE]     -> {06}{07} in-segment page turn (clear window, wait ▼, next page) —
                         lets one segment hold >3 lines without adding segments
  [WAIT]     -> {02}     wait / dynamic-insert
  [C:XX]     -> raw byte 0xXX   (escape hatch for {03}/{05} UI codes)
  [RAW:hh..] -> raw bytes hh..  (arbitrary passthrough)
Everything else is Korean display text; ASCII spaces become `space` bytes
(default {01} half-width; pass FW space for the patch-free 16px variant).

Returns encode-pieces: [('kr', text) | ('raw', bytes), ...] consumed by
kr_encoding.encode_text (per 'kr' piece) + raw passthrough.
"""
import re
import sys, io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HW_SPACE = b"\x01"
FW_SPACE = b"\x81\x40"
# comma/period after which a following space byte is dropped (full-width punct cell
# already separates; a space just widens the gap). ASCII + full-width + JP forms.
_NOSPACE_AFTER = ",.，．。、"
CTRL_NL = b"\x08"
PAGE_BREAK = b"\x06\x07"

_TOKEN = re.compile(r"\[(NAME|MTE|C|RAW):([0-9A-Fa-f]+)\]|\[(NL|WAIT|PAGE)\]")

# tokens that render as (estimated) visible width, treated as unsplittable words
_ATOM = re.compile(r"\[(?:NAME|MTE|C|RAW):[0-9A-Fa-f]+\]|\[(?:NL|WAIT|PAGE)\]")

# a single zero-width control token ([C:XX] or [WAIT]) that draws nothing/advances no
# line on its own — usable as a page's "consumed first line" (absorb) lead.
_CTRL_ONLY_TOK = re.compile(r"\[(?:C:[0-9A-Fa-f]+|WAIT)\]$")
# a [PAGE] whose new page already opens with such control token(s) then a line break:
# the control-lead IS the renderer-eaten first line, so no extra absorb {08} is needed
# (mirrors the original game's {06}{07}{05}{08} quiz-box page structure).
_PAGE_LEAD = re.compile(r"(?:\[(?:C:[0-9A-Fa-f]+|WAIT)\])+\[NL\]")


def _atom_width(tok, name_w=None, wait_w=None, indent_w=0.0):
    """토큰 하나가 화면에서 차지하는 칸수.

    `indent_w`: `[C:05]`({05})가 차지하는 칸수. **{05}는 0폭 제어코드가 아니라
    1칸 들여쓰기 공백이다**(세션24 실측 — 원문에서 `{05}`로 시작하는 줄은 최대 15칸,
    없는 줄은 16칸). 나레이션 리프 `(2,7)`에서만 1.0을 넘긴다. 다른 리프는 조판을
    건드리지 않으려고 종전대로 0.0(특히 `L2:100` 상성표는 동결·보류 대상).

    `name_w`: `{xx: 칸수}` — `[NAME:xx]`가 펼쳐질 **실제 이름의 폭**(`kr_names.width_map`).
    주면 정확한 값을, 안 주거나 표에 없으면 종전 추정값(NAME_WIDTH_EST)을 쓴다.
    `wait_w`: `[WAIT]`({02})의 실제 폭. 안 주면 종전 추정값(WAIT_WIDTH_EST)."""
    if tok.startswith("[NAME:"):
        if name_w:
            w = name_w.get(int(tok[6:-1], 16))
            if w is not None:
                return w
        return NAME_WIDTH_EST
    if tok == "[WAIT]":
        # {02} expands to a runtime argument (player name / item name), NOT 0
        return WAIT_WIDTH_EST if wait_w is None else wait_w
    if tok.startswith("[MTE:"):
        return 2
    if tok == "[C:05]":
        return indent_w                    # {05} = 들여쓰기 공백(나레이션에서 1칸)
    return 0            # [C]/[RAW] render ~0 칸


def _is_ctrl_only_line(line):
    """True if `line` (a list of (tok, sp, w) from rewrap) is non-empty and consists
    solely of zero-width control tokens ([C:XX]/[WAIT]) — a page-lead absorb line."""
    return bool(line) and all(_CTRL_ONLY_TOK.match(tok) for tok, sp, w in line)


# CLOSING punctuation that attaches to the preceding word when we re-flow lines
# together (no space before it). Deliberately EXCLUDES ellipsis '…'/'‥' and colon —
# those open a new clause and must keep a word-separating space, else consecutive
# ellipsis-led lines glue into one unbreakable run that overflows the window.
_NOSPACE_LEAD = "。、，,.!?！？」』）)]％〜～"


# a line that must keep its own break even in reflow: bullet/condition list items
_LIST_LEAD = re.compile(r"^(?:\[[^\]]*\])*[・＊*]")


def _reflow_keep_own_line(raw_line, vis):
    """True if a narration/dialogue line must NOT be merged into a prose flow: bullet/
    condition items (・ ＊), scenario-title lines (「…」 / ＳＣＥＮＡＲＩＯ header), and
    control-only lines (colour codes with no visible text). Protects the intro title
    page's structure and victory/defeat condition lists when reflowing."""
    if _LIST_LEAD.match(raw_line):
        return True
    if not vis:                              # control-only (only [C:xx]/[WAIT])
        return True
    if "「" in vis or "」" in vis or "ＳＣＥＮＡＲＩＯ" in raw_line:
        return True
    return False


def _reflow_groups(page):
    """Split a page's translator [NL] lines into flow GROUPS for natural Korean
    re-wrap. Consecutive prose lines merge into one group (rejoined with a space at
    word boundaries — except before leading closing punctuation); but a line that
    opens a bullet/condition list item (・ ＊) starts its own group so victory/defeat
    condition lists and menus keep their per-item breaks. Each returned group is
    wrapped independently by the caller (so groups never share a display line)."""
    groups = []
    cur = None                               # None = no group started yet
    prev_keep = False
    for ln in page.split("[NL]"):
        s = ln.lstrip()
        vis = re.sub(r"\[[^\]]*\]", "", s)
        keep = _reflow_keep_own_line(s, vis)
        if cur is None:
            cur = s
        elif keep or prev_keep:              # boundary line -> its own group
            groups.append(cur); cur = s
        else:                                # prose -> merge into current group
            prev = cur.rstrip()
            sep = "" if (not prev or not vis or vis[0] in _NOSPACE_LEAD
                         or prev.endswith(("(", "（", "「", "『"))) else " "
            cur = prev + sep + s
        prev_keep = keep
    groups.append(cur if cur is not None else "")
    return groups


def rewrap_markup(kr, width=14, max_lines=3, space_cells=0.5, absorb=True, reflow=False,
                  page2_lines=None, sentence_pages=False, name_w=None, wait_w=None,
                  indent_w=0.0):
    """Enforce the physical window (14 칸 x 3 lines) on a translator's markup string.

    The translator's [PAGE] page breaks and [NL] line breaks are HARD boundaries we
    keep; but if any resulting line is wider than `width` 칸 we word-wrap it (adding
    [NL]), and if a page then exceeds `max_lines` lines we split it into more pages
    ([PAGE]). [NAME]/[MTE]/[WAIT]/... tokens are atomic words. Idempotent on strings
    that already fit. Returns a new markup string (WAIT tokens preserved inline).

    `absorb`: the small DIALOGUE window's {06}{07} clear callback eats the first line
    of each page after the first (so pages 2+ hold max_lines-1 content + 1 absorb).
    The full-screen NARRATION renderer (scenario intro, leaf (block,2,7)) does NOT eat
    a line — its pages start directly with content. Pass absorb=False for narration so
    every page holds the full max_lines and no absorb slot is reserved.

    `reflow`: discard the translator's within-page [NL] and re-wrap the whole page as
    natural Korean, filling each line up to `width` at word boundaries. Keeps [PAGE]
    boundaries. Fixes JP-mirrored breaks that orphan a short word on its own line.

    `sentence_pages` (세션21 사용자 규칙): 페이지를 하드라인(=한 문장) 경계에서만 끊는다.
    워드랩으로 2줄이 된 문장이 페이지 끝에 걸치면 그 문장을 통째로 다음 페이지로 내린다
    ("문장 중간에 페이지가 넘어가면 해당 문장 자체를 다음 페이지로 넘긴다"). 한 문장이 페이지
    높이보다 길면 넘길 곳이 없으므로 종전대로 쪼갠다.

    `name_w`: `[NAME:xx]`의 실제 이름 폭 표(`kr_names.width_map(ws)[tag]`). 주면 이름 변수를
    추정 4칸이 아니라 실제 칸수로 재서 워드랩한다 — 긴 이름(베른하르트 5칸)이 창을 넘기던
    것과 짧은 이름(레딘 2칸)에서 줄이 일찍 접히던 것이 함께 해결된다.

    `wait_w` (세션24): `[WAIT]`({02})의 실제 폭. {02}는 "스크립트가 밀어 넣은 런타임 인자"라
    자리마다 정체가 다르다 — **대사(2,5)·나레이션(2,7)·조건(2,6) 리프에서는 100% 주인공 이름**
    (엘윈/레딘 = 2칸)이고, 아이템/병종명이 들어가는 것은 **UI 리프(2,0)뿐**이다(세션24 전수
    조사: {02} 684회 중 아이템 문맥 6종이 전부 UI 리프). 안 주면 종전 추정값 4칸."""
    kr = kr.replace("\n", "[NL]")
    out_pages = []
    first_page = True                        # only the segment's very first page is full
    for page in kr.split("[PAGE]"):
        sub_lines = []                       # list of token-lists (each a display line)
        line_group = []                      # sub_lines[i]가 나온 하드라인(문장) 번호
        hards = _reflow_groups(page) if reflow else page.split("[NL]")
        for _gi, hard in enumerate(hards):
            _start = len(sub_lines)
            # tokenize the hard line into words: plain-text words + atomic [..] tokens,
            # remembering whether a space preceded each word/token.
            items, pos = [], 0
            state = [False]                  # state[0] = a space precedes the next word

            def emit_run(text):
                for k, w in enumerate(text.split(" ")):
                    if k > 0:
                        state[0] = True      # split consumed a real space
                    if w:
                        items.append((w, state[0], len(w))); state[0] = False

            for m in _ATOM.finditer(hard):
                if m.start() > pos:
                    emit_run(hard[pos:m.start()])
                items.append((m.group(0), state[0],
                              _atom_width(m.group(0), name_w, wait_w, indent_w)))
                state[0] = False
                pos = m.end()
            if pos < len(hard):
                emit_run(hard[pos:])
            # ⛔ 공백 없이 앞에 붙는 조각은 **같은 단어**다 — 줄을 가르면 안 된다.
            # `[NAME:0c]이라고` 는 토크나이저가 아톰 하나 + 글자 하나로 쪼개 놓지만 그
            # 사이엔 공백이 없다. 병합하지 않으면 워드랩이 `…이끄는 레온 / 이라고 한다.`
            # 처럼 이름과 조사를 갈라 놓는다(세션24 실사고). `[WAIT]`/`[MTE]`/`[C:xx]` 도 같다.
            merged = []
            for tok, sp, w in items:
                if merged and not sp:
                    ptok, psp, pw = merged[-1]
                    merged[-1] = (ptok + tok, psp, pw + w)
                else:
                    merged.append((tok, sp, w))
            items = merged
            # greedy wrap items into <=width 칸 lines
            cur, cur_w = [], 0.0
            for tok, sp, w in items:
                add = w + (space_cells if (cur and sp) else 0)
                if cur and cur_w + add > width:
                    sub_lines.append(cur); cur, cur_w = [(tok, False, w)], float(w)
                else:
                    cur.append((tok, sp, w)); cur_w += add
            sub_lines.append(cur)            # keep empty lines (translator blank lines)
            line_group.extend([_gi] * (len(sub_lines) - _start))
        # paginate: the segment's first page holds max_lines lines; every later page
        # (after any {06}{07}, translator- or wrap-inserted) loses one line to the
        # renderer's consumed absorb slot, so it holds max_lines-1 (see parse_markup).
        # EXCEPTION: a later page that already opens with a zero-width control-only
        # line (e.g. [C:05]) supplies its own eaten first line, so parse_markup adds
        # no bare absorb and this page holds the full max_lines (that control line +
        # max_lines-1 content). Miscounting it as content is what split #30's box.
        # 세션18 실기 확정: 이름 있는 시나리오 대화는 1페이지=이름+max_lines(3), 2페이지+는
        # 이름 없어 page2_lines(4)줄(흡수줄 없음). page2_lines=None이면 종전대로 max_lines.
        p2 = page2_lines if page2_lines is not None else max_lines
        i = 0
        while i < len(sub_lines):
            if first_page:
                cap = max_lines                  # 1페이지: 이름줄 아래 max_lines
            elif not absorb:
                cap = p2                          # 2페이지+: 이름 없음 → 전체 높이(no absorb)
            else:
                lead_absorbs = _is_ctrl_only_line(sub_lines[i])
                cap = p2 if lead_absorbs else p2 - 1   # 흡수줄이 한 줄 먹음(여신 박스)
            end = min(i + cap, len(sub_lines))
            if (sentence_pages and end < len(sub_lines)
                    and line_group[end] == line_group[end - 1]):
                # 페이지 경계가 한 문장을 가른다 → 그 문장 첫 줄까지 후퇴시켜 통째로 다음 페이지로.
                g, gs = line_group[end], end
                while gs > i and line_group[gs - 1] == g:
                    gs -= 1
                if gs > i:                   # 후퇴해도 이 페이지에 남는 문장이 있을 때만
                    end = gs
            out_pages.append(sub_lines[i:end]); i = end
            first_page = False
        if not sub_lines and first_page:     # a wholly empty first page
            out_pages.append([]); first_page = False
    # rebuild the markup string
    def join_line(line):
        s = ""
        for j, (tok, sp, w) in enumerate(line):
            if j > 0 and sp:
                s += " "
            s += tok
        return s
    parts = []
    for pi, page in enumerate(out_pages):
        if pi > 0:
            parts.append("[PAGE]")
        parts.append("[NL]".join(join_line(l) for l in page))
    return "".join(parts)


def parse_markup(kr, space=HW_SPACE, absorb=True):
    """Korean+markup string -> encode-pieces. Raises ValueError on bad markup.

    `absorb=False` (narration): [PAGE] emits only {06}{07}, no absorbing {08} — the
    full-screen narration renderer starts each page's first line with content and does
    not eat it (unlike the dialogue box, see rewrap_markup)."""
    pieces = []
    kr = kr.replace("\n", "[NL]")
    pos = 0

    def emit_text(txt):
        # split on ASCII spaces -> interleave `space` bytes between word runs.
        # EXCEPTION: drop the space byte when the preceding word ends with a comma or
        # period (,.，．。、) — the full-width punctuation cell already gives separation,
        # so a following space just widens the gap (user request: 구두점 뒤 공백 제거,
        # 부호는 전각 유지). rewrap_markup still counts the space for wrapping (safe).
        parts = txt.split(" ")
        for i, part in enumerate(parts):
            if i > 0:
                prev = parts[i - 1]
                if not (prev and prev[-1] in _NOSPACE_AFTER):
                    pieces.append(("raw", space))
            if part:
                pieces.append(("kr", part))

    for m in _TOKEN.finditer(kr):
        if m.start() > pos:
            emit_text(kr[pos:m.start()])
        if m.group(1):                       # [KIND:HEX]
            kind, hexv = m.group(1), m.group(2)
            if kind == "NAME":
                pieces.append(("raw", b"\x09" + bytes([int(hexv, 16)])))
            elif kind == "MTE":
                pieces.append(("raw", b"\x04" + bytes([int(hexv, 16)])))
            elif kind == "C":
                pieces.append(("raw", bytes([int(hexv, 16)])))
            elif kind == "RAW":
                if len(hexv) % 2:
                    raise ValueError(f"[RAW:{hexv}] odd hex length")
                pieces.append(("raw", bytes.fromhex(hexv)))
        else:                                # [NL] | [WAIT] | [PAGE]
            g = m.group(3)
            if g == "PAGE":
                # {06}{07} clears the window; the renderer's clear callback then WIPES
                # the first line typed on the new page (re-confirmed on hardware, task
                # #6 — removing this absorb dropped page 2's real first line). Emit an
                # absorbing {08} so the translator's first post-[PAGE] line survives —
                # mirrors kr_render.render_segment (pages 2+ = window_lines-1 content).
                # EXCEPTION: if the page already opens with a zero-width control-lead
                # (e.g. [C:05][NL], as the original quiz boxes do), that lead is itself
                # the eaten first line — adding a bare absorb too would double the blank
                # line and push content off the page. Skip the absorb in that case.
                pieces.append(("raw", PAGE_BREAK))
                if absorb and not _PAGE_LEAD.match(kr, m.end()):
                    pieces.append(("raw", CTRL_NL))
            else:
                pieces.append(("raw", {"NL": CTRL_NL, "WAIT": b"\x02"}[g]))
        pos = m.end()
    if pos < len(kr):
        emit_text(kr[pos:])
    return pieces


NAME_WIDTH_EST = 4      # a {09 XX} name variable expands to a runtime name; estimate 4 칸
WAIT_WIDTH_EST = 4      # {02} expands to player name (엘윈/레딘=2칸) or item name (up to
                        # ~5칸); estimate 4 so lines with [WAIT] don't overflow when it
                        # expands (was 0 → narration/dialogue lines overran the window).


def line_widths(pieces, name_w=None, wait_w=None, indent_w=0.0):
    """Per-line widths in 칸 (fullwidth cells) from encode-pieces. A Korean/punct
    char is 1 칸; a half-width {01} space is 0.5 칸, a fullwidth space 1.0 칸; a
    [NAME] variable uses `name_w` (kr_names.width_map) if given, else NAME_WIDTH_EST;
    a [WAIT] ({02}) uses `wait_w` if given, else WAIT_WIDTH_EST.
    Lines split on {08} and {06}{07}.
    Used to enforce the physical 14-칸 (224px) window width per line."""
    widths, cur = [], 0.0
    for kind, val in pieces:
        if kind == "kr":
            cur += len(val)
        elif val == HW_SPACE:
            cur += 0.5
        elif val == FW_SPACE:
            cur += 1.0
        elif val in (CTRL_NL, PAGE_BREAK):
            widths.append(cur); cur = 0.0
        elif len(val) == 2 and val[0] == 0x09:      # {09 XX} name variable
            cur += (name_w or {}).get(val[1], NAME_WIDTH_EST)
        elif val == b"\x02":                         # {02} dynamic name (player/item)
            cur += WAIT_WIDTH_EST if wait_w is None else wait_w
        elif val == b"":                        # {05} 들여쓰기 공백(나레이션 1칸)
            cur += indent_w
        # other control raws ({04} MTE handled by caller, etc.) add ~0
    widths.append(cur)
    return widths


def max_line_width(pieces, name_w=None, wait_w=None, indent_w=0.0):
    """Widest line in 칸 across all pages (each page cleared by {06}{07})."""
    return max(line_widths(pieces, name_w, wait_w, indent_w))


def line_count(pieces):
    """Number of display lines = 1 + count of {08} line-break raw pieces."""
    return 1 + sum(1 for k, v in pieces if k == "raw" and v == CTRL_NL)


def max_page_lines(pieces):
    """Max display lines within any single page (pages split by {06}{07}). This is
    what must stay <= the window height (3): a segment may be long overall as long
    as each page fits, because {06}{07} clears the window between pages."""
    worst = cur = 1
    for k, v in pieces:
        if k != "raw":
            continue
        if v == PAGE_BREAK:
            worst = max(worst, cur); cur = 1
        elif v == CTRL_NL:
            cur += 1
    return max(worst, cur)


def _raw_bytes(pieces):
    """Concatenate only the raw pieces (kr pieces need the font table to encode)."""
    return b"".join(v for k, v in pieces if k == "raw")


def _selftest():
    p = parse_markup("내 이름은 [NAME:45]。[NL]지상에선 빛의 여신。")
    raw = _raw_bytes(p)
    # structure check: name var 09 45, line break 08, half-width spaces 01 present
    assert b"\x09\x45" in raw and b"\x08" in raw and b"\x01" in raw, raw.hex()
    assert line_count(p) == 2, line_count(p)
    # '。' is a non-Hangul kr char -> stays in a 'kr' piece (encoded via passthrough later)
    kr_txt = "".join(v for k, v in p if k == "kr")
    assert "내" in kr_txt and "。" in kr_txt
    p2 = parse_markup("테스트[C:05][RAW:8140]끝")
    raw2 = _raw_bytes(p2)
    assert b"\x05" in raw2 and b"\x81\x40" in raw2
    # [PAGE] -> {06}{07}; page-aware line count
    p3 = parse_markup("한줄[NL]두줄[NL]세줄[PAGE]다음[NL]둘")
    raw3 = _raw_bytes(p3)
    assert b"\x06\x07" in raw3
    # [PAGE] emits {06}{07} + an absorbing {08} (renderer eats page 2's first line).
    # Total {08}: 2 (page1) + 1 (absorb) + 1 (page2) = 4 -> line_count 5.
    assert line_count(p3) == 5, line_count(p3)
    # page1 = 한줄/두줄/세줄 (3); page2 = absorb/다음/둘 (3) -> max 3
    assert max_page_lines(p3) == 3, max_page_lines(p3)
    # [C:05] page-lead (quiz-box structure): a page opening with a zero-width control
    # lead supplies its own eaten first line, so parse adds NO bare absorb {08} and
    # rewrap does NOT count the lead as content (no wrong page split). Result must be
    # {06}{07}{05}{08}content — NOT {06}{07}{08}{05}{08} (double blank + overflow).
    q = "가[NL]나[PAGE][C:05][NL]다[NL]라"
    rq = rewrap_markup(q, 14, 3)
    assert rq == q, rq                      # 다/라 stay on one page (not split)
    raw_q = _raw_bytes(parse_markup(rq))
    assert b"\x06\x07\x05\x08" in raw_q, raw_q.hex()      # page-lead, single absorb
    assert b"\x06\x07\x08\x05" not in raw_q, raw_q.hex()  # no doubled absorb
    assert max_page_lines(parse_markup(rq)) == 3
    print("kr_markup selftest OK")


if __name__ == "__main__":
    _selftest()
