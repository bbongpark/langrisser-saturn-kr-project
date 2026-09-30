#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kr_render.py — Korean typesetting for Langrisser Saturn message windows.

Window model (reverse-engineered from LANG1_SCEN block-20 narration, verified on
hardware 2026-07-13):
  * Each NUL-separated SCEN segment = ONE message window.
  * Lines within a window are separated by control code {08}.
  * A window holds up to `max_lines` lines (default 3); overflow -> next window.
  * Each line is ~`width` fullwidth cells wide (default 14). One Korean syllable
    and one fullwidth space (0x8140) each occupy 1 cell.

render_message(korean) turns a translated Korean string (words separated by
spaces, '\\n' = forced line break) into a list of windows, each a list of
"pieces" ready for encoding:
    ('kr', text)   -> syllables encoded via the font table (kr_encoding)
    ('raw', bytes) -> literal bytes (fullwidth space 0x8140, control code 0x08)
This is the encode-piece format consumed by build_translate_poc.encode_pieces.
"""
import sys, io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

FW_SPACE = b"\x81\x40"   # fullwidth space (16px; renders blank, no patch needed)
HW_SPACE = b"\x01"       # {01} half-width space (8px) — needs the LANG1/LANG2.BIN
                         # SH-2 patch (build_hwspace_poc); verified on hardware.
CTRL_NL = b"\x08"        # in-window newline
PAGE_BREAK = b"\x06\x07"  # {06}{07} = in-segment page turn (clear window, wait ▼,
                          # show next page). Lets ONE segment hold >max_lines lines
                          # WITHOUT adding NUL segments (script indices stay valid).
                          # Already used by the original game — no patch needed.
DEFAULT_WIDTH = 14       # cells per line (fullwidth-cell budget)
DEFAULT_MAX_LINES = 3    # lines per page (window)
DEFAULT_SPACE = HW_SPACE  # shipping default: half-width (compact, natural)


def wrap_paragraphs(korean, width=DEFAULT_WIDTH, space_cells=1.0):
    """wrap_words와 같은 워드랩이지만, 결과를 '\\n' 문단(=세션21 규칙의 한 문장) 단위로
    묶어 list[list[line]]로 반환한다. render_segment의 문장 단위 페이지네이션이 쓴다."""
    paras = []
    for para in korean.split("\n"):
        lines = []
        words = [w for w in para.split(" ") if w != ""]
        if not words:
            paras.append([[]])
            continue
        cur, cur_cells = [], 0.0
        for word in words:
            # hard-split an over-wide single word into width-sized chunks
            while len(word) > width:
                if cur:
                    lines.append(cur); cur, cur_cells = [], 0.0
                lines.append([word[:width]])
                word = word[width:]
            add = len(word) + (space_cells if cur else 0)   # space before the word
            if cur and cur_cells + add > width:
                lines.append(cur); cur, cur_cells = [word], float(len(word))
            else:
                cur.append(word); cur_cells += add
        if cur:
            lines.append(cur)
        paras.append(lines)
    return paras


def wrap_words(korean, width=DEFAULT_WIDTH, space_cells=1.0):
    """Greedy word-wrap. Returns list[list[str]] = lines of words.
    '\\n' forces a line break; a word longer than `width` gets its own line
    (hard-split only if it alone exceeds width).

    `width` is the window width in fullwidth cells (칸). Each syllable/punct is
    1 칸; an inter-word space costs `space_cells` 칸 — 0.5 for a half-width {01}
    space (8px), 1.0 for a fullwidth space (16px). Counting the real space width
    keeps a line within the physical window (14 칸 = 224px) AND lets half-width
    spaces pack more per line (the whole point of §5.1)."""
    return [ln for para in wrap_paragraphs(korean, width, space_cells) for ln in para]


def _space_cells(space):
    """Width in 칸 of one inter-word space of the given raw bytes."""
    return 0.5 if space == HW_SPACE else 1.0


def render_message(korean, width=DEFAULT_WIDTH, max_lines=DEFAULT_MAX_LINES,
                   space=DEFAULT_SPACE):
    """Return list of windows; each window is a list of encode-pieces
    (see module docstring). Windows map 1:1 to NUL-separated SCEN segments.
    `space` is the raw bytes inserted between words (HW_SPACE {01} by default —
    needs the SH-2 patch; pass FW_SPACE for a patch-free 16px space)."""
    lines = wrap_words(korean, width, _space_cells(space))
    windows = [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)] or [[]]
    out = []
    for win in windows:
        pieces = []
        for li, line in enumerate(win):
            if li > 0:
                pieces.append(("raw", CTRL_NL))
            for wi, word in enumerate(line):
                if wi > 0:
                    pieces.append(("raw", space))
                pieces.append(("kr", word))
        out.append(pieces)
    return out


def render_segment(korean, width=DEFAULT_WIDTH, window_lines=DEFAULT_MAX_LINES,
                   space=DEFAULT_SPACE, absorb=True, page2_lines=None,
                   sentence_pages=False):
    """Auto-typeset Korean into a SINGLE SCEN segment, paginating with {06}{07}.

    Unlike render_message (separate windows = separate NUL segments), this keeps ONE
    segment and turns pages in place with {06}{07} — an arbitrarily long translation
    replaces a single original segment without shifting script indices (verified on
    hardware). Lines wrap at `width` cells.

    Window model (reverse-engineered AND re-confirmed on hardware 2026-07-13, task #6):
    the FIRST content line after a {06}{07} page break is LOST — the {07} window-clear
    callback (0x0603aec8) fires a beat after typing starts and wipes whatever was drawn
    on line 1 (this is the user's "글씨가 다 없어진 다음 새로 나오면서" symptom). So every
    page after the first must begin with an empty {08} line to absorb that clear:
      page 1        -> up to window_lines content lines
      pages 2..N    -> up to window_lines-1 content lines (+ 1 consumed empty line)
    NOTE (task #6): removing this absorb line was tried and REVERTED — it drops page 2's
    real first line on hardware (verified: prologue box#0 lost "지상에서는 빛의 여신이라고").
    The absorb's cost is a blank top row on pages 2+; eliminating that cleanly needs an
    ASM fix to the clear timing (kr_render/kr_markup byte tricks can't), so it stays.

    `sentence_pages` (세션21 사용자 규칙): 페이지를 '\\n' 문단(=한 문장) 경계에서만 끊어,
    워드랩으로 2줄이 된 문장이 페이지 끝에 걸치면 통째로 다음 페이지로 내린다. 한 문장이
    페이지 높이보다 길면 넘길 곳이 없으므로 종전대로 쪼갠다. (kr_markup.rewrap_markup의
    같은 이름 파라미터와 동작 일치 — 마크업 있는 항목/없는 항목이 같은 조판을 받는다.)
    """
    paras = wrap_paragraphs(korean, width, _space_cells(space))
    lines, line_group = [], []
    for gi, para in enumerate(paras):
        for ln in para:
            lines.append(ln); line_group.append(gi)
    # 세션18 실기 확정: 이름 있는 시나리오 대화 박스는 1페이지=이름+window_lines(3)줄,
    # 2페이지+는 이름이 없어 page2_lines(4)줄. page2_lines=None이면 종전대로 window_lines.
    p2 = page2_lines if page2_lines is not None else window_lines
    # absorb=True: pages 2+ hold p2-1 content (+1 consumed clear line, 여신 박스).
    # absorb=False: full p2 per page, no absorbing {08} (시나리오 대화, 실기 확정).
    step = max(1, p2 - 1) if absorb else p2
    pages, i, first = [], 0, True
    while i < len(lines):
        cap = window_lines if first else step
        end = min(i + cap, len(lines))
        if (sentence_pages and end < len(lines)
                and line_group[end] == line_group[end - 1]):
            g, gs = line_group[end], end
            while gs > i and line_group[gs - 1] == g:
                gs -= 1
            if gs > i:
                end = gs
        pages.append(lines[i:end]); i = end; first = False
    if not pages:
        pages = [[]]
    pieces = []
    for pi, page in enumerate(pages):
        if pi > 0:
            pieces.append(("raw", PAGE_BREAK))     # {06}{07}
            if absorb:
                pieces.append(("raw", CTRL_NL))    # consumed leading line (see docstring)
        for li, line in enumerate(page):
            if li > 0:
                pieces.append(("raw", CTRL_NL))
            for wi, word in enumerate(line):
                if wi > 0:
                    pieces.append(("raw", space))
                pieces.append(("kr", word))
    return pieces


def pieces_preview(pieces):
    """Human-readable one-line preview of a window's pieces."""
    s = []
    for kind, val in pieces:
        if kind == "kr":
            s.append(val)
        elif val in (FW_SPACE, HW_SPACE):
            s.append(" ")
        elif val == CTRL_NL:
            s.append("⏎")
        else:
            s.append("<%s>" % val.hex())
    return "".join(s)


def _selftest():
    para = ("엘사리아에 어서 오세요 제 이름은 루시리스 지상에서는 빛의 여신이라 "
            "불리고 있습니다 지금 이 세계는 어둠의 위협에 노출되려 하고 있습니다")
    wins = render_message(para, width=14, max_lines=3)
    print(f"input syllables/spaces -> {len(wins)} window(s)")
    for wi, w in enumerate(wins):
        # reconstruct lines to check width (half-width spaces count 0.5 칸)
        lines, cur = [], ""
        for kind, val in w:
            if kind == "raw" and val == CTRL_NL:
                lines.append(cur); cur = ""
            elif kind == "kr":
                cur += val
            elif kind == "raw" and val in (FW_SPACE, HW_SPACE):
                cur += " "
        lines.append(cur)
        assert len(lines) <= 3, f"window {wi} has {len(lines)} lines > 3"
        print(f"  window {wi}:")
        for ln in lines:
            cells = sum(1 for c in ln if c != " ") + 0.5 * ln.count(" ")  # 칸 (half-width space = 0.5)
            assert cells <= 14, f"line '{ln}' = {cells} 칸 > 14"
            print(f"    [{cells:4.1f}] {ln}")
    # render_segment: with the hardware-required absorb line, a 4-line block paginates
    # 3 (page1) + 1 content (page2, preceded by the consumed empty {08}). Expect the
    # piece right after {06}{07} to be the absorb {08}, then the content.
    seg = render_segment("가\n나\n다\n라", width=14, window_lines=3)
    npage = sum(1 for k, v in seg if k == "raw" and v == PAGE_BREAK)
    assert npage == 1, npage
    pb = seg.index(("raw", PAGE_BREAK))
    assert seg[pb + 1] == ("raw", CTRL_NL), "absorb line missing after {06}{07}"
    assert seg[pb + 2] == ("kr", "라"), seg[pb + 2]
    print("selftest OK (all lines <=14 칸, all windows <=3 lines; render_segment absorb kept)")


if __name__ == "__main__":
    _selftest()
