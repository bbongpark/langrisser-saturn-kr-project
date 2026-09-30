#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""미니 SH-2 디스어셈블러 (big-endian, 16-bit 고정). IMG.DAT 디컴프레서 정적 RE용.
완전하진 않지만 로더/DMA/디컴프 루프 판독에 충분한 공통 서브셋."""
import struct

def _s8(v):  return v-0x100 if v & 0x80 else v
def _s12(v): return v-0x1000 if v & 0x800 else v

def disasm_one(code, pc):
    """pc = 이 명령의 주소(리터럴 disp 계산용). returns (text, is_flow)."""
    w = code
    n = (w >> 8) & 0xf
    m = (w >> 4) & 0xf
    d4 = w & 0xf
    d8 = w & 0xff
    op = w >> 12
    def R(x): return "r%d"%x
    # PC-relative load target address
    if op == 0x9:  # mov.w @(disp,PC),Rn
        addr = pc + 4 + (d8*2)
        return "mov.w @(0x%x,pc),%s  ; =0x%08x"%(d8*2, R(n), addr), False
    if op == 0xd:  # mov.l @(disp,PC),Rn
        addr = (pc + 4 + (d8*4)) & ~3
        return "mov.l @(0x%x,pc),%s  ; =0x%08x"%(d8*4, R(n), addr), False
    if op == 0xe:  # mov #imm,Rn
        return "mov #0x%x,%s"%(_s8(d8)&0xffffffff, R(n)), False
    if op == 0x6:
        t={0:"mov.b @%s,%s",1:"mov.w @%s,%s",2:"mov.l @%s,%s",3:"mov %s,%s",
           4:"mov.b @%s+,%s",5:"mov.w @%s+,%s",6:"mov.l @%s+,%s",7:"not %s,%s",
           8:"swap.b %s,%s",9:"swap.w %s,%s",0xa:"negc %s,%s",0xb:"neg %s,%s",
           0xc:"extu.b %s,%s",0xd:"extu.w %s,%s",0xe:"exts.b %s,%s",0xf:"exts.w %s,%s"}[d4]
        return t%(R(m),R(n)), False
    if op == 0x2:
        t={0:"mov.b %s,@%s",1:"mov.w %s,@%s",2:"mov.l %s,@%s",4:"mov.b %s,@-%s",
           5:"mov.w %s,@-%s",6:"mov.l %s,@-%s",7:"div0s %s,%s",8:"tst %s,%s",
           9:"and %s,%s",0xa:"xor %s,%s",0xb:"or %s,%s",0xc:"cmp/str %s,%s",
           0xd:"xtrct %s,%s",0xe:"mulu.w %s,%s",0xf:"muls.w %s,%s"}[d4]
        return t%(R(m),R(n)), False
    if op == 0x3:
        t={0:"cmp/eq %s,%s",2:"cmp/hs %s,%s",3:"cmp/ge %s,%s",4:"div1 %s,%s",
           5:"dmulu.l %s,%s",6:"cmp/hi %s,%s",7:"cmp/gt %s,%s",8:"sub %s,%s",
           0xa:"subc %s,%s",0xb:"subv %s,%s",0xc:"add %s,%s",0xd:"dmuls.l %s,%s",
           0xe:"addc %s,%s",0xf:"addv %s,%s"}.get(d4)
        if t: return t%(R(m),R(n)), False
    if op == 0x4:
        one={0x00:"shll %s",0x01:"shlr %s",0x02:"sts mach,%s",0x04:"rotl %s",0x05:"rotr %s",
             0x06:"lds.l @%s+,mach",0x08:"shll2 %s",0x09:"shlr2 %s",0x0a:"lds %s,mach",
             0x0b:"jsr @%s",0x10:"dt %s",0x11:"cmp/pz %s",0x15:"cmp/pl %s",0x18:"shll8 %s",
             0x19:"shlr8 %s",0x1b:"tas.b @%s",0x20:"shal %s",0x21:"shar %s",0x22:"sts.l pr,@-%s",
             0x24:"rotcl %s",0x25:"rotcr %s",0x28:"shll16 %s",0x29:"shlr16 %s",0x2a:"lds %s,pr",
             0x2b:"jmp @%s",0x26:"lds.l @%s+,pr",0x0e:"ldc %s,sr",0x1e:"ldc %s,gbr",
             0x07:"ldc.l @%s+,sr",0x17:"ldc.l @%s+,gbr"}
        lo=w & 0xff
        if lo in one:
            t=one[lo]; flow = ("jsr" in t or "jmp" in t)
            return t%R(n), flow
        if d4==0xc: return "shad %s,%s"%(R(m),R(n)), False
        if d4==0xd: return "shld %s,%s"%(R(m),R(n)), False
    if op == 0x8:
        sub=(w>>8)&0xf
        if sub==0x8: return "cmp/eq #0x%x,r0"%(_s8(d8)&0xffffffff), False
        if sub==0x9: return "bt 0x%08x"%(pc+4+_s8(d8)*2), True
        if sub==0xb: return "bf 0x%08x"%(pc+4+_s8(d8)*2), True
        if sub==0xd: return "bt/s 0x%08x"%(pc+4+_s8(d8)*2), True
        if sub==0xf: return "bf/s 0x%08x"%(pc+4+_s8(d8)*2), True
        if sub==0x0: return "mov.b r0,@(0x%x,%s)"%(d4, R(m)), False
        if sub==0x1: return "mov.w r0,@(0x%x,%s)"%(d4*2, R(m)), False
        if sub==0x4: return "mov.b @(0x%x,%s),r0"%(d4, R(m)), False
        if sub==0x5: return "mov.w @(0x%x,%s),r0"%(d4*2, R(m)), False
    if op == 0xa: return "bra 0x%08x"%(pc+4+_s12(w&0xfff)*2), True
    if op == 0xb: return "bsr 0x%08x"%(pc+4+_s12(w&0xfff)*2), True
    if op == 0x0:
        if w==0x000b: return "rts", True
        if w==0x0009: return "nop", False
        if w==0x0008: return "clrt", False
        if w==0x0018: return "sett", False
        if w==0x0019: return "div0u", False
        if w==0x001b: return "sleep", False
        if w==0x0028: return "clrmac", False
        if d4==0x3 and m==0x0: return "bsrf %s"%R(n), True
        if d4==0x3 and m==0x2: return "braf %s"%R(n), True
        if d4==0xc: return "mov.b @(r0,%s),%s"%(R(m),R(n)), False
        if d4==0xd: return "mov.w @(r0,%s),%s"%(R(m),R(n)), False
        if d4==0xe: return "mov.l @(r0,%s),%s"%(R(m),R(n)), False
        if d4==0x4: return "mov.b %s,@(r0,%s)"%(R(m),R(n)), False
        if d4==0x5: return "mov.w %s,@(r0,%s)"%(R(m),R(n)), False
        if d4==0x6: return "mov.l %s,@(r0,%s)"%(R(m),R(n)), False
        if d4==0x7: return "mul.l %s,%s"%(R(m),R(n)), False
        if w&0xff==0x2a: return "sts pr,%s"%R(n), False
        if w&0xff==0x29: return "movt %s"%R(n), False
        if w&0xff==0x0a: return "sts mach,%s"%R(n), False
    if op == 0x1: return "mov.l %s,@(0x%x,%s)"%(R(m), d4*4, R(n)), False
    if op == 0x5: return "mov.l @(0x%x,%s),%s"%(d4*4, R(m), R(n)), False
    if op == 0x7: return "add #0x%x,%s"%(_s8(d8)&0xffffffff, R(n)), False
    if op == 0xc:
        sub=(w>>8)&0xf
        tbl={0:"mov.b r0,@(0x%x,gbr)"%d8,1:"mov.w r0,@(0x%x,gbr)"%(d8*2),
             2:"mov.l r0,@(0x%x,gbr)"%(d8*4),3:"trapa #0x%x"%d8,
             4:"mov.b @(0x%x,gbr),r0"%d8,5:"mov.w @(0x%x,gbr),r0"%(d8*2),
             6:"mov.l @(0x%x,gbr),r0"%(d8*4),7:"mova @(0x%x,pc),r0"%(d8*4),
             8:"tst #0x%x,r0"%d8,9:"and #0x%x,r0"%d8,0xa:"xor #0x%x,r0"%d8,
             0xb:"or #0x%x,r0"%d8,0xc:"tst.b #0x%x,@(r0,gbr)"%d8,0xd:"and.b #0x%x,@(r0,gbr)"%d8}
        if sub in tbl: return tbl[sub], False
    return ".word 0x%04x"%w, False

def disasm_range(data, file_off, load_base, count):
    """data=파일바이트, file_off=시작 파일오프셋, load_base=RAM 로드베이스, count=명령수."""
    out=[]
    for i in range(count):
        fo=file_off+i*2
        if fo+2>len(data): break
        w=struct.unpack(">H",data[fo:fo+2])[0]
        pc=load_base+fo
        txt,flow=disasm_one(w,pc)
        out.append("0x%08x  %04x  %s"%(pc,w,txt))
    return "\n".join(out)

if __name__=="__main__":
    import sys
    fn=sys.argv[1]; fo=int(sys.argv[2],0); base=int(sys.argv[3],0); cnt=int(sys.argv[4]) if len(sys.argv)>4 else 40
    print(disasm_range(open(fn,"rb").read(), fo, base, cnt))
