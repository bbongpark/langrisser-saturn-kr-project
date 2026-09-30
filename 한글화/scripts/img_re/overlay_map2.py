#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""오버레이 맵 정밀화: 전투 애니메이션이 덮는 RAM 구간 전체 + 배틀-세이프 재배치 후보를
LANG1.BIN 꼬리(0x61000~0x64f14)에서 찾아 다음 세션용 문서로 저장."""
import sys, os, io
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRATCH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import disc_tool

W = open(os.path.join(SCRATCH, "dump_anim_crash", "workramh.bin"), "rb").read()
orig = open(os.path.join(ROOT, "original", "LANG1.BIN"), "rb").read()
disc = disc_tool.Disc(os.path.join(ROOT, "build", "disc-krpoc", "track1.bin"))
patched = disc.read_file(202, 0x64F14)
N = len(orig)
ram = W[0x10000:0x10000 + N]

def is_overlay(i):
    return ram[i] != patched[i] and ram[i] != orig[i]

# 전체 오버레이 풋프린트(구간 병합, 간격 8B 이하는 하나로)
ov = []
i = 0
while i < N:
    if is_overlay(i):
        j = i
        gap = 0
        k = i
        while k < N:
            if is_overlay(k):
                j = k; gap = 0
            else:
                gap += 1
                if gap > 8:
                    break
            k += 1
        ov.append((i, j + 1))
        i = k
    else:
        i += 1
print("=== 전투 애니메이션 오버레이 풋프린트 (간격≤8B 병합) ===")
tail_ov = [(s, e) for s, e in ov if s >= 0x60000]
for s, e in ov:
    print(f"  file 0x{s:05x}-0x{e:05x} ({e-s}B) RAM 0x{0x06010000+s:08x}")
print(f"  (전체 {len(ov)}구간; 꼬리 0x60000+ 만 {len(tail_ov)}구간)")

# 배틀-세이프: 오버레이 아닌 구간 중, LANG1.BIN 데이터 꼬리에서 재사용 가능한 큰 구간.
# 관심 영역: 0x617a0(str_table)~0x64f14(file end). 여기서 오버레이 안 덮는 연속 구간.
print("\n=== 0x617a0~0x64f14 에서 오버레이 안 덮는 연속 구간 (≥64B) ===")
lo, hi = 0x617a0, 0x64f14
segs = []
i = lo
while i < hi:
    if not is_overlay(i):
        j = i
        while j < hi and not is_overlay(j):
            j += 1
        if j - i >= 64:
            segs.append((i, j))
        i = j
    else:
        i += 1
for s, e in segs:
    # 원본 내용 힌트
    z = all(b == 0 for b in orig[s:e])
    print(f"  file 0x{s:05x}-0x{e:05x} ({e-s}B) RAM 0x{0x06010000+s:08x} {'(원본0)' if z else ''}")

# 필요 공간 요약
print("\n=== 필요 케이브 크기 (재배치 대상) ===")
print("  heal ~44 + cave8 ~200 + prim_a/b 52x2 + barprim 44 + vsprim 52 + bartxt ~180 + vstxt ~180 = ~800B")
print("  + conv table 512B (conv_new)")
