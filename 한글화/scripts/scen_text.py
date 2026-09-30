#!/usr/bin/env python3
"""
scen_text.py — text layer on top of scen_tool.

A text leaf is a NUL-separated array of SJIS strings. Each string is a token
stream: SJIS double-byte chars, ASCII, and <0x0A control codes. Some control
codes take a 1-byte argument.

Control codes (per tech-doc §3.3, re-verified by frequency here):
  09 XX  -> [NAME:XX]  character-name variable
  01     -> {01}       (orig unused) repurposed as half-width space in KR build
  02     -> {02}       in-window newline / dynamic insert
  04 XX  -> {04:XX}    MTE dictionary expansion (Japanese fragments)
  05,06,07,08 -> window/page control
"""
import sys, io, os
sys.stdout.reconfigure(encoding="utf-8") if (
    sys.stdout.encoding or "").lower() not in ("utf-8", "utf8") else sys.stdout
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scen_tool

# control codes that consume one following argument byte
ARG_CODES = {0x04, 0x09}
CTRL_MAX = 0x0a  # bytes < 0x0a are control codes


def tokenize(raw):
    """Return list of tokens. Each token:
       ('text', str)        decoded SJIS/ASCII run
       ('ctrl', code, arg)  control code (arg=None if none)
       ('raw', byte)        undecodable byte (keeps losslessness)
    """
    toks = []
    i = 0
    n = len(raw)
    buf = bytearray()

    def flush():
        if buf:
            toks.append(("text", buf.decode("shift_jis", "surrogateescape")))
            buf.clear()

    while i < n:
        b = raw[i]
        if b < CTRL_MAX:
            flush()
            if b in ARG_CODES and i + 1 < n:
                toks.append(("ctrl", b, raw[i + 1]))
                i += 2
            else:
                toks.append(("ctrl", b, None))
                i += 1
        elif 0x81 <= b <= 0x9f or 0xe0 <= b <= 0xef:
            if i + 1 < n:
                buf += raw[i:i + 2]
                i += 2
            else:
                toks.append(("raw", b))
                i += 1
        elif 0x20 <= b < 0x7f or b in (0x0a, 0x0d):
            buf += raw[i:i + 1]
            i += 1
        else:
            # single high byte not a valid SJIS lead in-context; keep raw
            flush()
            toks.append(("raw", b))
            i += 1
    flush()
    return toks


def split_strings(raw):
    """Split a leaf into NUL-delimited byte strings (preserving empties)."""
    return raw.split(b"\x00")


def leaf_text_score(raw):
    """Fraction of NUL-delimited non-empty segments that decode as clean SJIS."""
    segs = [s for s in split_strings(raw) if s]
    if not segs:
        return 0.0, 0
    good = 0
    for s in segs:
        try:
            # a "clean" text segment: decodes and is mostly printable JP/ASCII
            txt = s.decode("shift_jis")
            printable = sum(1 for ch in txt if ch.isprintable() or ch in "\n\r")
            if printable / max(1, len(txt)) > 0.8:
                good += 1
        except Exception:
            pass
    return good / len(segs), len(segs)


# --- MTE dictionary (verified): per-block leaf at child path (block, 2, 4),
#     NUL-separated fragments; {04 XX} expands to entry index (XX - 1). ---
MTE_DICT_SUBPATH = (2, 4)


def get_block_dict(tree, block_idx):
    """Return list[bytes] of MTE fragments for top-level block `block_idx`."""
    node = tree.children[block_idx]
    for i in MTE_DICT_SUBPATH:
        if node.kind != "table" or i >= len(node.children):
            return None
        node = node.children[i]
    if node.kind != "leaf":
        return None
    return node.raw.split(b"\x00")


def expand_mte(raw, dict_entries):
    """Expand {04 XX} MTE codes in `raw` (bytes) using dict_entries (list[bytes]).
    Returns bytes with MTE codes replaced by their fragments (recursively, since
    fragments themselves are plain SJIS). Other control codes are preserved.

    ⛔ 세션22 버그 (66세그먼트 손상): **{09}의 인자 바이트가 0x04일 수 있다.**
    `09 04` = [NAME:04] = 주인공(플레이어 명명) 이름이고, 여기서 04는 MTE 코드가
    아니다. 예전 구현은 09를 건너뛰지 않고 그 인자 04를 MTE로 착각해 사전 항목
    (「光の末裔」·「あなたの」 등)을 본문에 끼워 넣었다 → 추출된 JP가
    `{09:8c}<f5>の末裔I` 처럼 깨졌고, 그 상태로 번역돼 게임에서 이름 자리에
    범위 밖 NAME 인덱스(0x8c=140 > 이름표 78개)가 들어가 엉뚱한 문자열이 떴다.
    ARG_CODES는 어떤 것이든 **인자를 통째로 넘겨야** 한다."""
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        b = raw[i]
        if b in ARG_CODES and b != 0x04 and i + 1 < n:
            out += raw[i:i + 2]          # 인자 바이트는 해석하지 않고 그대로
            i += 2
        elif b == 0x04 and i + 1 < n:
            idx = raw[i + 1] - 1
            if dict_entries and 0 <= idx < len(dict_entries):
                out += dict_entries[idx]
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


def analyze(name):
    with open(os.path.join(scen_tool_ORIG, name), "rb") as f:
        data = f.read()
    tree = scen_tool.parse(data)
    leaves = list(scen_tool.iter_leaves(tree))
    text_leaves = []
    ctrl_freq = {}
    mte_args = set()
    total_strings = 0
    for path, leaf in leaves:
        score, nseg = leaf_text_score(leaf.raw)
        if score >= 0.6 and nseg >= 2:
            text_leaves.append((path, leaf, nseg))
            total_strings += nseg
            for tok in tokenize(leaf.raw):
                if tok[0] == "ctrl":
                    ctrl_freq[tok[1]] = ctrl_freq.get(tok[1], 0) + 1
                    if tok[1] == 0x04 and tok[2] is not None:
                        mte_args.add(tok[2])
    print(f"\n=== {name} ===")
    print(f"leaves total={len(leaves)}  text-leaves={len(text_leaves)}  ~strings={total_strings:,}")
    print("control-code frequency (in text leaves):")
    for code in sorted(ctrl_freq):
        print(f"    {code:#04x} {'(arg)' if code in ARG_CODES else '     '}: {ctrl_freq[code]:,}")
    print(f"distinct {{04}} MTE indices used: {len(mte_args)}  (range {min(mte_args) if mte_args else '-'}..{max(mte_args) if mte_args else '-'})")
    return tree, text_leaves, mte_args


scen_tool_ORIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "original")

if __name__ == "__main__":
    analyze("LANG1_SCEN.DAT")
    analyze("LANG2_SCEN.DAT")
