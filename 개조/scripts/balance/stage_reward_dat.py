#!/usr/bin/env python3
"""
stage_reward_dat.py — LANG2.BIN 안의 스테이지 클리어 보상 코덱. (DerEditor 탭9
"关卡数据"의 일부 — `textBox24`/`textBox25`, 골드·경험치 두 필드)

위치: LANG2.BIN offset 405656(골드, 92B) + 405756(경험치, 92B). 92스테이지
(SSL2 `comboBox70.Items.Count==92`, `剧本1~92`)와 1:1 대응.

★ 정본: 탭9 조사 세션에서 `_tab9_probe.py`로 실측 — 스테이지1(35×10=350P/9EXP)부터
자연스럽게 우상향하다가(최대 250×10=2500P/21EXP) 0인 항목들이 섞여 있음(분기
시나리오 등 표준 보상이 없는 스테이지로 추정, 미확인).

⚠ 이 테이블은 탭9의 **일부**일 뿐이다 — 유닛 배치/AI/장비 등 스테이지의 나머지
데이터(SCEN.DAT 안의 압축 블롭)는 아직 읽기 전용(`_tab9_probe.py`)이고 이
모듈과 무관하다.

필드:
  gold_x10  골드 보상 — 표시값은 raw×10 (한글화 HANDOFF의 소지금 저장 관례와 동일)
  exp       경험치 보상 (raw 그대로)

레코드 수: 92.
"""
from json_io import load_json, save_json  # noqa: F401

BIN_PATH = "LANG2.BIN"  # L1 오프셋 미검증
GOLD_OFFSET = 405656
EXP_OFFSET = 405756
STAGE_COUNT = 92
assert GOLD_OFFSET + STAGE_COUNT == 405748  # 다음 필드(EXP)와 안 겹치는지 확인
assert EXP_OFFSET + STAGE_COUNT == 405848   # matchup_dat 시작(405854) 전에 끝나는지 확인


def decode(gold_region: bytes, exp_region: bytes) -> list:
    assert len(gold_region) == STAGE_COUNT
    assert len(exp_region) == STAGE_COUNT
    return [
        {"index": i, "gold_x10": gold_region[i], "gold_display": gold_region[i] * 10, "exp": exp_region[i]}
        for i in range(STAGE_COUNT)
    ]


def encode(records: list) -> tuple:
    assert len(records) == STAGE_COUNT
    gold_out = bytearray(STAGE_COUNT)
    exp_out = bytearray(STAGE_COUNT)
    for i, o in enumerate(records):
        g, e = o["gold_x10"], o["exp"]
        if not (0 <= g <= 255 and 0 <= e <= 255):
            raise ValueError(f"stage {i}: gold_x10={g} exp={e} out of byte range")
        gold_out[i] = g
        exp_out[i] = e
    return bytes(gold_out), bytes(exp_out)


if __name__ == "__main__":
    import random
    random.seed(0)
    gold = bytes(random.randint(0, 255) for _ in range(STAGE_COUNT))
    exp = bytes(random.randint(0, 255) for _ in range(STAGE_COUNT))
    recs = decode(gold, exp)
    g2, e2 = encode(recs)
    assert (gold, exp) == (g2, e2), "round-trip 실패"
    print("stage_reward_dat self-test OK (round-trip byte-identical,", STAGE_COUNT, "stages)")
