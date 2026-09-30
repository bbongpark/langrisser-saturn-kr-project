#!/usr/bin/env python3
"""
bin_region.py — LANG1.BIN/LANG2.BIN "안의" 한 구간을 읽고 쓰는 헬퍼.

CLASS.DAT·FIGHT.DAT는 디스크에 독립된 파일이라 통째로 교체하면 되지만,
DerEditor가 병종/전직/아이템 등 대부분의 밸런스 데이터를 저장하는 곳은
**LANG1.BIN/LANG2.BIN(게임 코드) 안의 특정 오프셋**이다(예: 아이템 데이터
offset 397276, 560바이트). 파일 전체(약 417KB)를 통째로 다시 쓰는 대신,
**해당 구간만 잘라서 건드리고 나머지 바이트는 그대로 둔다** — 한글화가 이미
BIN 꼬리에 심어놓은 것(반각공백 SH-2 패치, 병종명 케이브 등, Next/README.md
3절 참고)을 실수로 덮어쓰지 않기 위해서다.

읽기: read_region(disc, "LANG2.BIN", offset, size) -> bytes
쓰기: write_region(disc, "LANG2.BIN", offset, payload)
      → 파일 전체를 읽어 그 구간만 갈아끼운 뒤 파일 전체를 다시 쓴다
        (disc_tool.write_file은 파일 단위로만 동작하므로 파일 전체를 매번
        다시 쓰지만, 구간 밖 바이트는 read-modify-write라 손상되지 않는다).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from project_paths import TRANSLATION_SCRIPTS
sys.path.insert(0, TRANSLATION_SCRIPTS)
from disc_tool import Disc  # noqa: E402
import disc_files  # noqa: E402


def read_region(disc: Disc, path: str, offset: int, size: int) -> bytes:
    info = disc_files.find(disc, path)
    whole = disc.read_file(info["extent"], info["size"])
    assert offset + size <= len(whole), (
        f"{path}: 구간({offset}+{size}) 이 파일 크기({len(whole)})를 벗어남"
    )
    return whole[offset:offset + size]


def write_region(disc: Disc, path: str, offset: int, payload: bytes):
    info = disc_files.find(disc, path)
    whole = bytearray(disc.read_file(info["extent"], info["size"]))
    assert offset + len(payload) <= len(whole), (
        f"{path}: 구간({offset}+{len(payload)}) 이 파일 크기({len(whole)})를 벗어남"
    )
    whole[offset:offset + len(payload)] = payload
    disc.write_file(info["extent"], bytes(whole), regen=True)


if __name__ == "__main__":
    track1 = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LANGRISSER_TRACK1")
    if not track1:
        print("usage: python bin_region.py <track1.bin>")
        sys.exit(1)
    d = Disc(track1)
    region = read_region(d, "LANG2.BIN", 397016, 104)
    print("LANG2.BIN[397016:397120] =", region.hex())
