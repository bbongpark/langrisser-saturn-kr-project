#!/usr/bin/env python3
"""
class_dat.py — LANG1/LANG2 CLASS.DAT(7,140B = 255레코드 × 28바이트) 코덱.

병종/직업(職業/兵種) 스탯 테이블. 랑그릿사 시리즈 밸런스의 핵심 데이터 —
HP는 없다(HP는 별도 레벨업 성장 테이블, 여기 아님. BALANCE_PIPELINE.md 참고).

★ 정본 출처: DerEditor_V1.9.1(중국 팬패치 에디터, .NET) 디컴파일 —
  DerEditor_V1.9.1/decompiled/DerEditor/Form1.cs
  - LoadData1()/SaveData1() 의 radioButton10(SSL2, 새턴판) 분기 (~line 2102, ~line 2680대)
  - 필드명은 Form1.cs InitializeComponent의 라벨(중국어)에서 좌표로 대조해 확정
    (label3~label20, textBox2~12, comboBox1~7, numericUpDown1/10~12, checkBox5)
  - 실측 검증: 우리 디스크(원본 JP) L1/L2 CLASS.DAT 앞 8레코드 + 마지막 레코드를
    디코딩해 값 범위가 전부 정상(AT/DF/MV 1~8, magic_resist 45~80% 등)임을 확인.

레코드 오프셋(28바이트, 새턴판 SSL2 기준 — 다른 플랫폼은 오프셋이 다름, 여기선 무관):
  0   reserved_0        용도 미상 (관측상 전부 0) — 원본값 보존만
  1   flying            비행 상태 (0/1)
  2   type              병종 타입(comboBox84 인덱스, 의미 미해독 — RAW ID)
  3   magic             마력(魔力)
  4   AT                공격력
  5   DF                방어력
  6   MV                이동력
  7   cmd_range         지휘범위
  8   A_mod             공격 수정치
  9   D_mod             방어 수정치
  10  MP                MP
  11  magic_resist      마법내성(%)
  12  merc_count        용병 고용 가능 수 (부호 있는 byte, 249 초과 시 -256 보정)
  13  merc_price_raw    용병 가격 — 화면 표시 = raw*10 P (에디터 라벨 "×10 P")
  14  kill_money_raw    처치 시 획득 골드 — 화면 표시 = raw*10 P
  15  kill_exp          처치 시 획득 경험치
  16  levelup_exp_raw   레벨업 필요 경험치 — 화면 표시 = raw*8 (에디터 라벨 "×8")
  17  reserved_17       용도 미상(비-새턴판에서 쓰임, 새턴 UI 미사용)
  18  reserved_18       〃
  19  merc1_id          용병1 종류 ID (RAW, 0=없음)
  20  reserved_20       용도 미상
  21  merc2_id          용병2 종류 ID
  22  reserved_22       용도 미상
  23  merc3_id          용병3 종류 ID
  24  magic1_id         마법1 ID (RAW, 0xFF=없음)
  25  magic2_id         마법2 ID
  26  magic3_id         마법3 ID
  27  magic4_id         마법4 ID

⚠ merc*_id/magic*_id/type은 "RAW ID"만 보존한다 — 에디터가 콤보박스에 채우는
  이름 목록(어떤 ID가 어떤 마법/용병인지)은 아직 디코딩하지 않았다. 값을 바꿀 땐
  같은 게임 안의 다른 레코드에서 이미 쓰이고 있는 ID를 재사용하는 것이 안전하다.

레코드 수: 7140 / 28 = 255.
"""
import sys
import os
from json_io import load_json, save_json  # noqa: F401

RECORD_SIZE = 28
RECORD_COUNT = 255
assert RECORD_SIZE * RECORD_COUNT == 7140

# (offset, field_name, kind)  kind: 'u8' | 'i8' | 'x10' | 'x8'
FIELDS = [
    (0, "reserved_0", "u8"),
    (1, "flying", "u8"),
    (2, "type", "u8"),
    (3, "magic", "u8"),
    (4, "AT", "u8"),
    (5, "DF", "u8"),
    (6, "MV", "u8"),
    (7, "cmd_range", "u8"),
    (8, "A_mod", "u8"),
    (9, "D_mod", "u8"),
    (10, "MP", "u8"),
    (11, "magic_resist", "u8"),
    (12, "merc_count", "i8"),
    (13, "merc_price_raw", "x10"),
    (14, "kill_money_raw", "x10"),
    (15, "kill_exp", "u8"),
    (16, "levelup_exp_raw", "x8"),
    (17, "reserved_17", "u8"),
    (18, "reserved_18", "u8"),
    (19, "merc1_id", "u8"),
    (20, "reserved_20", "u8"),
    (21, "merc2_id", "u8"),
    (22, "reserved_22", "u8"),
    (23, "merc3_id", "u8"),
    (24, "magic1_id", "u8"),
    (25, "magic2_id", "u8"),
    (26, "magic3_id", "u8"),
    (27, "magic4_id", "u8"),
]
_MULT = {"x10": 10, "x8": 8}


def decode(data: bytes) -> list:
    assert len(data) == 7140, f"CLASS.DAT는 7140바이트여야 함 (got {len(data)})"
    records = []
    for i in range(RECORD_COUNT):
        rec = data[i * RECORD_SIZE:(i + 1) * RECORD_SIZE]
        obj = {"index": i}
        for off, name, kind in FIELDS:
            b = rec[off]
            if kind == "i8":
                obj[name] = b - 256 if b > 249 else b
            else:
                obj[name] = b
            if kind in _MULT:
                obj[name.replace("_raw", "_display")] = b * _MULT[kind]
        records.append(obj)
    return records


def encode(records: list) -> bytes:
    assert len(records) == RECORD_COUNT, f"레코드 255개여야 함 (got {len(records)})"
    out = bytearray(7140)
    for i, obj in enumerate(records):
        base = i * RECORD_SIZE
        for off, name, kind in FIELDS:
            v = obj[name]
            if kind == "i8":
                v = v & 0xFF
            if not (0 <= v <= 255):
                raise ValueError(f"record {i} field {name}={v} out of byte range")
            out[base + off] = v
    return bytes(out)


if __name__ == "__main__":
    # self-test: round-trip a synthetic buffer
    import random
    random.seed(0)
    buf = bytes(random.randint(0, 255) for _ in range(7140))
    recs = decode(buf)
    buf2 = encode(recs)
    assert buf == buf2, "round-trip 실패"
    print("class_dat self-test OK (round-trip byte-identical,", RECORD_COUNT, "records)")
