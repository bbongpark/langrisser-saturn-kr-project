#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Try the TRUE Okumura LZSS (absolute ring positions, discontiguous pos/len)."""
import io, sys, struct, itertools
sys.stdout.reconfigure(encoding="utf-8")

def resources(path):
    d = open(path, "rb").read()
    n = struct.unpack(">I", d[:4])[0] // 4
    offs = [struct.unpack(">I", d[i*4:i*4+4])[0] for i in range(n)]
    offs.append(len(d))
    return [d[offs[i]:offs[i+1]] for i in range(n)]

def lzss(data, N=4096, F=18, THR=2, rinit=0, litbit=1, order='lsb',
         rpos_init=None, poslen='classic', maxout=None):
    if rpos_init is None:
        rpos_init = N - F
    ring = bytearray([rinit]) * N
    r = rpos_init
    out = bytearray()
    p = 0
    flags = 0
    fcnt = 0
    try:
        while p < len(data):
            if maxout and len(out) >= maxout:
                break
            if fcnt == 0:
                flags = data[p]; p += 1; fcnt = 8
            if order == 'lsb':
                bit = flags & 1; flags >>= 1
            else:
                bit = (flags >> 7) & 1; flags = (flags << 1) & 0xff
            fcnt -= 1
            if bit == litbit:
                c = data[p]; p += 1
                out.append(c); ring[r] = c; r = (r + 1) & (N - 1)
            else:
                b0 = data[p]; b1 = data[p+1]; p += 2
                if poslen == 'classic':      # pos = b0 | (b1>>4)<<8 ; len=b1&0xf
                    pos = b0 | ((b1 & 0xf0) << 4)
                    length = (b1 & 0x0f) + THR + 1
                elif poslen == 'classic_swap':  # b1 low byte, b0 high nibble
                    pos = b1 | ((b0 & 0xf0) << 4)
                    length = (b0 & 0x0f) + THR + 1
                elif poslen == 'lenhi':      # len in high nibble of b1
                    pos = b0 | ((b1 & 0x0f) << 8)
                    length = ((b1 & 0xf0) >> 4) + THR + 1
                for k in range(length):
                    c = ring[(pos + k) & (N - 1)]
                    out.append(c); ring[r] = c; r = (r + 1) & (N - 1)
    except IndexError:
        pass
    return bytes(out)

TARGET = bytes.fromhex("eeeee444eeeee443eeee4432eeee4321")

def main():
    for path in ["data/LANG2_IMG.DAT", "data/LANG1_IMG.DAT"]:
        res = resources(path)
        print(f"== {path}: {len(res)} resources", flush=True)
        # First just decode resource 0..3 with the plain classic and print head
        for ri in [0,1,2,3,4]:
            o = lzss(res[ri], maxout=96)
            print(f"  res#{ri} classic head: {o[:48].hex()}  outlen~{len(o)}", flush=True)
        # Now scan for TARGET across param space
        hits = 0
        for litbit, order, THR, rinit, poslen, rpos in itertools.product(
                [0,1], ['lsb','msb'], [1,2,3], [0,0x20],
                ['classic','classic_swap','lenhi'], [4078, 4096-18, 0, 1]):
            for ri, r in enumerate(res):
                o = lzss(r, THR=THR, rinit=rinit, litbit=litbit, order=order,
                         poslen=poslen, rpos_init=rpos, maxout=0x80)
                if TARGET in o:
                    print(f"  HIT res#{ri} lit={litbit} {order} THR={THR} rinit={rinit:#x} "
                          f"{poslen} rpos={rpos} @0x{o.index(TARGET):x} head={o[:8].hex()}", flush=True)
                    hits += 1
                    if hits > 12:
                        return
        if hits == 0:
            print("  no TARGET hit", flush=True)

if __name__ == "__main__":
    main()
