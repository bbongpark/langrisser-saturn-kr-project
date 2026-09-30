#!/usr/bin/env python3
"""
extract_stage.py — LANG2/SCEN.DAT에서 92개 스테이지의 유닛 배치를 JSON으로 뽑는다.

registry.py 기반 파이프라인과 별도다(stage_dat.py 상단 설명 참고) — SCEN.DAT는
`scen_tool`의 재귀 트리로 통째로 파싱해야 한다.

사용:
  python extract_stage.py [<track1.bin> [<출력 폴더>]]
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # Next/scripts (for scen_tool)
from project_paths import TRANSLATION_SCRIPTS
sys.path.insert(0, TRANSLATION_SCRIPTS)
from disc_tool import Disc  # noqa: E402
import disc_files  # noqa: E402
import scen_tool  # noqa: E402
import stage_dat  # noqa: E402
from json_io import save_json  # noqa: E402
from extract_balance import default_track1  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    track1 = sys.argv[1] if len(sys.argv) > 1 else default_track1()
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(PROJECT_ROOT, "build", "extracted-balance")
    if not os.path.exists(track1):
        print(f"트랙1을 찾을 수 없다: {track1}")
        sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)

    print(f"디스크: {track1}")
    d = Disc(track1)
    info = disc_files.find(d, "LANG2/SCEN.DAT")
    scen = d.read_file(info["extent"], info["size"])
    print(f"LANG2/SCEN.DAT: LBA={info['extent']} size={info['size']}")

    tree = scen_tool.parse(scen)
    rebuilt_check = bytes(scen_tool.serialize(tree))
    if rebuilt_check != scen:
        print("⛔ scen_tool 라운드트립이 원본과 다르다 — SCEN.DAT 파싱 가정이 이 디스크에 안 맞을 수 있다.")
        sys.exit(1)

    stages = []
    for stage_idx in range(stage_dat.STAGE_COUNT):
        leaf = tree.children[stage_idx].children[1]
        stages.append(stage_dat.decode_stage(leaf.raw))

    out_path = os.path.join(out_dir, "stage_l2.json")
    save_json(stages, out_path)
    print(f"-> {out_path} ({len(stages)}개 스테이지)")
    print("\n완료. apply_stage.py 로 반영해라.")


if __name__ == "__main__":
    main()
