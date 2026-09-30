#!/usr/bin/env python3
"""
stage_dat.py — LANG2/SCEN.DAT 안의 스테이지별 유닛 배치 코덱. (DerEditor 탭9
"关卡数据"의 핵심 — listBox10, 92개 스테이지)

★★ 다른 balance 모듈과 구조가 다르다 ★★ — SCEN.DAT는 `bin_region`(고정 오프셋
구간)이 아니라 **`scen_tool.py`의 재귀 트리**(대사 텍스트가 사는 그 구조,
한글화가 이미 수만 번 검증한 코드)로 다룬다. 이 모듈은 register.py의 일반
파이프라인에 끼우지 않고 **`extract_stage.py`/`apply_stage.py` 전용 CLI**로
돌린다(SCEN.DAT 하나를 통째로 파싱/재조립해야 해서 다른 테이블과 배치가 다름).

## 위치를 찾는 법 (실측 검증됨)

`scen_tool.parse(SCEN.DAT)`의 루트 테이블 자식 108개 중 **`root.children[i]`
(i=0~91)가 곧 스테이지 i(1-based "剧本 i+1")의 레코드**다(DerEditor
`comboBox70.Items.Count==92`와 일치, 92개까지만 쓴다 — 92 이후 인덱스는
스테이지가 아닌 다른 데이터로 추정, 안 건드림). 그 레코드는 14개 자식을 가진
테이블이고, **`children[1]`이 압축된 "유닛 배치" 블롭**이다(children[0]은
다른 용도로 보이는 leaf, children[2]는 중첩 테이블, children[3~13]은 다른
leaf들 — 전부 이 모듈이 안 건드리는 미해독 영역).

## 압축 블롭 내부 구조 (`langr_compress.decode()`로 풀린 뒤)

8바이트 헤더: `[0]`아군턴음악 `[1]`적턴음악 `[2:4]`캐릭터목록offset(LE16)
`[4:6]`지휘관좌표offset(LE16) `[6:8]`유닛테이블offset(LE16, 보통 8).
`[6:8]`가 가리키는 위치부터 **44바이트 스트라이드 유닛 레코드**가 블롭 끝까지
반복된다(개수 = (blob길이 - 유닛테이블offset) // 44, 나머지는 항상 0 — 실측
92스테이지 전부 나머지 0 확인).

이 모듈은 **헤더+캐릭터목록+지휘관좌표 구간을 통째로 원본 그대로 보존**하고
(무엇을 하는지 확실치 않아서), **유닛 레코드(44B)만 필드 단위로 파싱/재조립**한다.

### 유닛 레코드 필드 (44바이트, ★ = 실측으로 값이 합리적임을 확인한 필드)

| off | 필드 | 확신도 |
|---|---|---|
| +0~3  | magic_flags (마법습득 32비트 플래그, 빅엔디안 추정) | 중간 |
| +4,+5 | trigger_flags_a/b (전투 트리거 관련) | 낮음(원시 바이트로만 보존) |
| +6    | ★ item1 (장비1, item_dat.py 인덱스) | 높음 |
| +7    | ★ item2 (장비2) | 높음 |
| +8    | ★ activity (AI 행동적극도) | 높음 |
| +9    | ★ cmd (지령: 전투/돌격/방어/수동) | 높음 |
| +10   | action_code (원시 HEX, 의미 미해독) | 낮음(원시 바이트로만 보존) |
| +11   | ★ faction_raw (진영: 우군/NPC/적/적2) | 높음 |
| +12   | atk_target | 중간 |
| +13,14| dest_x, dest_y (AI 이동 목적지) | 중간 |
| +15   | chr_target (인물 지정 타겟) | 중간 |
| +16   | reserved_16 | 미상 |
| +17   | ★ LV | 높음 |
| +18   | ★ EXP | 높음 |
| +19   | ★ MP | 높음 |
| +20   | ★ MAXMP | 높음 |
| +21   | ★ AT | 높음 |
| +22   | ★ DF | 높음 |
| +23,24| ★ pos_x, pos_y (배치좌표, 255,255=미배치/증원대기) | 높음 |
| +25   | ★ name_id (캐릭터명 ID, 256종) | 높음 |
| +26   | reserved_26 | 미상 |
| +27   | ★ class_id (CLASS.DAT류 인덱스, 254종) | 높음 |
| +28   | ★ portrait (초상화 ID) | 높음 |
| +29,30| reserved_29/30 | 미상 |
| +31,33,35,37,39,41 | merc1~6 (용병 관련, comboBox77~82) | 낮음(원시 보존) |
| +32,34,36,38,40,42,43 | reserved | 미상 |

★ 표시 필드(스탯·장비·AI·좌표·배치)만 밸런스 튜닝에 신뢰하고 써라. 나머지는
"원본값 그대로 보존"만 되고 의미는 모른다 — JSON에 raw byte로 나오니 필요하면
직접 바꿔볼 수는 있지만 무슨 효과가 날지 모른다.

⛔ **유닛 개수는 못 바꾼다**(늘리거나 줄이면 블롭 내부 오프라인 사용자석/후속
데이터가 깨질 수 있다 — 값 편집만 지원). 헤더/캐릭터목록/지휘관좌표 구간도
안 바꾼다.

⚠ 압축은 이번 세션에 새로 짠 인코더(`langr_compress.py`)를 쓴다 — 원본
압축기와 바이트가 다를 수 있지만 decode(encode(x))==x 는 92스테이지 전부
검증됨. 압축률도 원본과 비슷하거나 더 낫다(실측 0.96x).
"""
import langr_compress

UNIT_STRIDE = 44

UNIT_FIELDS = [
    # (offset, name, size_in_bytes)  size>1 는 여러 바이트를 하나의 필드로 묶음
    (6, "item1", 1), (7, "item2", 1), (8, "activity", 1), (9, "cmd", 1),
    (10, "action_code", 1), (11, "faction_raw", 1), (12, "atk_target", 1),
    (13, "dest_x", 1), (14, "dest_y", 1), (15, "chr_target", 1),
    (16, "reserved_16", 1),
    (17, "LV", 1), (18, "EXP", 1), (19, "MP", 1), (20, "MAXMP", 1),
    (21, "AT", 1), (22, "DF", 1),
    (23, "pos_x", 1), (24, "pos_y", 1), (25, "name_id", 1),
    (26, "reserved_26", 1), (27, "class_id", 1), (28, "portrait", 1),
    (29, "reserved_29", 1), (30, "reserved_30", 1),
    (31, "merc1", 1), (32, "reserved_32", 1), (33, "merc2", 1), (34, "reserved_34", 1),
    (35, "merc3", 1), (36, "reserved_36", 1), (37, "merc4", 1), (38, "reserved_38", 1),
    (39, "merc5", 1), (40, "reserved_40", 1), (41, "merc6", 1),
    (42, "reserved_42", 1), (43, "reserved_43", 1),
]


def _parse_unit(rec: bytes) -> dict:
    obj = {"magic_flags": int.from_bytes(rec[0:4], "big"),
           "trigger_flags_a": rec[4], "trigger_flags_b": rec[5]}
    for off, name, _sz in UNIT_FIELDS:
        obj[name] = rec[off]
    return obj


def _pack_unit(obj: dict) -> bytes:
    rec = bytearray(UNIT_STRIDE)
    rec[0:4] = int(obj["magic_flags"]).to_bytes(4, "big")
    rec[4] = obj["trigger_flags_a"]
    rec[5] = obj["trigger_flags_b"]
    for off, name, _sz in UNIT_FIELDS:
        v = obj[name]
        if not (0 <= v <= 255):
            raise ValueError(f"unit field {name}={v} out of byte range")
        rec[off] = v
    return bytes(rec)


def decode_stage(leaf_raw: bytes) -> dict:
    """leaf_raw = scen_tool 리프 노드의 raw bytes (압축된 블롭 그대로)."""
    blob = langr_compress.decode(leaf_raw)
    # blob[6:8](=iAddr2, 헤더의 세 번째 LE16)는 유닛테이블 시작보다 1바이트 앞을
    # 가리킨다 — 실측(_tab9_probe.py: base = iAddr2 + 1)과 정확히 일치시켰다.
    unit_table_off = int.from_bytes(blob[6:8], "little") + 1
    body = blob[unit_table_off:]
    n_units, remainder = divmod(len(body), UNIT_STRIDE)
    units = [_parse_unit(body[k * UNIT_STRIDE:(k + 1) * UNIT_STRIDE]) for k in range(n_units)]
    return {
        "blob_len": len(blob),
        "orig_compressed_len": len(leaf_raw),
        "prefix_hex": blob[:unit_table_off].hex(),
        "n_units": n_units,
        "remainder_hex": body[n_units * UNIT_STRIDE:].hex() if remainder else "",
        "units": units,
    }


def _rebuild_blob(data: dict) -> bytes:
    prefix = bytes.fromhex(data["prefix_hex"])
    units = data["units"]
    if len(units) != data["n_units"]:
        raise ValueError(
            f"유닛 개수를 {data['n_units']}→{len(units)}로 바꿀 수 없다(값만 편집 가능)"
        )
    body = b"".join(_pack_unit(u) for u in units)
    remainder = bytes.fromhex(data["remainder_hex"]) if data["remainder_hex"] else b""
    blob = prefix + body + remainder
    assert len(blob) == data["blob_len"], "blob_len이 재조립 결과와 안 맞음(내부 버그)"
    return blob


def unchanged(leaf_raw: bytes, data: dict) -> bool:
    """이 스테이지가 JSON에서 실제로 편집됐는지 확인한다(압축 결과가 원본과
    달라도 **압축 해제한 내용**이 같으면 미편집으로 본다) — apply_stage.py가
    이걸로 손 안 댄 스테이지의 원본 압축 바이트를 그대로 보존해 디스크 변경
    범위를 최소화한다."""
    return langr_compress.decode(leaf_raw) == _rebuild_blob(data)


def encode_stage(data: dict) -> bytes:
    """반환값 = 압축된 블롭 bytes (scen_tool 리프의 새 raw), **원본과 정확히
    같은 길이로 0바이트 패딩**한다 — SCEN.DAT 전체 파일 크기가 디스크에 고정
    (LBA 재배치 없이 같은 크기로만 패치 가능, disc_tool.write_file 제약)이라
    leaf 하나하나의 압축 크기가 바뀌면 안 되기 때문이다.

    패딩이 안전한 이유: 압축 스트림은 "01+111111"(스트림 종료 마커)로 끝나고
    decode()는 그 마커를 만나는 즉시 멈춘다 — 마커 뒤에 뭘 붙이든 디코더가
    아예 안 읽는다(92개 실제 스테이지 전부 이 인코더가 원본과 같거나 더 작게
    압축함을 확인했다 — 8절/self-test 참고, 그래서 패딩만으로 충분하다).

    새 압축 결과가 원본보다 **크면** 에러를 낸다(패딩으로 못 줄인다) — 그런
    경우는 이 유닛의 편집 내용을 좀 더 단순하게(반복되는 값 위주로) 바꾸거나
    다음 세션에서 SCEN.DAT 전체 재배치 로직을 만들어야 한다.
    """
    blob = _rebuild_blob(data)
    compressed = langr_compress.encode(blob)
    target = data["orig_compressed_len"]
    if len(compressed) > target:
        raise ValueError(
            f"압축 결과({len(compressed)}B)가 원본 압축 크기({target}B)보다 커서 "
            "이 스테이지는 이대로 반영할 수 없다 — 편집을 줄이거나 다른 값으로 시도해봐라."
        )
    return compressed + b"\x00" * (target - len(compressed))


STAGE_COUNT = 92


def leaf_path(stage_idx: int) -> tuple:
    """scen_tool 트리에서 스테이지 stage_idx(0-based)의 압축 블롭 리프 경로."""
    if not (0 <= stage_idx < STAGE_COUNT):
        raise ValueError(f"stage_idx는 0~{STAGE_COUNT-1} 사이여야 함")
    return (stage_idx, 1)


if __name__ == "__main__":
    import random
    random.seed(0)
    prefix = bytearray(random.randint(0, 255) for _ in range(8))
    prefix[6:8] = (7).to_bytes(2, "little")  # iAddr2+1 must equal prefix length (8)
    prefix = bytes(prefix)
    units = []
    for _ in range(5):
        u = {"magic_flags": random.randint(0, 2**32 - 1),
             "trigger_flags_a": random.randint(0, 255), "trigger_flags_b": random.randint(0, 255)}
        for off, name, _sz in UNIT_FIELDS:
            u[name] = random.randint(0, 255)
        units.append(u)
    blob = prefix + b"".join(_pack_unit(u) for u in units)
    leaf_raw = langr_compress.encode(blob)

    data = decode_stage(leaf_raw)
    assert data["n_units"] == 5
    re_leaf = encode_stage(data)
    back = langr_compress.decode(re_leaf)
    assert back == blob, "round-trip 실패(무편집)"

    data["units"][0]["AT"] = 77
    edited_leaf = encode_stage(data)
    edited_blob = langr_compress.decode(edited_leaf)
    reparsed = decode_stage(edited_leaf)
    assert reparsed["units"][0]["AT"] == 77
    assert reparsed["units"][1] == data["units"][1]
    print("stage_dat self-test OK (round-trip + 단일 필드 편집 정확)")
