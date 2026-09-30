#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IMG.DAT codec for Langrisser I&II Dramatic Edition (Sega Saturn).

STATUS (2026-07-14): SOLVED & VALIDATED.
  * CONTAINER   — parse_archive / build_archive, lossless round-trip on both
    LANG1_IMG.DAT and LANG2_IMG.DAT.
  * DECOMPRESS  — custom MSB-first prefix-LZ, reverse-engineered from the LANG2.BIN
    SH-2 decompressor (see FORMAT.md for the full function map). VALIDATED against
    a live VDP2 VRAM capture: each resource decompresses to a 0x2000-byte VRAM
    char bank and matches the ground-truth dump byte-for-byte (res#1/5/6/27 = 100%,
    res#0 = 99.5%; the few misses are VRAM tiles overwritten after the capture).
    The earlier "PRS" hypothesis was DISPROVEN — the codec is MSB-first, not PRS's
    LSB-first, which is why every PRS variant failed.
  * COMPRESS    — MSB-first bit-writer inverse. Lossless: decompress(compress(x)) == x
    for all 233 LANG2 resource payloads. Greedy matcher; output ~105% of the original
    compressed size (growth absorbed by rebuilding the offset table in build_archive).

VRAM layout: resource i decompresses into VDP2 VRAM char-data bank at 0x20000 + i*0x2000
(observed order in the captured menu scene: res0->0x20000, res5->0x22000, res6->0x24000,
res1->0x26000, res27->0x28000, ...). Menu-label glyph tiles (兵士配属 등) live in these
banks; exact per-label resource index is a rendering/visual-ID step (next phase).
"""
import struct

# --------------------------------------------------------------------------
# Container  (VALIDATED — lossless round-trip on LANG1 & LANG2)
# --------------------------------------------------------------------------

def parse_archive(buf: bytes):
    """Split IMG.DAT into its resource byte-strings.

    Layout: big-endian u32 offset table at the head. u32[0] = table byte size,
    so entry count = u32[0] // 4. entry[i] = file offset of resource i.
    resource i = buf[off[i] : off[i+1]) (last resource ends at len(buf)).
    """
    n = struct.unpack(">I", buf[:4])[0] // 4
    offs = [struct.unpack(">I", buf[i * 4:i * 4 + 4])[0] for i in range(n)]
    offs.append(len(buf))
    return [buf[offs[i]:offs[i + 1]] for i in range(n)]


def build_archive(resources) -> bytes:
    """Inverse of parse_archive. Rebuilds the offset table + payload.
    build_archive(parse_archive(x)) == x for both game archives. Recomputes the
    offset table, so resources may change size (e.g. after re-compress)."""
    n = len(resources)
    tbl = bytearray()
    cur = n * 4
    for r in resources:
        tbl += struct.pack(">I", cur)
        cur += len(r)
    return bytes(tbl) + b"".join(resources)


# --------------------------------------------------------------------------
# Decompression  (VALIDATED vs live VDP2 VRAM — see module docstring / FORMAT.md)
# --------------------------------------------------------------------------
# Reverse-engineered directly from the LANG2.BIN SH-2 decompressor:
#   main loop   0x0601158c     get_bit  0x0601138c  (MSB-first: test 0x80, shift left,
#   get_byte    0x060113dc                           refill @ bitcount==8)
#   get_nibble  0x06011460     short-copy 0x06011534 (dist=nibble, 0=>16; len 1..3)
#   byte-copy   0x06011564 (dist=byte, 0=>256; len 2..4)
#   long        (len=nibble+5, dist=byte)            copy prim 0x060114f4 (overlapping)
# The `c0 01` header IS part of the bitstream (decode from offset 0; skip stays 0).

def decompress(resource: bytes, skip: int = 0) -> bytes:
    d = resource
    p = skip
    cur = 0
    cnt = 8                       # forces refill on first bit

    def bit():
        nonlocal cur, cnt, p
        if cnt == 8:
            cur = d[p]; p += 1; cnt = 0
        b = (cur >> 7) & 1        # MSB-first
        cur = (cur << 1) & 0xff
        cnt += 1
        return b

    def nbits(n):
        v = 0
        for _ in range(n):
            v = (v << 1) | bit()
        return v

    out = bytearray()

    def copy(dist, length):
        if dist == 0:
            dist = 256
        st = len(out) - dist
        for i in range(length):
            out.append(out[st + i] if 0 <= st + i < len(out) else 0)

    try:
        while p < len(d):
            if bit() == 1:                                # LITERAL
                if bit() == 1:                            # 11
                    out.append(nbits(8))
                elif bit() == 0:                          # 100
                    out.append(nbits(4))
                else:                                     # 101xx  common bytes
                    if bit() == 0:
                        out.append(0x10 if bit() == 0 else 0x30)
                    else:
                        out.append(0x80 if bit() == 0 else 0xFF)
            else:                                         # MATCH  (0...)
                if bit() == 0:   copy(nbits(4) or 0x10, 1)       # 00
                elif bit() == 0: copy(nbits(4) or 0x10, 2)       # 010
                elif bit() == 0: copy(nbits(4) or 0x10, 3)       # 0110
                elif bit() == 0: copy(nbits(8), 2)               # 01110
                elif bit() == 0: copy(nbits(8), 3)               # 011110
                elif bit() == 0: copy(nbits(8), 4)               # 0111110
                elif bit() == 0:                                 # 01111110 long
                    length = nbits(4) + 5; copy(nbits(8), length)
                else:                                            # 01111111 END
                    break
    except IndexError:
        pass
    return bytes(out)


# --------------------------------------------------------------------------
# Compression  (MSB-first bit-writer inverse of decompress; lossless)
# --------------------------------------------------------------------------
# Token costs (bits): literal 0x10/0x30/0x80/0xFF=5, nibble(<=0x0F)=7, byte=10;
# match short(len1..3,dist1..16)=6/7/8, byte(len2..4,dist1..256)=13/14/15,
# long(len5..20,dist1..256)=20. Greedy longest-match against the raw buffer
# (overlapping copies validate as raw[i+k]==raw[i+k-d]).

_SPECIAL = {0x10: 0b10100, 0x30: 0b10101, 0x80: 0b10110, 0xFF: 0b10111}


def compress(raw: bytes, type_byte: int = 0x01) -> bytes:
    """Encode `raw` into a game-decodable bitstream. Lossless: decompress(compress(x)) == x.
    `type_byte` is unused for correctness (the header is part of the bitstream); kept for
    API symmetry. Output length may exceed the original compressed size; build_archive
    recomputes the offset table to absorb it."""
    bits = []

    def put(v, n):
        for i in range(n - 1, -1, -1):
            bits.append((v >> i) & 1)

    n = len(raw)
    i = 0
    while i < n:
        best_L = 0
        best_d = 0
        maxd = min(i, 256)
        for d in range(1, maxd + 1):
            L = 0
            while L < 20 and i + L < n and raw[i + L] == raw[i + L - d]:
                L += 1
            if L > best_L:
                best_L = L
                best_d = d
                if L == 20:
                    break
        d = best_d
        L = best_L
        # a length-1 copy needs dist<=16; a >=2 copy with dist>16 uses the byte forms
        usable = L if (d <= 16 or L >= 2) else 0
        if usable >= 2:
            L = usable
            if L >= 5:
                put(0b01111110, 8); put(L - 5, 4); put(d & 0xff, 8)
            elif L == 4:
                put(0b0111110, 7); put(d & 0xff, 8)
            elif L == 3:
                if d <= 16: put(0b0110, 4); put(d & 0xf, 4)
                else:       put(0b011110, 6); put(d & 0xff, 8)
            else:  # L == 2
                if d <= 16: put(0b010, 3); put(d & 0xf, 4)
                else:       put(0b01110, 5); put(d & 0xff, 8)
            i += L
            continue
        # literal
        b = raw[i]
        if b in _SPECIAL:   put(_SPECIAL[b], 5)
        elif b <= 0x0F:     put(0b100, 3); put(b, 4)
        else:               put(0b11, 2); put(b, 8)
        i += 1

    put(0b01111111, 8)  # END token
    while len(bits) % 8:
        bits.append(0)
    body = bytearray()
    for k in range(0, len(bits), 8):
        v = 0
        for j in range(8):
            v = (v << 1) | bits[k + j]
        body.append(v)
    return bytes(body)


# --------------------------------------------------------------------------
# Optimal-parse compression (2026-07-17): shortest-path DP over the token set.
# Purpose: the greedy encoder outputs ~105% of the game's original size; the
# optimal parser beats the original (~-4%), and the reclaimed bytes become
# zero PADDING at the end of the rebuilt archive (file size is kept constant
# on disc). That padding slack hosts the 8px-HUD Korean tile blob (HANDOFF).
# Same bitstream format — decompress() round-trip verified for every resource.
# --------------------------------------------------------------------------

def compress_optimal(raw: bytes) -> bytes:
    """Bit-optimal encoding of `raw` for decompress(). Costs (bits):
    literal 5/7/10; len1 d<=16: 6; len2 d<=16/256: 7/13; len3: 8/14;
    len4 d<=256: 15; len5..20 d<=256: 20."""
    import numpy as np
    n = len(raw)
    if n == 0:
        return compress(raw)
    a = np.frombuffer(raw, dtype=np.uint8)
    idx = np.arange(n)
    INF = 1 << 30
    # per-position best match lengths (capped 20) + a dist achieving them
    max_s = np.zeros(n, dtype=np.int32)   # dist <= 16
    dist_s = np.zeros(n, dtype=np.int32)
    max_l = np.zeros(n, dtype=np.int32)   # dist <= 256
    dist_l = np.zeros(n, dtype=np.int32)
    for d in range(1, min(256, n) + 1):
        eq = np.zeros(n, dtype=bool)
        eq[d:] = a[d:] == a[:-d]
        nf = np.where(eq, n, idx)                       # next-false index
        nf = np.minimum.accumulate(nf[::-1])[::-1]
        run = np.minimum(nf - idx, 20).astype(np.int32)
        upd = run > max_l
        max_l[upd] = run[upd]
        dist_l[upd] = d
        if d <= 16:
            upd = run > max_s
            max_s[upd] = run[upd]
            dist_s[upd] = d
    lit_cost = np.full(256, 10, dtype=np.int32)
    lit_cost[:0x10] = 7
    for b in _SPECIAL:
        lit_cost[b] = 5
    # DP (backward): cost[i] = best bits to encode raw[i:]
    cost = np.full(n + 1, INF, dtype=np.int64)
    cost[n] = 0
    choice = np.zeros(n, dtype=np.int64)   # packed: L<<16 | kind(0=lit,1=short,2=long)
    lc = lit_cost[a]
    ms, ml = max_s, max_l
    cost_np, choice_np = cost, choice
    for i in range(n - 1, -1, -1):
        best = lc[i] + cost_np[i + 1]
        ch = (1 << 16) | 0
        s, l = ms[i], ml[i]
        if s >= 1:
            c = 6 + cost_np[i + 1]
            if c < best: best, ch = c, (1 << 16) | 1
        if s >= 2:
            c = 7 + cost_np[i + 2]
            if c < best: best, ch = c, (2 << 16) | 1
        if s >= 3:
            c = 8 + cost_np[i + 3]
            if c < best: best, ch = c, (3 << 16) | 1
        if l >= 2:
            c = 13 + cost_np[i + 2]
            if c < best: best, ch = c, (2 << 16) | 2
        if l >= 3:
            c = 14 + cost_np[i + 3]
            if c < best: best, ch = c, (3 << 16) | 2
        if l >= 4:
            c = 15 + cost_np[i + 4]
            if c < best: best, ch = c, (4 << 16) | 2
        if l >= 5:
            sub = cost_np[i + 5:i + l + 1]
            j = int(np.argmin(sub))
            c = 20 + int(sub[j])
            if c < best: best, ch = c, ((j + 5) << 16) | 2
        cost_np[i] = best
        choice_np[i] = ch
    # emit
    bits = []
    def put(v, nb):
        for k in range(nb - 1, -1, -1):
            bits.append((v >> k) & 1)
    i = 0
    while i < n:
        ch = int(choice_np[i])
        L, kind = ch >> 16, ch & 0xFFFF
        if kind == 0:
            b = raw[i]
            if b in _SPECIAL:   put(_SPECIAL[b], 5)
            elif b <= 0x0F:     put(0b100, 3); put(b, 4)
            else:               put(0b11, 2); put(b, 8)
        elif kind == 1:
            d = int(dist_s[i])
            if L == 1:   put(0b00, 2); put(d & 0xF, 4)
            elif L == 2: put(0b010, 3); put(d & 0xF, 4)
            else:        put(0b0110, 4); put(d & 0xF, 4)
        else:
            d = int(dist_l[i])
            if L == 2:   put(0b01110, 5); put(d & 0xFF, 8)
            elif L == 3: put(0b011110, 6); put(d & 0xFF, 8)
            elif L == 4: put(0b0111110, 7); put(d & 0xFF, 8)
            else:        put(0b01111110, 8); put(L - 5, 4); put(d & 0xFF, 8)
        i += L
    put(0b01111111, 8)
    while len(bits) % 8:
        bits.append(0)
    body = bytearray()
    for k in range(0, len(bits), 8):
        v = 0
        for j in range(8):
            v = (v << 1) | bits[k + j]
        body.append(v)
    return bytes(body)


if __name__ == "__main__":
    import sys, io
    sys.stdout.reconfigure(encoding="utf-8")
    for path in ("data/LANG2_IMG.DAT", "data/LANG1_IMG.DAT"):
        buf = open(path, "rb").read()
        res = parse_archive(buf)
        assert build_archive(res) == buf, "CONTAINER ROUND-TRIP FAILED: " + path
        ok = rt = errs = 0
        osz = nsz = 0
        for r in res:
            if len(r) < 3:
                continue
            rt += 1
            try:
                raw = decompress(r)
                comp = compress(raw)
                if decompress(comp) == raw:
                    ok += 1
                osz += len(r); nsz += len(comp)
            except Exception:
                errs += 1
        print(f"{path}: {len(res)} resources | container OK | "
              f"compress round-trip {ok}/{rt} | errors={errs} | "
              f"recompress size {100*nsz/osz:.1f}%")
    # VRAM ground-truth spot-check (LANG2 menu banks)
    try:
        V = open("data/vdp2vram.bin", "rb").read()
        res = parse_archive(open("data/LANG2_IMG.DAT", "rb").read())
        checks = []
        for i in (1, 5, 6, 27):
            o = decompress(res[i])
            # anchor to VRAM
            for k in range(len(o) - 32):
                w = o[k:k + 32]
                if w.count(0) < 24:
                    idx = V.find(w)
                    if idx >= 0:
                        base = idx - k
                        lo, hi = max(0, -base), min(len(o), len(V) - base)
                        same = sum(1 for j in range(lo, hi) if o[j] == V[base + j])
                        checks.append(f"res#{i}->V@0x{base:x} {100*same/(hi-lo):.1f}%")
                        break
        print("VRAM ground-truth:", " | ".join(checks))
    except FileNotFoundError:
        pass
