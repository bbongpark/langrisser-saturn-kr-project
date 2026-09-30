#!/usr/bin/env python3
"""
apply_stage.py — data/balance/stage_l2.json 을 LANG2/SCEN.DAT에 다시 굽는다.

사용:
  python apply_stage.py [<json 폴더>] [<대상 track1.bin>] [--out <출력 경로>]

동작: scen_tool로 SCEN.DAT를 트리로 파싱 → 92개 스테이지 리프를 JSON의 내용으로
교체(stage_dat.encode_stage가 원본과 정확히 같은 압축 크기로 패딩) →
scen_tool.serialize()로 SCEN.DAT 전체를 재조립 → **크기가 원본과 정확히
같은지 검증**(다르면 디스크에 안 쓰고 에러) → disc_tool로 반영.

다른 balance 테이블과 마찬가지로 --out 없으면 제자리 반영, "(Japan)" 경로는 거부.
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from project_paths import TRANSLATION_SCRIPTS
sys.path.insert(0, TRANSLATION_SCRIPTS)
from disc_tool import Disc  # noqa: E402
import disc_files  # noqa: E402
import scen_tool  # noqa: E402
import stage_dat  # noqa: E402
from json_io import load_json  # noqa: E402
from extract_balance import default_track1  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('json_dir', nargs='?', default=os.path.join(PROJECT_ROOT, 'data', 'balance'))
    parser.add_argument('track1', nargs='?', default=default_track1())
    parser.add_argument('--out')
    parser.add_argument('--force', action='store_true')
    opts = parser.parse_args()
    json_dir, track1, out_override, force = opts.json_dir, opts.track1, opts.out, opts.force
    json_path = os.path.join(json_dir, "stage_l2.json")

    if not os.path.exists(track1):
        print(f"트랙1을 찾을 수 없다: {track1}")
        sys.exit(1)
    if not os.path.exists(json_path):
        print(f"stage_l2.json이 없다: {json_path}")
        sys.exit(1)

    out_path = out_override or track1
    if out_override is None and "(japan)" in track1.lower() and not force:
        print("⛔ 대상이 원본 릴리즈 폴더 안에 있는 것 같다 — 제자리 덮어쓰기를 거부한다.")
        print(f"   {track1}")
        print("   --out <경로> 로 다른 파일에 쓰거나, 정말 원한다면 --force 를 추가해라.")
        sys.exit(1)

    print(f"JSON: {json_path}")
    print(f"대상 디스크: {track1}")
    d = Disc(track1)
    info = disc_files.find(d, "LANG2/SCEN.DAT")
    scen = d.read_file(info["extent"], info["size"])
    tree = scen_tool.parse(scen)

    stages = load_json(json_path)
    assert len(stages) == stage_dat.STAGE_COUNT, f"스테이지 {stage_dat.STAGE_COUNT}개여야 함"

    changed = 0
    for i, stage_data in enumerate(stages):
        leaf = tree.children[i].children[1]
        if stage_dat.unchanged(leaf.raw, stage_data):
            continue  # 원본 압축 바이트를 그대로 둔다 — 디스크 변경 범위 최소화
        leaf.raw = stage_dat.encode_stage(stage_data)
        changed += 1
    print(f"  편집된 스테이지: {changed}/{stage_dat.STAGE_COUNT} (나머지는 원본 바이트 그대로 보존)")

    new_scen = bytes(scen_tool.serialize(tree))
    if len(new_scen) != len(scen):
        print(f"⛔ SCEN.DAT 전체 크기가 바뀐다({len(scen)} -> {len(new_scen)}) — "
              "디스크에 반영할 수 없다(파일 크기 고정). 편집을 줄여봐라.")
        sys.exit(1)

    d.write_file(info["extent"], new_scen, regen=True)
    print(f"  LANG2/SCEN.DAT: LBA={info['extent']} 에 {len(new_scen)}바이트 반영 (크기 불변 확인됨)")

    if out_path == track1:
        tmp = track1 + ".tmp"
        d.save(tmp)
        os.replace(tmp, track1)
    else:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        d.save(out_path)
    print(f"\n저장 완료: {out_path}")


if __name__ == "__main__":
    main()
