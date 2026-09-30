#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preserve_save.py — 재빌드로 디스크 md5가 바뀌어도 인게임 세이브(백업 RAM .bkr)를 잇는다.

mednafen 새턴은 백업 RAM 세이브를 `<sav>/langrisser-krpoc.<disc_md5>.bkr` 로 저장하는데,
디스크를 재빌드하면 md5가 바뀌어 게임이 예전 세이브를 못 찾는다. 재빌드 전 세이브를
새 md5 이름으로 복사하면 클리어 진행이 그대로 이어진다(대사 SCEN은 세이브에 없으니
불러와 시나리오에 들어가면 새 디스크의 대사가 나옴).

  python scripts/preserve_save.py <old_md5> <new_md5>
    old_md5 : 재빌드 전 디스크 id (get_rom_info content_md5), 생략 시 가장 최근 .bkr 자동 선택
    new_md5 : 재빌드 후 디스크 id (get_rom_info content_md5)

  예) python scripts/preserve_save.py 23f290066e879b8b40aa4ce52529be1a <new>
"""
import glob
import os
import shutil
import sys

SAV = os.path.join(os.environ.get("LOCALAPPDATA",
                   os.path.expanduser(r"~\AppData\Local")),
                   "emucap", "mednafen", "47800", "sav")
NAME = "langrisser-krpoc"


def newest_bkr(exclude_md5=None):
    cands = [p for p in glob.glob(os.path.join(SAV, f"{NAME}.*.bkr"))
             if not (exclude_md5 and exclude_md5 in os.path.basename(p))]
    return max(cands, key=os.path.getmtime) if cands else None


def main():
    args = sys.argv[1:]
    if len(args) == 1:                       # new_md5 만 준 경우 → old 는 최신 자동
        new_md5 = args[0]
        src = newest_bkr(exclude_md5=new_md5)
    elif len(args) == 2:
        old_md5, new_md5 = args
        src = os.path.join(SAV, f"{NAME}.{old_md5}.bkr")
    else:
        print(__doc__); sys.exit(1)
    if not src or not os.path.exists(src):
        print(f"복사할 세이브(.bkr)를 못 찾음: {src}"); sys.exit(1)
    dst = os.path.join(SAV, f"{NAME}.{new_md5}.bkr")
    shutil.copy2(src, dst)
    print(f"세이브 이어붙임: {os.path.basename(src)} -> {os.path.basename(dst)}")
    # .smpc(시계 등) 있으면 같이 복사
    smpc = src[:-4] + ".smpc"
    if os.path.exists(smpc):
        shutil.copy2(smpc, dst[:-4] + ".smpc")


if __name__ == "__main__":
    main()
