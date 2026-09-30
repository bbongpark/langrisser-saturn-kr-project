import struct

d=open('data/LANG2_IMG.DAT','rb').read()
n=struct.unpack('>I',d[:4])[0]//4
offs=[struct.unpack('>I', d[i*4:i*4+4])[0] for i in range(n)]
def res(i): return d[offs[i]:offs[i+1] if i+1<n else len(d)]
ref=open('data/vdp2vram.bin','rb').read()[:64]

def decode_byte_aligned(data, params, outlen):
    (flagsize, flagorder, litval, u16order, lenlow, lenbits,
     thr, distmode, ringN) = params
    offbits=16-lenbits
    p=0
    flags=0; fcount=0
    out=bytearray()
    ring=bytearray(ringN)
    rpos=ringN - 18  # classic init; may not matter for distmode rel
    def getflag():
        nonlocal flags,fcount,p
        if fcount==0:
            if flagsize==8:
                flags=data[p]; p+=1; fcount=8
            else:
                flags=(data[p]<<8)|data[p+1]; p+=2; fcount=16
        if flagorder=='msb':
            fcount-=1
            b=(flags>>fcount)&1
        else:
            b=flags&1; flags>>=1; fcount-=1
        return b
    try:
        while len(out)<outlen:
            f=getflag()
            if f==litval:
                out.append(data[p]); p+=1
            else:
                b0=data[p]; b1=data[p+1]; p+=2
                if u16order=='big': w=(b0<<8)|b1
                else: w=(b1<<8)|b0
                if lenlow:
                    length=(w&((1<<lenbits)-1))+thr
                    offv=w>>lenbits
                else:
                    length=(w>>offbits)+thr
                    offv=w&((1<<offbits)-1)
                if distmode=='rel':
                    dist=offv+1
                    for _ in range(length):
                        if dist>len(out): out.append(0)
                        else: out.append(out[len(out)-dist])
                elif distmode=='ring':
                    for _ in range(length):
                        c=ring[offv & (ringN-1)]
                        out.append(c)
                        ring[rpos]=c; rpos=(rpos+1)&(ringN-1)
                        offv+=1
        return bytes(out[:outlen])
    except (IndexError,):
        return None

resources_to_try=[0,1,2,3,4,6,7,8,10,13,15,16,17]
best=None; bestlen=0
found=[]
import itertools
for flagsize in [8,16]:
 for flagorder in ['msb','lsb']:
  for litval in [0,1]:
   for u16order in ['big','little']:
    for lenlow in [True,False]:
     for lenbits in [3,4,5]:
      for thr in [1,2,3]:
       for distmode in ['rel','ring']:
        for ringN in ([4096] if distmode=='ring' else [0]):
         params=(flagsize,flagorder,litval,u16order,lenlow,lenbits,thr,distmode,ringN)
         for ri in resources_to_try:
           o=decode_byte_aligned(res(ri),params,64)
           if o is None: continue
           # measure match length with ref
           m=0
           for a,b in zip(o,ref):
             if a==b: m+=1
             else: break
           if m>bestlen:
             bestlen=m; best=(ri,params,o.hex())
           if m>=48:
             found.append((ri,params,o[:16].hex(),m))
print('best partial match len:',bestlen)
print('best:',best)
print('found>=48:',len(found))
for f in found[:20]: print(f)
