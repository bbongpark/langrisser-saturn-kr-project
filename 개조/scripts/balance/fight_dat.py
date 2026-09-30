#!/usr/bin/env python3
"""
fight_dat.py — LANG1/LANG2 FIGHT.DAT 중 "攻击方式"(공격 방식) 편집 영역 코덱.

DerEditor 탭2. FIGHT.DAT 파일 자체는 L1 10,534B / L2 10,599B이지만 에디터가
건드리는 건 그 안의 **255레코드 × 8바이트(offset 91부터, 2040바이트) 뿐**이다.
그 앞뒤(offset 0~90, 2131~끝)는 전투 공식 등 다른 데이터로 추정되며 미해독.

★ 정본: decompiled/DerEditor/Form1.cs LoadData2()(~2372) + InitializeComponent
  tabPage2 라벨 대조(label22~26, numericUpDown2~5, ~line 10329~10420).

레코드 오프셋(8바이트, CLASS.DAT과 같은 인덱스로 병종을 가리킴 — 즉 레코드 i는
CLASS.DAT 레코드 i와 같은 병종):
  0,1  reserved      용도 미상
  2    hitbox_w      占位宽度 (지도 위 점유 폭)
  3    hitbox_h      占位高度 (지도 위 점유 높이)
  4    vs_ground     对陆攻击 (대지 공격력/가능여부)
  5    vs_air        对空攻击 (대공 공격력/가능여부)
  6,7  reserved      용도 미상

레코드 수: 2040 / 8 = 255 (CLASS.DAT과 1:1 대응).
"""
RECORD_SIZE = 8
RECORD_COUNT = 255
REGION_OFFSET = 91  # FIGHT.DAT 파일 내 이 영역의 시작 오프셋
REGION_SIZE = RECORD_SIZE * RECORD_COUNT
assert REGION_SIZE == 2040

FIELDS = [
    (0, "reserved_0", "u8"),
    (1, "reserved_1", "u8"),
    (2, "hitbox_w", "u8"),
    (3, "hitbox_h", "u8"),
    (4, "vs_ground", "u8"),
    (5, "vs_air", "u8"),
    (6, "reserved_6", "u8"),
    (7, "reserved_7", "u8"),
]


def decode(region: bytes) -> list:
    assert len(region) == REGION_SIZE, f"영역은 2040바이트여야 함 (got {len(region)})"
    records = []
    for i in range(RECORD_COUNT):
        rec = region[i * RECORD_SIZE:(i + 1) * RECORD_SIZE]
        obj = {"index": i}
        for off, name, _kind in FIELDS:
            obj[name] = rec[off]
        records.append(obj)
    return records


def encode(records: list) -> bytes:
    assert len(records) == RECORD_COUNT
    out = bytearray(REGION_SIZE)
    for i, obj in enumerate(records):
        base = i * RECORD_SIZE
        for off, name, _kind in FIELDS:
            v = obj[name]
            if not (0 <= v <= 255):
                raise ValueError(f"record {i} field {name}={v} out of byte range")
            out[base + off] = v
    return bytes(out)


if __name__ == "__main__":
    import random
    random.seed(0)
    buf = bytes(random.randint(0, 255) for _ in range(REGION_SIZE))
    recs = decode(buf)
    buf2 = encode(recs)
    assert buf == buf2, "round-trip 실패"
    print("fight_dat self-test OK (round-trip byte-identical,", RECORD_COUNT, "records)")
