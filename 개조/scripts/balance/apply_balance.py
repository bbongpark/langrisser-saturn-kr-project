#!/usr/bin/env python3
"""
apply_balance.py — data/balance/*.json 을 디스크에 다시 굽는다.

사용:
  python apply_balance.py [<json 폴더>] [<대상 track1.bin>] [--out <출력 경로>]

기본 동작:
  대상 = extract_balance.py와 같은 기본 규칙(build/disc-mod/track1.bin 우선).
  --out 을 안 주면 대상 파일을 **제자리에서(in-place)** 덮어쓴다.
  단, 대상 경로에 "(Japan)"이 들어 있으면(원본 릴리즈 폴더로 보임) 안전을 위해
  거부한다 — --force로 무시 가능하나 원본을 직접 건드리는 것이므로 권장하지 않는다.
  항상 build/disc-krpoc 같은 "빌드 산출물" 위에서 작업해라.

registry.py에 등록된 테이블마다: JSON을 읽어 module.encode()로 바이트를 만들고,
해당 파일의 정확한 오프셋에 (파일 전체를 read-modify-write해서) 반영한다.
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

    if not os.path.exists(track1):
        print(f"트랙1을 찾을 수 없다: {track1}")
        sys.exit(1)

    out_path = out_override or track1
    if out_override is None and "(japan)" in track1.lower() and not force:
        print("⛔ 대상이 원본 릴리즈 폴더 안에 있는 것 같다 — 제자리 덮어쓰기를 거부한다.")
        print(f"   {track1}")
        print("   --out <경로> 로 다른 파일에 쓰거나, 정말 원한다면 --force 를 추가해라.")
        sys.exit(1)

    print(f"JSON: {json_dir}")
    print(f"대상 디스크: {track1}")
    d = Disc(track1)

    for table in registry.TABLES:
        mod = table["module"]
        for game, parts in table["games"].items():
            json_path = os.path.join(json_dir, f"{table['key']}_{game.lower()}.json")
            if not os.path.exists(json_path):
                continue
            records = load_json(json_path)
            result = mod.encode(records)
            payloads = (result,) if isinstance(result, (bytes, bytearray)) else tuple(result)
            assert len(payloads) == len(parts), (
                f"{table['key']}/{game}: encode()가 {len(payloads)}개 반환했는데 "
                f"구간은 {len(parts)}개다"
            )
            for part, payload in zip(parts, payloads):
                assert len(payload) == part["size"], (
                    f"{table['key']}/{game} {part['path']}@{part['offset']}: "
                    f"크기 {len(payload)} != 예상 {part['size']}"
                )
                bin_region.write_region(d, part["path"], part["offset"], payload)
            print(f"  [{table['key']}/{game}] {json_path} 반영 완료 ({len(parts)}개 구간)")

    if out_path == track1:
        # in-place: write to a temp file then replace, so a crash mid-write doesn't corrupt the disc
        tmp = track1 + ".tmp"
        d.save(tmp)
        os.replace(tmp, track1)
    else:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        d.save(out_path)
    print(f"\n저장 완료: {out_path}")


if __name__ == "__main__":
    main()
