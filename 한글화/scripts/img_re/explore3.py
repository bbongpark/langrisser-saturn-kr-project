import struct
d=open('data/LANG2_IMG.DAT','rb').read()
n=struct.unpack('>I',d[:4])[0]//4
offs=[struct.unpack('>I', d[i*4:i*4+4])[0] for i in range(n)]
def res(i): return d[offs[i]:offs[i+1] if i+1<n else len(d)]
vram=open('data/vdp2vram.bin','rb').read()
TARGET=vram[:96]   # 00*32 + eeeee444...

# canonical-prefix resource: 16 has c00107d464637e1067e005b8
R=res(16)

def decode(data, params, outlen):
    (flagsize, flagorder, litval, u16order, lenlow, lenbits, thr, distadd) = params
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
                dist=offv+distadd
                if dist<=0: return out
                for _ in range(length):
                    if dist>len(out): out.append(0)
                    else: out.append(out[len(out)-dist])
        return bytes(out[:outlen])
    except IndexError:
        return bytes(out)

def matchlen(o,ref):
    m=0
    for a,b in zip(o,ref):
        if a==b: m+=1
        else: break
    return m

results=[]
for flagsize in [8,16]:
 for flagorder in ['msb','lsb']:
  for litval in [0,1]:
   for u16order in ['big','little']:
    for lenlow in [True,False]:
     for lenbits in [3,4,5,6]:
      for thr in [0,1,2,3]:
       for distadd in [0,1,2]:
        params=(flagsize,flagorder,litval,u16order,lenlow,lenbits,thr,distadd)
        o=decode(R,params,96)
        if not o: continue
        m=matchlen(o,TARGET)
        results.append((m,params,o[:16].hex()))
results.sort(reverse=True, key=lambda x:x[0])
print('best matchlen for res16 vs 00*32+frame:')
for r in results[:12]: print(r)
