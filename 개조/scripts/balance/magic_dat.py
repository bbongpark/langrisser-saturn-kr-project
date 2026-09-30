#!/usr/bin/env python3
"""
magic_dat.py — LANG1/LANG2.BIN 안의 마법(魔法) 데이터 코덱. (DerEditor 탭3 "魔法数据")

위치: LANG2.BIN offset 397016, 104바이트 = 26레코드 × 4바이트.
      (파일에 실제로 쓰이는 건 108바이트지만 게임이 읽는 건 104바이트뿐 —
      마지막 4바이트는 이 테이블 소속이 아닌 인접 데이터로 보여 건드리지 않는다.)

★ 정본: decompiled/DerEditor/Form1.cs LoadData9()·ApplyData()의 radioButton10 분기.
  bytes9 버퍼, `Array.Copy(bytes0, 397016, bytes9, 0, 104)`로 로드.
  실측 검증: 진영 필드(공격계=적방/회복계=아군)가 마법 성격과 완벽히 일치,
  MP소모 1~12 합리적 범위, 순간이동만 사거리 16으로 유독 커 이동계로 설명됨.

레코드(4바이트):
  +0        range       魔法射程 — 마법 사거리
  +1 bit7   must_target 必须选定对象 — 시전 전 목표 지정 필수(1) / 자동·범위(0)
  +1 bit0-6 aoe         波及范围 — 파급 범위(0~127)
  +2        mp_cost     魔法消耗 — MP 소모량
  +3        faction     友方/敌方 — 대상 진영(0=아군 대상 / 1=적군 대상)

레코드 수: 104 / 4 = 26.

⚠ 마법 이름은 파일에 없다(코드에 하드코딩된 strMagicjp1/2 배열 + 우리 쪽 번역
  텍스트에 있음, 이 모듈이 다루는 범위 밖). JSON엔 index만 있으니 어떤 마법인지는
  게임 내 마법 목록 순서(0=마법의 화살, 1=충격파, … 순서로 추정, 미확정)로 대조해라.
"""
REGION_OFFSET = 397016
RECORD_SIZE = 4
RECORD_COUNT = 26
REGION_SIZE = RECORD_SIZE * RECORD_COUNT
assert REGION_SIZE == 104
BIN_PATH = "LANG2.BIN"  # L1은 LANG1.BIN — 오프셋 별도 확인 필요(미검증, 8절 참고)


def decode(region: bytes) -> list:
    assert len(region) == REGION_SIZE, f"영역은 104바이트여야 함 (got {len(region)})"
    records = []
    for i in range(RECORD_COUNT):
        rec = region[i * RECORD_SIZE:(i + 1) * RECORD_SIZE]
        b1 = rec[1]
        records.append({
            "index": i,
            "range": rec[0],
            "must_target": (b1 >> 7) & 1,
            "aoe": b1 & 0x7F,
            "mp_cost": rec[2],
            "faction": rec[3],
        })
    return records


def encode(records: list) -> bytes:
    assert len(records) == RECORD_COUNT
    out = bytearray(REGION_SIZE)
    for i, obj in enumerate(records):
        base = i * RECORD_SIZE
        aoe = obj["aoe"]
        if not (0 <= aoe <= 127):
            raise ValueError(f"record {i} aoe={aoe} out of 0..127")
        b1 = ((obj["must_target"] & 1) << 7) | aoe
        for off, v in ((0, obj["range"]), (1, b1), (2, obj["mp_cost"]), (3, obj["faction"])):
            if not (0 <= v <= 255):
                raise ValueError(f"record {i} offset {off} value {v} out of byte range")
            out[base + off] = v
    return bytes(out)


if __name__ == "__main__":
    import random
    random.seed(0)
    buf = bytearray(random.randint(0, 255) for _ in range(REGION_SIZE))
    for i in range(RECORD_COUNT):
        buf[i * 4 + 1] &= 0x7F  # aoe 필드는 7비트만 유효 — 라운드트립 위해 상위비트 제거
    buf = bytes(buf)
    recs = decode(buf)
    buf2 = encode(recs)
    assert buf == buf2, "round-trip 실패"
    print("magic_dat self-test OK (round-trip byte-identical,", RECORD_COUNT, "records)")
