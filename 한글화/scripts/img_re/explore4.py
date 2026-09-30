import struct
d=open('data/LANG2_IMG.DAT','rb').read()
n=struct.unpack('>I',d[:4])[0]//4
offs=[struct.unpack('>I', d[i*4:i*4+4])[0] for i in range(n)]
def res(i): return d[offs[i]:offs[i+1] if i+1<n else len(d)]
vram=open('data/vdp2vram.bin','rb').read()
TARGET=vram[:128]
R=res(16)

def bits_msb(data):
    for byte in data:
        for k in range(7,-1,-1):
            yield (byte>>k)&1
def bits_lsb(data):
    for byte in data:
        for k in range(8):
            yield (byte>>k)&1

def decode(data, order, litval, Ob, Lb, thr, litbits, outlen, distmode):
    g = bits_msb(data) if order=='msb' else bits_lsb(data)
    out=bytearray()
    def rd(nn):
        v=0
        for _ in range(nn):
            v=(v<<1)|next(g)
        return v
    try:
        while len(out)<outlen:
            f=next(g)
            if f==litval:
                out.append(rd(litbits) & 0xff)
            else:
                off=rd(Ob); length=rd(Lb)+thr
                if distmode=='back':
                    dist=off+1
                    for _ in range(length):
                        if dist>len(out): out.append(0)
                        else: out.append(out[len(out)-dist])
                else: # forward-from-ring absolute not applicable
                    dist=off+1
                    for _ in range(length):
                        if dist>len(out): out.append(0)
                        else: out.append(out[len(out)-dist])
        return bytes(out[:outlen])
    except StopIteration:
        return bytes(out)

def matchlen(o):
    m=0
    for a,b in zip(o,TARGET):
        if a==b: m+=1
        else: break
    return m

res_list=[]
for order in ['msb','lsb']:
 for litval in [0,1]:
  for Ob in [8,9,10,11,12,13]:
   for Lb in [3,4,5,6,7,8]:
    for thr in [0,1,2,3]:
     o=decode(R,order,litval,Ob,Lb,thr,8,128,'back')
     m=matchlen(o)
     res_list.append((m,order,litval,Ob,Lb,thr,o[:16].hex()))
res_list.sort(reverse=True,key=lambda x:x[0])
print('best bit-packed matchlen res16:')
for r in res_list[:12]: print(r)
