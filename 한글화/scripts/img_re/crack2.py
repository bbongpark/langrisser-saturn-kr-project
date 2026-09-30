#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crack2.py — control-byte compression families (each token = control byte + data)."""
import io, sys, struct, itertools
sys.stdout.reconfigure(encoding="utf-8")

TARGET = bytes.fromhex("eeeee444eeeee443eeee4432eeee4321")   # 16B frame prefix
MAXOUT = 0x100


def resources(path):
    d = open(path, "rb").read()
    n = struct.unpack(">I", d[:4])[0] // 4
    offs = [struct.unpack(">I", d[i*4:i*4+4])[0] for i in range(n)]
    offs.append(len(d))
    return [(i, d[offs[i]:offs[i+1]]) for i in range(n)]


def dec_ctrl(data, skip, lit_hi, lit_cnt_plus, ob, lb, len_hi, bo, thr, db):
    """Control-byte scheme: read C. If (C>=0x80)==lit_hi -> literal run of
    (C&0x7f)+lit_cnt_plus bytes; else -> back-ref from a 2-byte token (C is byte0)."""
    out = bytearray()
    p = skip
    try:
        while p < len(data) and len(out) < MAXOUT:
            c = data[p]; p += 1
            is_lit = ((c >= 0x80) == lit_hi)
            if is_lit:
                n = (c & 0x7f) + lit_cnt_plus
                for _ in range(n):
                    out.append(data[p]); p += 1
            else:
                w = (c << 8) | data[p] if bo == "big" else c | (data[p] << 8)
                p += 1
                if len_hi:
                    length = (w >> ob) & ((1 << lb)-1); off = w & ((1 << ob)-1)
                else:
                    off = (w >> lb) & ((1 << ob)-1); length = w & ((1 << lb)-1)
                length += thr
                dist = off + db
                for _ in range(length):
                    out.append(out[-dist] if 0 < dist <= len(out) else 0)
    except IndexError:
        pass
    return bytes(out)


def main():
    combos = list(itertools.product(
        [0, 2],                 # skip
        [True, False],          # lit_hi (high bit => literal?)
        [0, 1],                 # lit_cnt_plus
        [(11, 4), (12, 3), (10, 5), (13, 2), (9, 6)],  # (off_bits, len_bits) within 15-bit token
        [True, False],          # len_hi (length in high bits of token)
        ["big", "little"],      # byte order
        [0, 1, 2, 3],           # threshold
        [0, 1],                 # dist base
    ))
    for path in ["data/LANG2_IMG.DAT", "data/LANG1_IMG.DAT"]:
        res = resources(path)
        print(f"== {path}: {len(res)} res x {len(combos)} combos", flush=True)
        for (skip, lh, lcp, (ob, lb), lenhi, bo, thr, db) in combos:
            for idx, r in res:
                o = dec_ctrl(r, skip, lh, lcp, ob, lb, lenhi, bo, thr, db)
                if TARGET in o:
                    print("HIT %s res#%d skip=%d lit_hi=%s lcp=%d off=%d len=%d lenhi=%s %s thr=%d db=%d @0x%x head=%s"
                          % (path, idx, skip, lh, lcp, ob, lb, lenhi, bo, thr, db, o.index(TARGET), o[:24].hex()), flush=True)
                    return
    print("no control-byte match.", flush=True)


if __name__ == "__main__":
    main()
