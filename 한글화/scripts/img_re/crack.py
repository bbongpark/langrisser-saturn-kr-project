#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crack.py — brute-force the IMG.DAT LZSS parameters by matching a known
decompressed target (the menu window-frame tile) inside a resource's output."""
import io, sys, struct, itertools
sys.stdout.reconfigure(encoding="utf-8")

IMG = open("data/LANG2_IMG.DAT", "rb").read()
VRAM = open("data/vdp2vram.bin", "rb").read()
TARGET = bytes.fromhex("eeeee444eeeee443eeee4432eeee4321eee43232ee222122e222322332232232")
MAXOUT = 0x80          # frame is at output ~0x20; only decode the head for the search


def resources():
    n = struct.unpack(">I", IMG[:4])[0] // 4
    offs = [struct.unpack(">I", IMG[i*4:i*4+4])[0] for i in range(n)]
    offs.append(len(IMG))
    return [(i, IMG[offs[i]:offs[i+1]]) for i in range(n)]


def decode(data, flag_bits, order, lit_val, off_bits, len_bits, len_low,
           bo, thr, dist_base, skip):
    out = bytearray()
    p = skip
    flags = 0
    fc = 0
    try:
        while p < len(data) and len(out) < MAXOUT:
            if fc == 0:
                if flag_bits == 8:
                    flags = data[p]; p += 1; fc = 8
                else:
                    flags = (data[p] << 8) | data[p+1] if bo == "big" else data[p] | (data[p+1] << 8)
                    p += 2; fc = 16
            if order == "msb":
                bit = (flags >> (fc-1)) & 1
            else:
                bit = flags & 1; flags >>= 1
            fc -= 1
            if bit == lit_val:
                out.append(data[p]); p += 1
            else:
                w = (data[p] << 8) | data[p+1] if bo == "big" else data[p] | (data[p+1] << 8)
                p += 2
                if len_low:
                    length = (w & ((1 << len_bits)-1)) + thr
                    off = w >> len_bits
                else:
                    length = (w >> off_bits) + thr
                    off = w & ((1 << off_bits)-1)
                dist = off + dist_base
                for _ in range(length):
                    out.append(out[-dist] if 0 < dist <= len(out) else 0)
    except IndexError:
        pass
    return bytes(out)


def main():
    res = resources()
    found = []
    combos = list(itertools.product(
        [16, 8],              # flag_bits
        ["msb", "lsb"],       # order
        [0, 1],               # lit_val
        [(11, 5), (12, 4), (13, 3), (10, 6), (9, 7), (8, 8)],  # (off_bits,len_bits)
        [True, False],        # len_low
        ["big", "little"],    # byte order
        [0, 1, 2, 3],         # threshold
        [0, 1],               # dist_base
        [0, 2],               # skip leading bytes (0, or 2 for c0 01 header)
    ))
    print("combos:", len(combos), " resources:", len(res), flush=True)
    T8 = TARGET[:8]
    for ci, (fb, order, lit, (ob, lb), ll, bo, thr, db, skip) in enumerate(combos):
        for idx, r in res:
            o = decode(r, fb, order, lit, ob, lb, ll, bo, thr, db, skip)
            if T8 in o:                      # 8-byte frame prefix is already distinctive
                pos = o.index(T8)
                found.append((idx, fb, order, lit, ob, lb, ll, bo, thr, db, skip, pos))
                print("HIT res#%d fb=%d %s lit=%d off=%d len=%d low=%s %s thr=%d db=%d skip=%d @out0x%x head=%s"
                      % (idx, fb, order, lit, ob, lb, ll, bo, thr, db, skip, pos, o[:16].hex()), flush=True)
        if len(found) >= 6:
            break
    if not found:
        print("no match with 8B frame prefix.", flush=True)


if __name__ == "__main__":
    main()
