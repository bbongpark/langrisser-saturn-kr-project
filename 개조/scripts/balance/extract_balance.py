#!/usr/bin/env python3
"""
extract_balance.py — registry.py에 등록된 모든 테이블을 디스크에서 뽑아
편집용 JSON으로 저장한다.

사용:
  python extract_balance.py [<track1.bin> [<출력 폴더>]]

기본값:
  track1.bin  = $LANGRISSER_TRACK1  또는  Next/build/disc-krpoc/track1.bin
                (아직 안 빌드했으면 $LANGRISSER_DISC 원본 JP 트랙1로 폴백)
  출력 폴더   = Next/build/balance/

출력 파일명: build/balance/<key>_<game>.json  (예: class_l1.json, item_l2.json)
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
import bin_region  # noqa: E402
import registry  # noqa: E402
from json_io import save_json  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))


def default_track1() -> str:
    env = os.environ.get("LANGRISSER_TRACK1")
    if env and os.path.exists(env):
        return env
    built = os.path.join(PROJECT_ROOT, "build", "disc-mod", "track1.bin")
    if os.path.exists(built):
        return built
    return built



def main():
    track1 = sys.argv[1] if len(sys.argv) > 1 else default_track1()
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(PROJECT_ROOT, "build", "extracted-balance")
    if not os.path.exists(track1):
        print(f"트랙1을 찾을 수 없다: {track1}")
        print("경로를 인자로 주거나 LANGRISSER_TRACK1 환경변수를 설정해라.")
        sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)

    print(f"디스크: {track1}")
    d = Disc(track1)
    for table in registry.TABLES:
        mod = table["module"]
        for game, parts in table["games"].items():
            regions = [bin_region.read_region(d, p["path"], p["offset"], p["size"]) for p in parts]
            records = mod.decode(*regions)
            out_path = os.path.join(out_dir, f"{table['key']}_{game.lower()}.json")
            save_json(records, out_path)
            paths = ", ".join(f"{p['path']}@{p['offset']}({p['size']}B)" for p in parts)
            print(f"  [{table['key']}/{game}] {paths} -> {out_path} ({len(records)} records)")

    print("\n완료. build/balance/*.json 을 편집한 뒤 python apply_balance.py 로 디스크에 반영해라.")


if __name__ == "__main__":
    main()
