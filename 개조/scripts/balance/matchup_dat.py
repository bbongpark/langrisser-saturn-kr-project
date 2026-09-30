#!/usr/bin/env python3
"""
matchup_dat.py — LANG2.BIN 안의 병종 상성표 코덱. (DerEditor 탭11 "兵种相克")

위치: LANG2.BIN offset 405854, 648B = 18(공격측 병종) × 36(수비측 18병종 × 2바이트).
      셀 하나(2바이트) = (attack_bonus, defense_bonus) — 라벨 원문:
      "左边为攻击方,右边为防守方,数值以百分比形式加成到攻击方,数值范围0-255"
      (왼쪽=공격측, 오른쪽=수비측, 공격측에 % 가산, 0~255).

★ 정본: decompiled/DerEditor/Form1.cs LoadData18()(~3564). 두 라디오버튼
  ("攻击加成"/"防御加成" — 코드상 텍스트가 얼핏 뒤바뀐 것처럼 보일 수 있으니
  주의, 실제로는 radioButton11=攻击加成/radioButton12=防御加成)이 같은 36바이트
  행에서 짝수(공격%)/홀수(방어%) 바이트를 각각 보여주는 두 가지 보기일 뿐,
  둘 다 SS가 실제로 쓰는 값이다(지형표의 짝/홀 분리와 달리 플랫폼 분리가 아님).

실측 검증: 退魔类(엑소시스트) 행이 史莱姆/恶魔类/鬼魂类/不死类(슬라임·악마·
유령·언데드)에 집중적으로 높은 보너스(공25~40/방20) — "대(對)언데드 특화"
직업 컨셉과 완전히 일치.

행(공격측)·열(수비측) 둘 다 같은 18병종 순서로 추정(terrain_dat.UNIT_TYPE_NAMES와
동일 체계) — **열 쪽은 그래픽 헤더 텍스트가 없어 순서 일치는 미확정**이니
값을 편집할 땐 우선 실기/에뮬레이터로 한 셀을 바꿔 확인하고 넓게 적용해라.
"""
from json_io import load_json, save_json  # noqa: F401
from terrain_dat import UNIT_TYPE_NAMES, N_UNIT_TYPE  # noqa: F401

BIN_PATH = "LANG2.BIN"  # L1 오프셋 미검증
OFFSET = 405854
SIZE = 648
STRIDE = N_UNIT_TYPE * 2  # 36
assert STRIDE * N_UNIT_TYPE == SIZE


def decode(region: bytes) -> list:
    assert len(region) == SIZE, f"영역은 {SIZE}바이트여야 함 (got {len(region)})"
    rows = []
    for i in range(N_UNIT_TYPE):
        row = []
        for j in range(N_UNIT_TYPE):
            base = i * STRIDE + j * 2
            row.append({"attack_bonus": region[base], "defense_bonus": region[base + 1]})
        rows.append(row)
    return rows


def encode(rows: list) -> bytes:
    assert len(rows) == N_UNIT_TYPE
    out = bytearray(SIZE)
    for i, row in enumerate(rows):
        assert len(row) == N_UNIT_TYPE
        for j, cell in enumerate(row):
            base = i * STRIDE + j * 2
            a, d = cell["attack_bonus"], cell["defense_bonus"]
            if not (0 <= a <= 255 and 0 <= d <= 255):
                raise ValueError(f"[{i}][{j}] out of byte range: {cell}")
            out[base] = a
            out[base + 1] = d
    return bytes(out)


if __name__ == "__main__":
    import random
    random.seed(0)
    buf = bytes(random.randint(0, 255) for _ in range(SIZE))
    rows = decode(buf)
    buf2 = encode(rows)
    assert buf == buf2, "round-trip 실패"
    print("matchup_dat self-test OK (round-trip byte-identical,", N_UNIT_TYPE, "x", N_UNIT_TYPE, ")")
