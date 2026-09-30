#!/usr/bin/env python3
"""말투 후보를 사람이 확인한 정상 예외로 기록한다.

번역문 전체도 함께 저장하므로, 나중에 문장이 바뀌면 자동으로 예외가 풀리고 다시 검사된다.

사용:
  python scripts/review_tone_queue.py --kind mixed_speech
  python scripts/review_tone_queue.py --id L2:1/2/5#10 --apply
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CANDIDATES = os.path.join(ROOT, "build", "tone_audit", "candidates.json")
ACCEPTED = os.path.join(ROOT, "build", "tone_audit", "accepted.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", action="append", default=[])
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--note", default="앞뒤 문맥과 인물 말투를 확인한 정상 문장")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.kind and not args.id:
        ap.error("--kind 또는 --id가 필요합니다")

    with open(CANDIDATES, encoding="utf-8") as f:
        candidates = json.load(f)
    accepted = {}
    if os.path.exists(ACCEPTED):
        with open(ACCEPTED, encoding="utf-8") as f:
            accepted = json.load(f)

    chosen = {}
    wanted_ids = set(args.id)
    wanted_kinds = set(args.kind)
    for id0, row in candidates.items():
        kinds = {r["kind"] for r in row["reasons"]}
        if id0 in wanted_ids or kinds & wanted_kinds:
            chosen[id0] = {"kr": row["kr"], "note": args.note}

    missing = wanted_ids - set(chosen)
    print(f"정상 예외로 기록할 후보: {len(chosen)}개")
    for id0 in sorted(missing):
        print(f"  [없음] {id0}")
    for id0 in list(chosen)[:15]:
        print(f"  {id0}: {chosen[id0]['kr'][:90]}")
    if len(chosen) > 15:
        print(f"  … 외 {len(chosen) - 15}개")

    if not args.apply:
        print("(--apply 를 주면 기록합니다)")
        return
    accepted.update(chosen)
    tmp = ACCEPTED + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(accepted, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, ACCEPTED)
    print(f"[저장] {ACCEPTED}")


if __name__ == "__main__":
    main()
