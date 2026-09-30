#!/usr/bin/env python3
"""
character_dat.py — LANG2.BIN 안의 등장인물(주요 캐릭터) 데이터 코덱.
(DerEditor 탭5 "登场数据")

위치:
  bytes3  LANG2.BIN offset 397200, 72B  = 18레코드 × 4B  (초기 스탯 보정치)
  bytes6  LANG2.BIN offset 400432, 360B = 18레코드 × 20B (초기 직업·레벨·마법 등)

18명 = 艾尔文(Elwin)~奥斯特(Oist), `listBox5.Items` 순서(SS/새턴판 한정 —
다른 플랫폼은 19번째 雷亚德(Reard)가 더 있으나 새턴판은 플랫폼 제약으로 없음).

★ 정본: decompiled/DerEditor/Form1.cs LoadData3()(~2396)·LoadData6()(~2805)·
  ApplyData() radioButton10 분기. 실측 검증: 성별 필드가 실제 캐릭터 성별과
  전원 일치, 마법 비트마스크가 마법사 계열 캐릭터에서만 켜짐, 용병 종류 ID가
  strSoldiercn2 목록과 정확히 대응 — 강한 확증.

⚠⚠ **DerEditor 자체 버그 주의(이 코덱은 그 버그를 재현하지 않는다)**: 원본
  에디터는 `bytes3`를 로드할 때 72바이트 중 **54바이트만** 메모리에 채우고
  저장할 때는 72바이트 전체를 되쓴다 — 그 결과 레코드15~17(艾格贝尔特·艾斯特·
  奥斯特)의 뒷부분이 저장 시 0으로 덮어써진다(디스크엔 원래 0이 아닌 실데이터가
  있음, 실측 확인). 이 모듈은 `bin_region`으로 **72바이트 전체를 항상 온전히
  읽고 쓰므로** 이 손실이 없다 — 단, DerEditor로 만든 결과물과 대조할 땐 이
  차이를 염두에 둘 것.

bytes3 레코드(4바이트) — "초기 스탯 보정":
  +0  A_mod       공격력 보정치
  +1  D_mod       방어력 보정치
  +2  MV_bonus    이동력 보너스
  +3  unknown_3   UI 미노출, 디스크엔 값 존재(용도 미상 — 건드리지 말고 보존만)

bytes6 레코드(20바이트) — "초기 상태":
  +0   reserved_0     SS는 0 고정 관측
  +1   class_raw      초기 직업 인덱스인데 raw-1이 CLASS.DAT 인덱스(즉 저장값=класс+1)
  +2   MP             초기 MP
  +3   LV             초기 레벨
  +4   EXP            초기 경험치(하위 바이트)
  +5   AT             초기 공격력
  +6   DF             초기 방어력
  +7   reserved_7     용도 미상(SS UI 미참조)
  +8..+11  magic_flags  습득 마법 32비트 플래그, **빅엔디안**(SS 전용 — 다른
                        플랫폼은 리틀엔디안이라 그대로 재사용 금지)
  +12  gender         0=남 / 1=여
  +13  reserved_13    SS는 건너뜀(용도 미상)
  +14  portrait       초상화 인덱스로 추정(FACE.DAT 대조 안 함 — 확신도 중간)
  +15  merc_count     초기 용병(호위) 슬롯 수
  +16  reserved_16    SS는 건너뜀
  +17  merc1_raw      용병1 병종 ID, raw-119(0x77)이 CLASS.DAT류 인덱스
  +18  reserved_18    SS 미사용(PC판의 용병2 슬롯으로 추정)
  +19  reserved_19    용도 미상, 확신도 낮음

레코드 수: 72/4 = 360/20 = 18.
"""
from json_io import load_json, save_json  # noqa: F401

STATS_OFFSET = 397200
STATS_SIZE = 72
STATS_STRIDE = 4

INIT_OFFSET = 400432
INIT_SIZE = 360
INIT_STRIDE = 20

BIN_PATH = "LANG2.BIN"  # L1 오프셋 미검증
RECORD_COUNT = 18
assert STATS_STRIDE * RECORD_COUNT == STATS_SIZE
assert INIT_STRIDE * RECORD_COUNT == INIT_SIZE

CLASS_RAW_BIAS = 1     # class = class_raw - 1
MERC_RAW_BIAS = 0x77   # merc1 = merc1_raw - 0x77


def decode(stats_region: bytes, init_region: bytes) -> list:
    assert len(stats_region) == STATS_SIZE
    assert len(init_region) == INIT_SIZE
    records = []
    for i in range(RECORD_COUNT):
        s = stats_region[i * STATS_STRIDE:(i + 1) * STATS_STRIDE]
        n = init_region[i * INIT_STRIDE:(i + 1) * INIT_STRIDE]
        records.append({
            "index": i,
            "A_mod": s[0],
            "D_mod": s[1],
            "MV_bonus": s[2],
            "unknown_3": s[3],
            "reserved_0": n[0],
            "class_raw": n[1],
            "class": n[1] - CLASS_RAW_BIAS,
            "MP": n[2],
            "LV": n[3],
            "EXP": n[4],
            "AT": n[5],
            "DF": n[6],
            "reserved_7": n[7],
            "magic_flags": int.from_bytes(n[8:12], "big"),
            "gender": n[12],
            "reserved_13": n[13],
            "portrait": n[14],
            "merc_count": n[15],
            "reserved_16": n[16],
            "merc1_raw": n[17],
            "merc1": n[17] - MERC_RAW_BIAS if n[17] >= MERC_RAW_BIAS else None,
            "reserved_18": n[18],
            "reserved_19": n[19],
        })
    return records


def encode(records: list) -> tuple:
    assert len(records) == RECORD_COUNT
    stats_out = bytearray(STATS_SIZE)
    init_out = bytearray(INIT_SIZE)
    for i, o in enumerate(records):
        sb = i * STATS_STRIDE
        stats_out[sb + 0] = o["A_mod"]
        stats_out[sb + 1] = o["D_mod"]
        stats_out[sb + 2] = o["MV_bonus"]
        stats_out[sb + 3] = o["unknown_3"]

        nb = i * INIT_STRIDE
        init_out[nb + 0] = o["reserved_0"]
        init_out[nb + 1] = o["class_raw"]
        init_out[nb + 2] = o["MP"]
        init_out[nb + 3] = o["LV"]
        init_out[nb + 4] = o["EXP"]
        init_out[nb + 5] = o["AT"]
        init_out[nb + 6] = o["DF"]
        init_out[nb + 7] = o["reserved_7"]
        init_out[nb + 8:nb + 12] = int(o["magic_flags"]).to_bytes(4, "big")
        init_out[nb + 12] = o["gender"]
        init_out[nb + 13] = o["reserved_13"]
        init_out[nb + 14] = o["portrait"]
        init_out[nb + 15] = o["merc_count"]
        init_out[nb + 16] = o["reserved_16"]
        init_out[nb + 17] = o["merc1_raw"]
        init_out[nb + 18] = o["reserved_18"]
        init_out[nb + 19] = o["reserved_19"]
    return bytes(stats_out), bytes(init_out)


if __name__ == "__main__":
    import random
    random.seed(0)
    stats = bytes(random.randint(0, 255) for _ in range(STATS_SIZE))
    init = bytes(random.randint(0, 255) for _ in range(INIT_SIZE))
    recs = decode(stats, init)
    s2, n2 = encode(recs)
    assert stats == s2 and init == n2, "round-trip 실패"
    print("character_dat self-test OK (round-trip byte-identical,", RECORD_COUNT, "records)")
