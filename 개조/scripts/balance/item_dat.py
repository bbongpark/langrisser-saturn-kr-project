#!/usr/bin/env python3
"""
item_dat.py — LANG2.BIN 안의 아이템/장비 데이터 코덱. (DerEditor 탭4 "道具数据")

위치:
  효과   LANG2.BIN offset 397276, 560B = 35레코드 × 16B (레코드당 효과슬롯 4개 × 4B)
  가격   LANG2.BIN offset 413750,  70B = 35레코드 × 2B  (빅엔디안 u16)

★ 정본: decompiled/DerEditor/Form1.cs LoadData4()(~2547)·button10_Click(~5707)
  radioButton10 분기. 실측 검증: 恶魔之斧(악마의 도끼)=AT+8/DF-3,
  奥丁之盾(오딘의 방패)=소환 슬레이프니르(오딘의 애마, 신화 일치),
  封印念珠(봉인염주)=소환 펜리르(봉인된 늑대, 신화 일치) — 값과 아이템 성격이
  전부 앞뒤가 맞아 필드 매핑을 강하게 뒷받침한다.

효과 슬롯(4바이트 × 최대 4개/아이템):
  +0  reserved     항상 0x00 관측(슬롯 사용 시) — 부호확장용 상위바이트로 추정
  +1  effect_type  효과 종류(아래 EFFECT_TYPES). 0xFF = 슬롯 미사용
  +2  reserved     value의 부호 확장 바이트(음수면 0xFF, 양수/0이면 0x00) — 인코딩 시 자동 계산
  +3  value        효과 수치(부호 있는 byte). type=9(소환)일 때는 소환수 인덱스

가격: 빅엔디안 u16, ×10 여부는 라벨에 "×10 P" 문구가 있으나 코드상 배율 처리를
      못 찾음 — **미확정**. 일단 raw 그대로(파일에 있는 값 그대로) 다룬다.

레코드 수: 560/16 = 70/2 = 35 (아이템 01~23(hex) — listBox3 순서, 1-based 표시).

⚠ `bytes17`(장비가능 병종 비트마스크)은 **SS(새턴)판에서 전혀 안 쓰인다** — PS1판
  전용 코드 경로에만 있다(실측 확인, ApplyData의 radioButton10 분기에 없음).
  즉 새턴판엔 "이 아이템을 어떤 병종만 장비 가능"이라는 제한 데이터 자체가 이
  구조에 없다(또는 CLASS.DAT 쪽에 통합돼 있을 가능성 — 미조사).
"""
from json_io import load_json, save_json  # noqa: F401

EFFECTS_OFFSET = 397276
EFFECTS_SIZE = 560
PRICE_OFFSET = 413750
PRICE_SIZE = 70
BIN_PATH = "LANG2.BIN"  # L1 오프셋 미검증

RECORD_COUNT = 35
SLOT_SIZE = 4
SLOTS_PER_ITEM = 4
ITEM_STRIDE = SLOT_SIZE * SLOTS_PER_ITEM
assert ITEM_STRIDE * RECORD_COUNT == EFFECTS_SIZE
assert 2 * RECORD_COUNT == PRICE_SIZE

EFFECT_TYPES = {
    0: "AT", 1: "DF", 2: "MV", 3: "cmd_range",
    4: "A_mod", 5: "D_mod", 6: "magic_range", 7: "magic_power",
    8: "magic_resist", 9: "summon",
}
NONE_TYPE = 0xFF


def decode(effects_region: bytes, price_region: bytes) -> list:
    assert len(effects_region) == EFFECTS_SIZE
    assert len(price_region) == PRICE_SIZE
    records = []
    for i in range(RECORD_COUNT):
        item_bytes = effects_region[i * ITEM_STRIDE:(i + 1) * ITEM_STRIDE]
        effects = []
        for s in range(SLOTS_PER_ITEM):
            slot = item_bytes[s * SLOT_SIZE:(s + 1) * SLOT_SIZE]
            etype = slot[1]
            if etype == NONE_TYPE:
                effects.append(None)
            else:
                raw = slot[3]
                value = raw - 256 if raw > 127 else raw
                effects.append({"type": etype, "type_name": EFFECT_TYPES.get(etype, f"unk_{etype}"), "value": value})
        price = int.from_bytes(price_region[i * 2:i * 2 + 2], "big")
        records.append({"index": i, "price": price, "effects": effects})
    return records


def encode(records: list) -> tuple:
    assert len(records) == RECORD_COUNT
    effects_out = bytearray(EFFECTS_SIZE)
    price_out = bytearray(PRICE_SIZE)
    for i, obj in enumerate(records):
        base = i * ITEM_STRIDE
        effects = obj["effects"]
        assert len(effects) == SLOTS_PER_ITEM, f"record {i}: effects는 슬롯 4개여야 함"
        for s, eff in enumerate(effects):
            slot_off = base + s * SLOT_SIZE
            if eff is None:
                effects_out[slot_off:slot_off + 4] = b"\xff\xff\xff\xff"
            else:
                v = eff["value"]
                if not (-128 <= v <= 127):
                    raise ValueError(f"record {i} slot {s} value {v} out of s8 range")
                raw = v & 0xFF
                sign_ext = 0xFF if v < 0 else 0x00
                effects_out[slot_off + 0] = 0x00
                effects_out[slot_off + 1] = eff["type"]
                effects_out[slot_off + 2] = sign_ext
                effects_out[slot_off + 3] = raw
        price = obj["price"]
        if not (0 <= price <= 0xFFFF):
            raise ValueError(f"record {i} price {price} out of u16 range")
        price_out[i * 2:i * 2 + 2] = price.to_bytes(2, "big")
    return bytes(effects_out), bytes(price_out)


if __name__ == "__main__":
    import random
    random.seed(0)
    eff = bytearray()
    for _ in range(RECORD_COUNT * SLOTS_PER_ITEM):
        if random.random() < 0.5:
            eff += b"\xff\xff\xff\xff"
        else:
            v = random.randint(-128, 127)
            eff += bytes([0x00, random.randint(0, 9), 0xFF if v < 0 else 0x00, v & 0xFF])
    eff = bytes(eff)
    price = bytes(random.randint(0, 255) for _ in range(PRICE_SIZE))
    recs = decode(eff, price)
    eff2, price2 = encode(recs)
    assert eff == eff2 and price == price2, "round-trip 실패"
    print("item_dat self-test OK (round-trip byte-identical,", RECORD_COUNT, "records)")
