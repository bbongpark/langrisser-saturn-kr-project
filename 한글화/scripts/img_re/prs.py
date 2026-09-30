#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sega PRS (LZ) decompressor variants + archive parsing for IMG.DAT."""
import struct

def parse_archive(data):
    n = struct.unpack(">I", data[:4])[0] // 4
    offs = [struct.unpack(">I", data[i*4:i*4+4])[0] for i in range(n)]
    offs.append(len(data))
    return [data[offs[i]:offs[i+1]] for i in range(n)]

def prs_decompress(data, skip=2, long_base=2, short_base=2, longsize_plus=1,
                   stop_on_zero=True, maxout=1<<20):
    """Canonical fuzziqer-style PRS. skip leading magic bytes (c0 01)."""
    out = bytearray()
    p = skip
    ctrl = 0; bits = 0
    def getbit():
        nonlocal ctrl, bits, p
        if bits == 0:
            ctrl = data[p]; p += 1; bits = 8
        b = ctrl & 1; ctrl >>= 1; bits -= 1
        return b
    try:
        while p < len(data) and len(out) < maxout:
            if getbit() == 1:
                out.append(data[p]); p += 1
                continue
            if getbit() == 1:
                # long
                a = data[p]; b = data[p+1]; p += 2
                if stop_on_zero and a == 0 and b == 0:
                    break
                offset = ((b << 8) | a) >> 3
                amount = a & 0x07
                if amount == 0:
                    amount = data[p] + longsize_plus; p += 1
                else:
                    amount = amount + long_base
                offset = offset - 0x2000
            else:
                # short: 2-bit size
                amount = (getbit() << 1) | getbit()
                amount += short_base
                offset = data[p] - 0x100; p += 1
            start = len(out) + offset
            for i in range(amount):
                if 0 <= start + i < len(out):
                    out.append(out[start + i])
                else:
                    out.append(0)
    except IndexError:
        pass
    return bytes(out), p

if __name__ == "__main__":
    import sys, io
    sys.stdout.reconfigure(encoding="utf-8")
    data = open("data/LANG2_IMG.DAT", "rb").read()
    res = parse_archive(data)
    print("resources:", len(res))
    # metric: how many consume input to within 8 bytes
    for (lb, sb, lp) in [(2,2,1),(3,3,1),(2,2,2),(3,2,1),(2,3,1)]:
        good = 0; sizes = []
        for r in res:
            if len(r) < 3: continue
            o, p = prs_decompress(r, long_base=lb, short_base=sb, longsize_plus=lp)
            if len(r) - p <= 8:
                good += 1
            sizes.append(len(o))
        print(f"lb={lb} sb={sb} lp={lp}: consumed_within8={good}/{len(res)} "
              f"mult32={sum(1 for s in sizes if s%32==0)}")
    # show res#4 (small) output head under best
    o, p = prs_decompress(res[4])
    print("res#4 outlen", len(o), "consumed", p, "of", len(res[4]))
    print("res#4 head:", o[:64].hex())
