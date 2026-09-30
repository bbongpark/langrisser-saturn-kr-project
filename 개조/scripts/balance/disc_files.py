#!/usr/bin/env python3
"""
disc_files.py — ISO9660 directory walker for the Saturn data track.

DerEditor(중국산 랑그릿사 전술 에디터)는 SS판(SSL2)에서 CLASS.DAT/FIGHT.DAT/BIN을
"디스크 안의 고정 절대 바이트 오프셋"으로 읽는다(standalone 랑그릿사2 새턴판 기준).
우리 디스크(Dramatic Edition, L1+L2 합본)는 마스터링이 달라 그 오프셋을 그대로 못 쓴다.

대신 이 파일은 디스크의 ISO9660 파일시스템을 직접 파싱해 파일명으로 LBA를 찾는다.
kr-patch가 이미 LANG2/SCEN.DAT를 LBA 157751로 알고 있었는데(HANDOFF.md), 이 파서로
같은 파일을 찾으면 정확히 LBA 157751이 나와 파서가 검증됐다.

한글화 빌드는 "같은 크기 패치"만 한다(disc_tool.write_file 요구사항) — 그래서 파일
크기·위치(LBA)가 원본 일본어판과 KR 빌드 사이에 절대 안 바뀐다. 즉 이 파서는 원본
디스크에도, KR 패치가 끝난 build/disc-krpoc 디스크에도 똑같이 쓸 수 있다.
"""
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from project_paths import TRANSLATION_SCRIPTS
sys.path.insert(0, TRANSLATION_SCRIPTS)
from disc_tool import Disc  # noqa: E402


def _parse_dr(rec: bytes) -> dict:
    reclen = rec[0]
    extent = struct.unpack_from("<I", rec, 2)[0]
    size = struct.unpack_from("<I", rec, 10)[0]
    flags = rec[25]
    len_fi = rec[32]
    fi = rec[33:33 + len_fi]
    return dict(reclen=reclen, extent=extent, size=size, flags=flags, fi=fi)


def _list_dir(disc: Disc, extent: int, size: int) -> list:
    data = disc.read_file(extent, size)
    pos = 0
    entries = []
    while pos < len(data):
        reclen = data[pos]
        if reclen == 0:
            pos = (pos // 2048 + 1) * 2048
            if pos >= len(data):
                break
            continue
        entries.append(_parse_dr(data[pos:pos + reclen]))
        pos += reclen
    return entries


def _strip_version(name: bytes) -> str:
    s = name.decode("ascii", "replace")
    if ";" in s:
        s = s.split(";")[0]
    return s


def root_dir(disc: Disc) -> dict:
    pvd = disc.read_file(16, 2048)
    assert pvd[1:6] == b"CD001", "LBA16이 ISO9660 PVD가 아니다 (디스크 확인)"
    return _parse_dr(pvd[156:156 + 34])


def find(disc: Disc, path: str) -> dict:
    """path 예: 'LANG2/CLASS.DAT' 또는 '0.BIN'. {'extent':LBA,'size':bytes} 반환."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    node = root_dir(disc)
    for i, part in enumerate(parts):
        entries = _list_dir(disc, node["extent"], node["size"])
        match = None
        for e in entries:
            if e["fi"] in (b"\x00", b"\x01"):
                continue
            if _strip_version(e["fi"]).upper() == part.upper():
                match = e
                break
        if match is None:
            raise FileNotFoundError(f"디스크에 없음: {path} ('{part}' 단계에서 실패)")
        node = match
    return {"extent": node["extent"], "size": node["size"]}


def listing(disc: Disc, path: str = "") -> list:
    """디렉터리 하나의 항목 리스트. 파일명·LBA·크기·디렉터리 여부."""
    if path:
        d = find(disc, path)
    else:
        d = root_dir(disc)
    out = []
    for e in _list_dir(disc, d["extent"], d["size"]):
        if e["fi"] in (b"\x00", b"\x01"):
            continue
        out.append({
            "name": _strip_version(e["fi"]),
            "extent": e["extent"],
            "size": e["size"],
            "is_dir": bool(e["flags"] & 2),
        })
    return out


if __name__ == "__main__":
    track1 = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LANGRISSER_TRACK1")
    if not track1:
        print("usage: python disc_files.py <track1.bin> [path ...]")
        sys.exit(1)
    d = Disc(track1)
    for p in (sys.argv[2:] or ["LANG1/CLASS.DAT", "LANG2/CLASS.DAT"]):
        info = find(d, p)
        print(f"{p}: extent(LBA)={info['extent']}  size={info['size']}")
