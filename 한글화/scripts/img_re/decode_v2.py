#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decompressor reverse-engineered from LANG2.BIN SH-2 code (main loop 0x0601158c,
get_bit 0x0601138c MSB-first, get_nibble 0x06011460, get_byte 0x060113dc,
copy 0x060114f4). MSB-first bit-packed prefix-coded LZ."""
import struct

def parse(path):
    d=open(path,'rb').read()
    n=struct.unpack('>I',d[:4])[0]//4
    offs=[struct.unpack('>I',d[i*4:i*4+4])[0] for i in range(n)]; offs.append(len(d))
    return [d[offs[i]:offs[i+1]] for i in range(n)]

class Bits:
    def __init__(self,data,p=0):
        self.d=data; self.p=p; self.cur=0; self.cnt=8   # cnt==8 forces refill
    def bit(self):
        if self.cnt==8:
            self.cur=self.d[self.p]; self.p+=1; self.cnt=0
        b=(self.cur>>7)&1            # MSB-first
        self.cur=(self.cur<<1)&0xff
        self.cnt+=1
        return b
    def bits(self,n):
        v=0
        for _ in range(n): v=(v<<1)|self.bit()
        return v

def decode(data, skip=0, maxout=1<<20):
    br=Bits(data,skip)
    out=bytearray()
    def copy(dist,length):
        if dist==0: dist=256
        st=len(out)-dist
        for i in range(length):
            out.append(out[st+i] if 0<=st+i<len(out) else 0)
    try:
        while len(out)<maxout:
            if br.bit()==1:                       # LITERAL
                if br.bit()==1:                   # 11
                    out.append(br.bits(8))
                elif br.bit()==0:                 # 100
                    out.append(br.bits(4))
                else:                             # 101xx
                    if br.bit()==0:
                        out.append(0x10 if br.bit()==0 else 0x30)
                    else:
                        out.append(0x80 if br.bit()==0 else 0xFF)
            else:                                 # MATCH (0...)
                if br.bit()==0:   copy(br.bits(4) or 0x10, 1)     # 00
                elif br.bit()==0: copy(br.bits(4) or 0x10, 2)     # 010
                elif br.bit()==0: copy(br.bits(4) or 0x10, 3)     # 0110
                elif br.bit()==0: copy(br.bits(8), 2)             # 01110
                elif br.bit()==0: copy(br.bits(8), 3)             # 011110
                elif br.bit()==0: copy(br.bits(8), 4)             # 0111110
                elif br.bit()==0:                                 # 01111110 LONG
                    length=br.bits(4)+5; dist=br.bits(8); copy(dist,length)
                else:                                             # 01111111 END
                    break
    except IndexError:
        pass
    return bytes(out)

if __name__=="__main__":
    import sys,io
    sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
    V=open('data/vdp2vram.bin','rb').read()
    frame=V[0x20:0x60]
    res=parse('data/LANG2_IMG.DAT')
    hits=[]
    for skip in (0,2):
        for i,r in enumerate(res):
            if len(r)<4: continue
            try: o=decode(r,skip=skip,maxout=0x4000)
            except Exception: continue
            if frame[:16] in o:
                hits.append((i,skip,o.index(frame[:16]),len(o)))
                print('FRAME HIT res#%d skip%d @0x%x outlen=%d full=%s'%(i,skip,o.index(frame[:16]),len(o),frame in o))
    if not hits:
        print('no frame hit; sample res#4 skip0 head:',decode(res[4],0,64)[:48].hex())
        print('sample res#4 skip2 head:',decode(res[4],2,64)[:48].hex())
