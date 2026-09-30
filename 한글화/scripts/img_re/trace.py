import struct
d=open('data/LANG2_IMG.DAT','rb').read()
n=struct.unpack('>I',d[:4])[0]//4
offs=[struct.unpack('>I', d[i*4:i*4+4])[0] for i in range(n)]
def res(i): return d[offs[i]:offs[i+1] if i+1<n else len(d)]
vram=open('data/vdp2vram.bin','rb').read()
TARGET=vram[:96]
R=res(16)
print('R:',R[:20].hex())
print('TARGET:',TARGET[:48].hex())

# Trace: 8-bit flags, msb-first, litval=0(=>bit1 is match), big u16, lenlow, lenbits=6, thr, distadd
def trace(data, flagorder, litval, u16order, lenlow, lenbits, thr, distadd, outlen):
    offbits=16-lenbits
    p=0; flags=0; fcount=0; out=bytearray(); log=[]
    def getflag():
        nonlocal flags,fcount,p
        if fcount==0:
            flags=data[p]; p+=1; fcount=8
        if flagorder=='msb':
            fcount-=1; return (flags>>fcount)&1
        else:
            b=flags&1; flags>>=1; fcount-=1; return b
    while len(out)<outlen and p<len(data):
        f=getflag()
        if f==litval:
            log.append(('LIT',hex(data[p]),'outpos',len(out)))
            out.append(data[p]); p+=1
        else:
            b0=data[p]; b1=data[p+1]; p+=2
            w=(b0<<8)|b1 if u16order=='big' else (b1<<8)|b0
            if lenlow:
                length=(w&((1<<lenbits)-1))+thr; offv=w>>lenbits
            else:
                length=(w>>offbits)+thr; offv=w&((1<<offbits)-1)
            dist=offv+distadd
            log.append(('MATCH','w',hex(w),'len',length,'dist',dist,'outpos',len(out)))
            for _ in range(length):
                if dist<=0 or dist>len(out): out.append(0)
                else: out.append(out[len(out)-dist])
    return out,log

out,log=trace(R,'msb',0,'big',True,6,1,1,96)
for l in log[:20]: print(l)
print('out[:48]:',bytes(out[:48]).hex())
