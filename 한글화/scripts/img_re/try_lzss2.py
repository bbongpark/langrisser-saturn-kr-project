#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io, sys, struct, itertools
sys.stdout.reconfigure(encoding="utf-8")
from try_lzss import resources, lzss

TARGET = bytes.fromhex("eeeee444eeeee443eeee4432eeee4321")

def nib_swap(b):
    return bytes(((x & 0x0f) << 4) | (x >> 4) for x in b)

def main():
    for path in ["data/LANG2_IMG.DAT", "data/LANG1_IMG.DAT"]:
        res = resources(path)
        # decode all fully with plain classic
        outs = [lzss(r) for r in res]
        print(f"== {path}", flush=True)
        print("  sizes decoded (first 8):", [len(o) for o in outs[:8]])
        print("  all multiple of 32?:", all(len(o)%32==0 for o in outs if len(o)>0))
        print("  non-mult-of-32 count:", sum(1 for o in outs if len(o)%32!=0))
        # search TARGET and variants across all outputs
        variants = {'plain': lambda b:b, 'nibswap': nib_swap}
        for vname, vf in variants.items():
            t = vf(TARGET)
            for i,o in enumerate(outs):
                oo = vf(o) if False else o
                if t in o:
                    print(f"  HIT[{vname}] res#{i} @0x{o.index(t):x} outlen={len(o)}", flush=True)
        # also print res#0 full head
        print("  res#0 full first 160:", outs[0][:160].hex())
        print("  res#0 len", len(outs[0]))

if __name__=="__main__":
    main()
