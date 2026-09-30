#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""전투 애니메이션 프리즈 시점의 workramh를 원본/패치 LANG1.BIN과 비교해
오버레이 맵(패치 금지 구간 vs 배틀-세이프 구간)을 만든다."""
import sys, os, io, struct
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRATCH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import disc_tool, gen_classnames as gc

W = open(os.path.join(SCRATCH, "dump_anim_crash", "workramh.bin"), "rb").read()
orig = open(os.path.join(ROOT, "original", "LANG1.BIN"), "rb").read()
disc = disc_tool.Disc(os.path.join(ROOT, "build", "disc-krpoc", "track1.bin"))
patched = disc.read_file(202, 0x64F14)   # 크래시 빌드의 LANG1.BIN
N = len(orig)
BASE = 0x10000     # RAM 0x06010000 = workramh 0x10000
ram = W[BASE:BASE + N]

# 바이트 단위 비교: RAM vs patched, RAM vs orig
def classify(i):
    r = ram[i]; p = patched[i]; o = orig[i]
    if r == p: return "patch_live"      # 내 패치본 그대로 = 이 구간 flat, 패치 살아있음
    if r == o: return "orig"            # 원본과 같음(패치 안 한 곳이거나 패치가 안 실림)
    return "overlay"                    # 둘 다 아님 = 전투 오버레이가 덮음

# 구간별 요약 (연속 동일 분류를 묶음)
segs = []
cur = None; start = 0
for i in range(N):
    c = classify(i)
    if c != cur:
        if cur is not None:
            segs.append((start, i, cur))
        cur = c; start = i
segs.append((start, N, cur))

# overlay 구간만(내가 신경 쓸 곳) + 큰 것만
print("=== 전투 애니메이션 시점 오버레이(전투코드가 덮은) 구간 (≥16B) ===")
for s, e, c in segs:
    if c == "overlay" and e - s >= 16:
        print(f"  file 0x{s:05x}-0x{e:05x} ({e-s}B) RAM 0x{0x06010000+s:08x}")

# 내 패치 사이트가 어느 분류인지
print("\n=== 내 gen_classnames 패치 사이트 상태 ===")
cfg = gc.CONFIGS["L1"]
sites = {
    "conv_new(변환테이블재배치)": cfg["conv_new"],
    "conv_old(케이브영역)": cfg["conv_old"],
    "str_table(단일문자열)": cfg["str_table"],
    "cls hook": cfg["cls"],
    "bar_cls": cfg["bar_cls"],
    "vs_cls": cfg["vs_cls"],
    "bar_prim": cfg["bar_prim"],
    "vs_prim": cfg["vs_prim"],
    "char_ptr(캐릭터문자열)": cfg["char_ptr"],
    "lit_lead(16px리터럴)": cfg["lit_lead"],
}
for name, off in sorted(sites.items(), key=lambda x: x[1]):
    c = classify(off)
    r16 = ram[off:off+8].hex()
    p16 = patched[off:off+8].hex()
    print(f"  0x{off:05x} {name:24s}: {c:11s} RAM={r16} PATCH={p16}")

# 배틀-세이프 후보: RAM==orig(또는 patch)이고 원본이 0으로 채워진 충분히 큰 데드존
print("\n=== 배틀-세이프 데드존 후보 (원본 0x00 연속 ≥256B, RAM도 안 덮임) ===")
runs = []
i = 0
while i < N:
    if orig[i] == 0 and classify(i) != "overlay":
        j = i
        while j < N and orig[j] == 0 and classify(j) != "overlay":
            j += 1
        if j - i >= 256:
            runs.append((i, j))
        i = j
    else:
        i += 1
for s, e in runs[:40]:
    print(f"  file 0x{s:05x}-0x{e:05x} ({e-s}B) RAM 0x{0x06010000+s:08x}")
