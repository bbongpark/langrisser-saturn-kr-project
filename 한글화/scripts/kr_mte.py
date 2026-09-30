#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kr_mte.py — Korean MTE (dictionary) compression for budget-tight SCEN blocks.

Problem (measured): the original Japanese script is MTE-compressed — each top-level
block has a fragment dictionary leaf at (block,2,4), and {04 XX} in text expands to
dict entry XX-1. Rewriting a block as LITERAL Korean removes that compression, and
~27/108 L2 blocks then overflow their padding (alignment-preserving budget).

Solution: give KOREAN its own MTE dictionary. Frequent Korean fragments (encoded as
font-slot bytes) are stored in the block's (block,2,4) leaf; the Korean text
references them with {04 idx} codes. The game's {04} decoder is a plain inline byte
substitution (same as scen_text.expand_mte), so it inserts the Korean fragment bytes
verbatim — they render as Korean exactly like literal text, but cost 2 bytes ({04 idx})
instead of the fragment's full length.

API:
  build_kr_dict(encoded_texts, max_entries=239, min_len=4, min_count=2)
      -> list[bytes]   (fragment byte sequences, most-savings first)
  compress(encoded, kr_dict) -> bytes   (greedy {04 idx} substitution)
  Round-trip: expand_mte(compress(x, d), d) == x   (verified in selftest)

`encoded_*` are already font-slot-encoded byte strings (kr_encoding.encode_text output),
so fragments are whole 2-byte units. Index note: {04 XX} -> dict[XX-1], and XX is a
single byte 1..255, so at most 255 entries and no fragment may contain a 0x00 or a
control byte < 0x0a.
"""
import sys, io
from collections import Counter

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

MTE = 0x04
CTRL_MAX = 0x0a


def _safe_fragment(frag):
    """A dict fragment must not contain NUL (leaf separator) or control codes."""
    return frag and all(b >= CTRL_MAX for b in frag)


def build_kr_dict(encoded_texts, max_entries=239, min_len=4, min_count=2,
                  frag_syllables=(2, 3, 4)):
    """Pick high-savings Korean fragments from encoded texts.

    encoded_texts: iterable of font-slot-encoded byte strings (2 bytes/syllable).
    Returns list[bytes] (fragments), best savings first. Savings of a fragment =
    (len-2) * count  (each use replaces `len` bytes with a 2-byte {04 idx})."""
    counts = Counter()
    for enc in encoded_texts:
        n = len(enc)
        for slen in (2 * s for s in frag_syllables):   # fragment byte lengths
            if slen < min_len:
                continue
            for i in range(0, n - slen + 1, 2):         # 2-byte aligned
                frag = enc[i:i + slen]
                if _safe_fragment(frag):
                    counts[frag] += 1
    scored = []
    for frag, c in counts.items():
        if c >= min_count:
            scored.append(((len(frag) - 2) * c, frag))
    scored.sort(reverse=True)
    return [frag for _, frag in scored[:max_entries]]


def compress(encoded, kr_dict):
    """Greedy longest-first {04 idx} substitution over an encoded byte string."""
    # index fragments by first 2 bytes, longest first, for greedy matching
    by_lead = {}
    for idx, frag in enumerate(kr_dict):
        by_lead.setdefault(frag[:2], []).append((idx, frag))
    for lead in by_lead:
        by_lead[lead].sort(key=lambda t: -len(t[1]))
    out = bytearray()
    i = 0
    n = len(encoded)
    while i < n:
        b = encoded[i]
        if b < CTRL_MAX:                # control code: copy (with its arg if any)
            out.append(b)
            if b in (MTE, 0x09) and i + 1 < n:
                out.append(encoded[i + 1]); i += 2
            else:
                i += 1
            continue
        matched = False
        for idx, frag in by_lead.get(encoded[i:i + 2], ()):
            if encoded[i:i + len(frag)] == frag:
                out += bytes([MTE, idx + 1])   # {04 idx+1}
                i += len(frag)
                matched = True
                break
        if not matched:
            out += encoded[i:i + 2]            # copy one 2-byte unit
            i += 2
    return bytes(out)


def expand(encoded, kr_dict):
    """Inverse of compress (mirrors the game's {04} decoder)."""
    out = bytearray()
    i = 0
    n = len(encoded)
    while i < n:
        b = encoded[i]
        if b == MTE and i + 1 < n:
            out += kr_dict[encoded[i + 1] - 1]
            i += 2
        elif b == 0x09 and i + 1 < n:
            out += encoded[i:i + 2]; i += 2
        elif b < CTRL_MAX:
            out.append(b); i += 1
        else:
            out += encoded[i:i + 2]; i += 2
    return bytes(out)


def _selftest():
    # synthetic: encoded Korean as 2-byte units (use kanji-slot-like codes 0x88xx)
    def enc(s):  # map each 'syllable char' to a fake 2-byte slot code
        return b"".join(bytes([0x88, 0x40 + ord(c) % 0x40]) for c in s)
    texts = [enc("빛의여신입니다"), enc("빛의여신이여"), enc("여신의가호"),
             enc("입니다그리고입니다")]
    d = build_kr_dict(texts, min_count=2, min_len=4)
    assert d, "no fragments found"
    # round-trip every text
    for t in texts:
        c = compress(t, d)
        assert expand(c, d) == t, "round-trip mismatch"
        assert len(c) <= len(t), "compression grew the text"
    # at least one text actually compressed
    assert any(len(compress(t, d)) < len(t) for t in texts), "no compression happened"
    print(f"kr_mte selftest OK — {len(d)} fragments, "
          f"e.g. saves on repeated 여신/입니다")


if __name__ == "__main__":
    _selftest()
