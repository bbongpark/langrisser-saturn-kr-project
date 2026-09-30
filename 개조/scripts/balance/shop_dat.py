#!/usr/bin/env python3
"""
shop_dat.py — LANG2.BIN 안의 상점 판매 목록 코덱. (DerEditor 탭8 "商店数据")

위치: LANG2.BIN offset 413004, 276바이트 = 27개 상점, **가변 길이** 레코드.
      각 바이트 = 그 슬롯에서 파는 아이템의 인덱스(0=없음/빈 슬롯, 1~0x23=
      item_dat.py의 아이템 인덱스+1 — CLASS.DAT류와 같은 "raw = idx+1" 관례로 추정,
      1:1 정확한 대조는 아직 안 함).

★ 정본: decompiled/DerEditor/Form1.cs LoadAllData3()(~1811)·ApplyData() SS 분기
  (~4221). 실측 검증: 27개 레코드가 전부 무기 진행표로 말이 되고(초반 상점=칼/
  방패류, 후반=지팡이/성십자가/장궁 등), 마지막 2개(인덱스25·26)는 각각 24·36
  아이템을 담은 "商店秘籍"(디버그/치트용 전체 아이템 상점)라 유독 큼 —
  이름·구조가 앞뒤가 맞는다.

**경계표(고정, 바꾸면 안 됨)** — 상점 i는 [SHOP_BOUNDARIES[i] : SHOP_BOUNDARIES[i+1]]:
  0,4,8,12,20,28,32,40,44,56,64,76,84,96,104,116,128,140,148,156,
  164,176,188,196,204,216,240,276
→ 27개 상점, 슬롯 수 4~36개(가변). **슬롯 개수 자체는 못 늘리고 못 줄인다**
  (파일 전체 크기 276바이트 고정) — 슬롯 안 내용(어떤 아이템을 파는지)만 바꿀 수 있다.

⛔ **게임은 경계표가 아니라 0(빈슬롯)을 만날 때까지 읽는다** (2026-08 실기 확인:
  상점0의 4슬롯을 전부 채웠더니 다음 상점의 아이템까지 이어서 표시됨). 따라서
  **각 상점의 마지막 슬롯은 반드시 0으로 남겨야 한다** — 실제 판매 가능 아이템 수는
  (슬롯 수 − 1)개. 원본 27개 상점 전부 끝에 0이 최소 1개 있는 것도 이 때문이다.

comboBox62 목록 순서 = 시나리오 그룹(같은 상점을 공유하는 챕터 묶음). 마지막 2개
(인덱스25="商店秘籍1", 26="商店秘籍2")는 디버그용으로 보이며 밸런스 편집 대상이
아닐 가능성이 높다(건드려도 되지만 일반 플레이 경로에 안 나올 수 있음 — 미확인).

⚠ 탭7 "转职高级修改"(전직 고급 수정)은 **SS(새턴)판에 대응 코드가 아예 없다**
  (실측 확인 — PS1 전용 기능). 그래서 이 프로젝트엔 관련 코덱을 안 만든다.
"""
from json_io import load_json, save_json  # noqa: F401

BIN_PATH = "LANG2.BIN"  # L1 오프셋 미검증
OFFSET = 413004
SIZE = 276

SHOP_BOUNDARIES = [
    0, 4, 8, 12, 20, 28, 32, 40, 44, 56, 64, 76, 84, 96, 104, 116,
    128, 140, 148, 156, 164, 176, 188, 196, 204, 216, 240, 276,
]
SHOP_COUNT = len(SHOP_BOUNDARIES) - 1
assert SHOP_BOUNDARIES[-1] == SIZE
assert SHOP_COUNT == 27


def decode(region: bytes) -> list:
    assert len(region) == SIZE, f"영역은 {SIZE}바이트여야 함 (got {len(region)})"
    shops = []
    for i in range(SHOP_COUNT):
        lo, hi = SHOP_BOUNDARIES[i], SHOP_BOUNDARIES[i + 1]
        shops.append({"index": i, "slots": list(region[lo:hi])})
    return shops


def encode(shops: list) -> bytes:
    assert len(shops) == SHOP_COUNT
    out = bytearray(SIZE)
    for i, obj in enumerate(shops):
        lo, hi = SHOP_BOUNDARIES[i], SHOP_BOUNDARIES[i + 1]
        expected_len = hi - lo
        slots = obj["slots"]
        if len(slots) != expected_len:
            raise ValueError(
                f"shop {i}: 슬롯 수가 {expected_len}개여야 하는데 {len(slots)}개 — "
                "이 상점의 슬롯 수는 늘리거나 줄일 수 없다(파일 크기 고정)"
            )
        for v in slots:
            if not (0 <= v <= 255):
                raise ValueError(f"shop {i} slot value {v} out of byte range")
        out[lo:hi] = bytes(slots)
    return bytes(out)


if __name__ == "__main__":
    import random
    random.seed(0)
    buf = bytes(random.randint(0, 255) for _ in range(SIZE))
    shops = decode(buf)
    buf2 = encode(shops)
    assert buf == buf2, "round-trip 실패"
    print("shop_dat self-test OK (round-trip byte-identical,", SHOP_COUNT, "shops)")
