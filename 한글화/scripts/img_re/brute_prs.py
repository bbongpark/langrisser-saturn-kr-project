#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brute PRS-family params against the concrete vdp2vram target (blank+frame)."""
import struct, itertools
def parse(path):
    d=open(path,'rb').read()
    n=struct.unpack('>I',d[:4])[0]//4
    offs=[struct.unpack('>I',d[i*4:i*4+4])[0] for i in range(n)]; offs.append(len(d))
    return [d[offs[i]:offs[i+1]] for i in range(n)]

V=open('data/vdp2vram.bin','rb').read()
TARGETS={
 'blank+frame': V[0x00:0x60],   # 32 zero + frame
 'frame':       V[0x20:0x60],
}

def prs(data, skip, long_base, short_base, longsize_plus, order, litbit,
        shortcopy_is_00, off_short_base, maxout=4000):
    out=bytearray(); p=skip; ctrl=0; bits=0
    def gb():
        nonlocal ctrl,bits,p
        if bits==0: ctrl=data[p]; p+=1; bits=8
        if order=='lsb': b=ctrl&1; ctrl>>=1
        else: b=(ctrl>>7)&1; ctrl=(ctrl<<1)&0xff
        bits-=1; return b
    try:
        while p<len(data) and len(out)<maxout:
            if gb()==litbit:
                out.append(data[p]); p+=1; continue
            second=gb()
            is_short = (second==0) if shortcopy_is_00 else (second==1)
            if is_short:
                sz=((gb()<<1)|gb())+short_base
                off=data[p]-off_short_base; p+=1
            else:
                b0=data[p]; b1=data[p+1]; p+=2
                if b0==0 and b1==0: break
                off=(((b1<<8)|b0)>>3)|(~0x1fff)
                sz=b0&7
                if sz==0: sz=data[p]+longsize_plus; p+=1
                else: sz+=long_base
            st=len(out)+off
            for k in range(sz):
                out.append(out[st+k] if 0<=st+k<len(out) else 0)
    except IndexError: pass
    return bytes(out)

def main():
    res=parse('data/LANG2_IMG.DAT')
    space=list(itertools.product(
        [0,2],              # skip
        [2,3],              # long_base
        [2,3],              # short_base
        [1,0,2],            # longsize_plus
        ['lsb','msb'],      # order
        [1,0],              # litbit
        [True,False],       # shortcopy_is_00
        [0x100,0x101],      # off_short_base
    ))
    print('space',len(space),'res',len(res),flush=True)
    for tname,tv in TARGETS.items():
        t8=tv[:8]; hits=0
        for params in space:
            for i,r in enumerate(res):
                if len(r)<6: continue
                o=prs(r,*params)
                if t8 in o:
                    full = tv in o
                    print('HIT[%s] res#%d params=%s @0x%x full=%s'%(tname,i,params,o.index(t8),full),flush=True)
                    hits+=1
                    if hits>15: break
            if hits>15: break
        print('target %s hits=%d'%(tname,hits),flush=True)

if __name__=='__main__': main()
