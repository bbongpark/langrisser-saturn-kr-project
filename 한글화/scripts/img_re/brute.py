#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import struct, itertools, sys
def resources(path):
    d=open(path,'rb').read()
    n=struct.unpack('>I',d[:4])[0]//4
    offs=[struct.unpack('>I',d[i*4:i*4+4])[0] for i in range(n)]
    offs.append(len(d))
    return [d[offs[i]:offs[i+1]] for i in range(n)]

TARGET=bytes.fromhex('eeeee444eeeee443eeee4432eeee4321')
def nib(b): return bytes(((x&0x0f)<<4)|(x>>4) for x in b)
def bsw(b): return bytes(b[i^1] for i in range(len(b)-len(b)%2))
TVARIANTS={'plain':TARGET,'nib':nib(TARGET),'bsw':bsw(TARGET),'nibbsw':bsw(nib(TARGET))}

def decode(data, litbit, order, THR, layout, mode, N=4096, maxout=6000):
    ring=bytearray(N); r=N-18; out=bytearray(); p=0; flags=0; fcnt=0
    try:
        while p<len(data) and len(out)<maxout:
            if fcnt==0: flags=data[p]; p+=1; fcnt=8
            if order=='lsb': bit=flags&1; flags>>=1
            else: bit=(flags>>7)&1; flags=(flags<<1)&0xff
            fcnt-=1
            if bit==litbit:
                c=data[p]; p+=1; out.append(c)
                if mode=='ring': ring[r]=c; r=(r+1)&(N-1)
            else:
                b0=data[p]; b1=data[p+1]; p+=2
                if layout=='A':   pos=b0|((b1&0xf0)<<4); length=(b1&0x0f)+THR+1
                elif layout=='B': pos=b0|((b1&0x0f)<<8); length=((b1&0xf0)>>4)+THR+1
                elif layout=='C': pos=b1|((b0&0xf0)<<4); length=(b0&0x0f)+THR+1
                elif layout=='D': pos=b1|((b0&0x0f)<<8); length=((b0&0xf0)>>4)+THR+1
                elif layout=='E': pos=(b0<<4)|(b1>>4); length=(b1&0x0f)+THR+1  # 12hi,4lo
                elif layout=='F': length=(b0>>4)+THR+1; pos=((b0&0x0f)<<8)|b1  # 4hi,12lo
                if mode=='ring':
                    for k in range(length):
                        c=ring[(pos+k)&(N-1)]; out.append(c); ring[r]=c; r=(r+1)&(N-1)
                else: # relative distance back
                    dist=pos+1
                    for k in range(length):
                        c=out[-dist] if dist<=len(out) else 0
                        out.append(c)
    except IndexError: pass
    return bytes(out)

def main():
    res=resources('data/LANG2_IMG.DAT')
    combos=list(itertools.product([0,1],['lsb','msb'],[0,1,2,3],
                ['A','B','C','D','E','F'],['ring','rel']))
    print('combos',len(combos),'res',len(res),flush=True)
    hits=0
    for (lb,order,THR,layout,mode) in combos:
        for i,r in enumerate(res):
            o=decode(r,lb,order,THR,layout,mode)
            for tname,tv in TVARIANTS.items():
                if tv[:8] in o:
                    print('HIT[%s] res#%d lit=%d %s THR=%d layout=%s %s @0x%x full=%s outlen=%d'
                          %(tname,i,lb,order,THR,layout,mode,o.index(tv[:8]),tv in o,len(o)),flush=True)
                    hits+=1
                    if hits>30: return
    if hits==0: print('NO T8 HIT anywhere',flush=True)

if __name__=='__main__': main()
