import struct
d=open('data/LANG2_IMG.DAT','rb').read()
n=struct.unpack('>I',d[:4])[0]//4
offs=[struct.unpack('>I', d[i*4:i*4+4])[0] for i in range(n)]
def res(i): return d[offs[i]:offs[i+1] if i+1<n else len(d)]
vram=open('data/vdp2vram.bin','rb').read()
frame=vram[0x20:0x20+48]   # eeeee444...
zeros_then=vram[0:0x40]

def decode(data, params, outlen):
    (flagsize, flagorder, litval, u16order, lenlow, lenbits, thr, prezero) = params
    offbits=16-lenbits
    p=0; flags=0; fcount=0; out=bytearray()
    def getflag():
        nonlocal flags,fcount,p
        if fcount==0:
            if flagsize==8: flags=data[p]; p+=1; fcount=8
            else: flags=(data[p]<<8)|data[p+1]; p+=2; fcount=16
        if flagorder=='msb':
            fcount-=1; return (flags>>fcount)&1
        else:
            b=flags&1; flags>>=1; fcount-=1; return b
    try:
        while len(out)<outlen:
            f=getflag()
            if f==litval:
                out.append(data[p]); p+=1
            else:
                b0=data[p]; b1=data[p+1]; p+=2
                w=(b0<<8)|b1 if u16order=='big' else (b1<<8)|b0
                if lenlow:
                    length=(w&((1<<lenbits)-1))+thr; offv=w>>lenbits
                else:
                    length=(w>>offbits)+thr; offv=w&((1<<offbits)-1)
                dist=offv+1
                for _ in range(length):
                    if dist>len(out):
                        out.append(0 if prezero else 0x20)
                    else:
                        out.append(out[len(out)-dist])
        return bytes(out[:outlen])
    except IndexError:
        return None

def matchlen(o,ref):
    m=0
    for a,b in zip(o,ref):
        if a==b: m+=1
        else: break
    return m

cands=list(range(n-1))
results=[]
for flagsize in [8,16]:
 for flagorder in ['msb','lsb']:
  for litval in [0,1]:
   for u16order in ['big','little']:
    for lenlow in [True,False]:
     for lenbits in [3,4,5]:
      for thr in [0,1,2,3]:
       for prezero in [True]:
        params=(flagsize,flagorder,litval,u16order,lenlow,lenbits,thr,prezero)
        for ri in cands:
          o=decode(res(ri),params,48)
          if o is None: continue
          m=matchlen(o,frame)
          if m>=24:
            results.append((m,ri,params,o[:12].hex()))
results.sort(reverse=True)
print('top matches vs frame(eeeee444) as output start:')
for r in results[:15]: print(r)
