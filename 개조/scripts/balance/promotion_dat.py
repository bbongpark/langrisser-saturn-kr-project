#!/usr/bin/env python3
"""
promotion_dat.py — LANG2.BIN 안의 캐릭터별 승급(전직) 목록 코덱.
(DerEditor 탭6 "转职数据"의 핵심 테이블만 — 8절 "범위" 참고)

**하나의 연속 구간**으로 다룬다: LANG2.BIN offset 398880부터 1,029바이트
(offset 398880~399908) — 승급 슬롯 데이터(956B) 바로 뒤에 그 슬롯들을 가리키는
포인터 테이블(72B = 18명×4B, offset 399837부터)이 붙어있어 한 번에 읽고 쓴다.

18명 캐릭터 각각의 "승급 슬롯 목록"이 이 안에 흩어져 있다 — **레코드 순서가
캐릭터 순서와 무관하고(포인터로만 위치를 찾음), 슬롯 개수도 캐릭터마다
다르다(11~19개, 2명은 0개)**.

★ 정본: decompiled/DerEditor/Form1.cs LoadData7()(~2930)·LoadData8()(~3247)·
  ApplyData() radioButton10 분기. 이번 세션에 포인터 공식과 종료자를 실측
  재검증했다(18명 전원 확인, 예외 없음):

  포인터: 이 구간 상대offset `957+i*4`(i=0..17)의 3바이트 빅엔디안 값 −
  464416 = 캐릭터 i의 슬롯 목록이 시작하는 **이 구간 안** 상대 오프셋(0~955).
  **캐릭터 순서대로 오름차순이 아니다**(예: 캐릭터9가 캐릭터0~8보다 앞선
  offset 144에서 시작) — "다음 포인터까지"로 길이를 재면 틀린다. 대신
  **4바이트씩 읽다가 `FF FF FF FF`를 만나면 그 캐릭터의 끝**이다.

  슬롯(4바이트): [+0]예비(관측상 항상 0x00) [+1]소스 병종ID+1 [+2]팔레트(0/1)
  [+3]타깃 병종ID(원값, +1 없음 — CLASS.DAT 인덱스 그대로)

⚠⚠ **"raw 전체 블롭 + 슬롯별 덮어쓰기" 방식이다.** 1,029바이트 전체를 원본
  hex로 JSON에 저장해두고, 인코딩할 때 그 원본 위에 슬롯 4바이트만 정확히
  제자리에 다시 써넣는다 — 슬롯 사이·캐릭터 사이의 "미지의 여유 공간"(원본
  조사에서 발견됨, 용도 불명)과 포인터 테이블 자체는 **절대 안 건드린다**.
  `raw_hex`는 참고용으로 JSON에 들어있을 뿐 손으로 고치면 안 된다 — 편집은
  `characters[i].promotions[j].target_class` 같은 파싱된 필드만 바꾸면
  `encode()`가 알아서 정확한 자리에만 반영한다.

⛔ **슬롯 개수는 못 바꾼다**(늘리면 다음 데이터를 덮어쓰고, 줄이면 뒷부분이
  쓰레기값으로 남는다) — `encode()`가 슬롯 개수 불일치 시 에러를 낸다.
⛔ **`bytes7`(체크포인트/전직 가능 목록, offset 413824)는 이 모듈이 다루지
  않는다** — bytes8과 어떤 관계인지(단순 UI 캐시인지 게임 로직도 참조하는지)
  확인 안 됐다. 여기만 바꿔서 실기로 테스트해보고, 전직 메뉴에 이상이 있으면
  bytes7도 봐야 한다는 뜻이다.

레코드 수: 18명(캐릭터 인덱스는 character_dat.py와 동일한 0~17, 艾尔文~奥斯特).
"""
from json_io import load_json, save_json  # noqa: F401

BIN_PATH = "LANG2.BIN"  # L1 오프셋 미검증
REGION_OFFSET = 398880
PROMO_SIZE = 956
PTR_TABLE_REL_OFFSET = 957   # 이 구간 안에서 포인터 테이블이 시작하는 상대 위치
PTR_TABLE_BIAS = 464416
CHAR_COUNT = 18
REGION_SIZE = PTR_TABLE_REL_OFFSET + CHAR_COUNT * 4  # 1029
TERMINATOR = b"\xff\xff\xff\xff"


def _read_pointers(region: bytes) -> list:
    out = []
    for i in range(CHAR_COUNT):
        off = PTR_TABLE_REL_OFFSET + i * 4
        v = int.from_bytes(region[off:off + 3], "big") - PTR_TABLE_BIAS
        out.append(v)
    return out


def _scan_slots(region: bytes, start: int) -> list:
    offsets = []
    pos = start
    while pos + 4 <= PROMO_SIZE:
        if region[pos:pos + 4] == TERMINATOR:
            return offsets
        offsets.append(pos)
        pos += 4
    raise ValueError(f"start={start}: 종료자(FFFFFFFF)를 못 찾고 승급영역 끝에 도달함")


def decode(region: bytes) -> dict:
    assert len(region) == REGION_SIZE, f"영역은 {REGION_SIZE}바이트여야 함 (got {len(region)})"
    pointers = _read_pointers(region)
    characters = []
    for i, start in enumerate(pointers):
        slot_offsets = _scan_slots(region, start)
        promotions = [{
            "region_offset": off,
            "reserved": region[off],
            "source_class": region[off + 1] - 1,
            "palette": region[off + 2],
            "target_class": region[off + 3],
        } for off in slot_offsets]
        characters.append({"index": i, "start": start, "promotions": promotions})
    return {"raw_hex": region.hex(), "characters": characters}


def encode(data: dict) -> bytes:
    out = bytearray.fromhex(data["raw_hex"])
    assert len(out) == REGION_SIZE, f"raw_hex 길이가 {REGION_SIZE}바이트가 아니다"

    orig_pointers = _read_pointers(out)
    for ch in data["characters"]:
        idx = ch["index"]
        orig_offsets = _scan_slots(bytes(out), orig_pointers[idx])
        promos = ch["promotions"]
        if len(promos) != len(orig_offsets):
            raise ValueError(
                f"character {idx}: 슬롯 개수를 {len(orig_offsets)}→{len(promos)}로 "
                "바꿀 수 없다(다른 캐릭터 데이터를 덮어씀)"
            )
        for p, off in zip(promos, orig_offsets):
            src = p["source_class"] + 1
            vals = {"reserved": p["reserved"], "source_class+1": src,
                    "palette": p["palette"], "target_class": p["target_class"]}
            for name, v in vals.items():
                if not (0 <= v <= 255):
                    raise ValueError(f"character {idx} slot@{off}: {name}={v} out of byte range")
            out[off + 0] = p["reserved"]
            out[off + 1] = src
            out[off + 2] = p["palette"]
            out[off + 3] = p["target_class"]
    return bytes(out)


if __name__ == "__main__":
    # self-test: 포인터 뒤섞임 + 가변길이 + 종료자 + 캐릭터 사이 여유공간을
    # 흉내낸 합성 데이터로 round-trip과 단일 슬롯 편집을 검증한다.
    import random
    random.seed(0)
    promo = bytearray(b"\xff" * PROMO_SIZE)
    pointers = []
    pos = 0
    for i in range(CHAR_COUNT):
        n = random.randint(0, 5)
        if pos + n * 4 + 4 > PROMO_SIZE:
            n = 0
        pointers.append(pos)
        for _ in range(n):
            promo[pos:pos + 4] = bytes([0, random.randint(1, 255), 0, random.randint(1, 255)])
            pos += 4
        promo[pos:pos + 4] = TERMINATOR
        pos += 4 + random.randint(0, 3)
        pos = min(pos, PROMO_SIZE - 4)
    region = bytearray(REGION_SIZE)
    region[0:PROMO_SIZE] = promo
    for i, p in enumerate(pointers):
        off = PTR_TABLE_REL_OFFSET + i * 4
        region[off:off + 3] = (p + PTR_TABLE_BIAS).to_bytes(3, "big")
    region = bytes(region)

    data = decode(region)
    out = encode(data)
    assert out == region, "round-trip 실패(무편집)"

    for ch in data["characters"]:
        if ch["promotions"]:
            ch["promotions"][0]["target_class"] = 200
            break
    edited = encode(data)
    diff = sum(1 for a, b in zip(region, edited) if a != b)
    assert diff == 1, f"딱 1바이트만 바뀌어야 하는데 {diff}바이트 바뀜"
    print("promotion_dat self-test OK (round-trip byte-identical, 1-byte 편집도 정확)")
