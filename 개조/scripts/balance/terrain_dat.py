#!/usr/bin/env python3
"""
terrain_dat.py — LANG2.BIN 안의 지형 데이터 코덱. (DerEditor 탭10 "地形数据")

두 개의 서로 다른 버퍼를 하나로 묶는다(에디터의 radioButton6/7 두 모드에 대응):

1) 이동력(地形移动) — bytes14, offset 397836, 1044B = 18(병종) × 58(29지형×2바이트)
   ⚠ **2바이트 중 홀수 바이트만 SS(SSL2)가 쓴다** — 짝수 바이트는 다른 플랫폼
   (PS1 등) 전용 값이라 SS 게임 로직과 무관하지만, **디스크엔 실존하는 값**이라
   그대로 보존한다(모르는 값을 0으로 지우면 다른 플랫폼용 데이터가 깨진다 —
   우리는 SS만 쓰지만 파일 자체는 공유 구조이므로 원칙적으로 보존).
   값 0~254=이동에 드는 MV, 255=이동 불가.

2) 방어 보정(地形加成) — bytes15_1(지형 고유, 29B) + bytes15_2(병종별 지형 보정,
   522B = 18×29). offset 395808 / 406502.

★ 정본: decompiled/DerEditor/Form1.cs LoadData14()(~3528)·LoadData15()(~3546).
  실측 검증: 飞兵类(비행)·鬼魂类(유령)·龙族类(용족)는 대부분 지형에서 이동비용
  1~2로 균일(高壁/禁만 255), 반면 지상 병종은 山/水中/空/熔岩에서 255(이동불가)
  — 병종 성격과 완전히 일치. 방어보정도 城/王座=40(최고), 平地=5 등 합리적이고,
  궁병(弓兵类)만 森林/斜坡에서 추가 보정이 붙어 "엄폐 보너스"로 해석 가능.

지형 29종(순서, 인덱스 0~28):
  平地 荒地 道路 森林 斜坡 山 水中 城 地板 壁 屋内 神殿 王座 桥 吊桥 空 洞窟 熔岩
  墓地 船上 河上 屋顶 舷 沙地 街上 异次元 破坏 高壁 禁

병종 18종(순서, 인덱스 0~17 — CLASS.DAT의 `type` 필드 값과 같은 체계로 추정,
  1:1 검증은 안 함):
  步兵类 退魔类 枪兵类 骑兵类 特骑类 飞兵类 强盗类 水兵类 史莱姆 恶魔类
  海兽类 野伏类 法师类 鬼魂类 不死类 弓兵类 弩车类 龙族类
"""
from json_io import load_json, save_json  # noqa: F401

BIN_PATH = "LANG2.BIN"  # L1 오프셋 미검증

TERRAIN_NAMES = [
    "平地", "荒地", "道路", "森林", "斜坡", "山", "水中", "城", "地板", "壁",
    "屋内", "神殿", "王座", "桥", "吊桥", "空", "洞窟", "熔岩", "墓地", "船上",
    "河上", "屋顶", "舷", "沙地", "街上", "异次元", "破坏", "高壁", "禁",
]
UNIT_TYPE_NAMES = [
    "步兵类", "退魔类", "枪兵类", "骑兵类", "特骑类", "飞兵类", "强盗类", "水兵类",
    "史莱姆", "恶魔类", "海兽类", "野伏类", "法师类", "鬼魂类", "不死类", "弓兵类",
    "弩车类", "龙族类",
]
N_TERRAIN = len(TERRAIN_NAMES)
N_UNIT_TYPE = len(UNIT_TYPE_NAMES)
assert N_TERRAIN == 29 and N_UNIT_TYPE == 18

MOVE_OFFSET = 397836
MOVE_SIZE = 1044
MOVE_STRIDE = N_TERRAIN * 2  # 58
assert MOVE_STRIDE * N_UNIT_TYPE == MOVE_SIZE

TDEF_OFFSET = 395808   # 지형 고유 방어보정
TDEF_SIZE = N_TERRAIN
UDEF_OFFSET = 406502   # 병종별 지형 방어보정
UDEF_SIZE = N_UNIT_TYPE * N_TERRAIN
assert UDEF_SIZE == 522


def decode(move_region: bytes, tdef_region: bytes, udef_region: bytes) -> dict:
    assert len(move_region) == MOVE_SIZE
    assert len(tdef_region) == TDEF_SIZE
    assert len(udef_region) == UDEF_SIZE

    move_cost = []  # [unit_type][terrain] = {"cost": SS값, "reserved_even": 타 플랫폼값}
    for i in range(N_UNIT_TYPE):
        row = []
        for j in range(N_TERRAIN):
            base = i * MOVE_STRIDE + j * 2
            row.append({"cost": move_region[base + 1], "reserved_even": move_region[base]})
        move_cost.append(row)

    terrain_defense = list(tdef_region)  # [terrain] = u8
    unit_terrain_defense = [
        list(udef_region[i * N_TERRAIN:(i + 1) * N_TERRAIN]) for i in range(N_UNIT_TYPE)
    ]  # [unit_type][terrain] = u8

    return {
        "terrain_names": TERRAIN_NAMES,
        "unit_type_names": UNIT_TYPE_NAMES,
        "move_cost": move_cost,
        "terrain_defense": terrain_defense,
        "unit_terrain_defense": unit_terrain_defense,
    }


def encode(data: dict) -> tuple:
    move_out = bytearray(MOVE_SIZE)
    for i, row in enumerate(data["move_cost"]):
        assert len(row) == N_TERRAIN
        for j, cell in enumerate(row):
            base = i * MOVE_STRIDE + j * 2
            move_out[base] = cell["reserved_even"]
            move_out[base + 1] = cell["cost"]

    tdef = data["terrain_defense"]
    assert len(tdef) == N_TERRAIN
    tdef_out = bytes(tdef)

    udef_out = bytearray(UDEF_SIZE)
    for i, row in enumerate(data["unit_terrain_defense"]):
        assert len(row) == N_TERRAIN
        udef_out[i * N_TERRAIN:(i + 1) * N_TERRAIN] = bytes(row)

    return bytes(move_out), tdef_out, bytes(udef_out)


if __name__ == "__main__":
    import random
    random.seed(0)
    move = bytes(random.randint(0, 255) for _ in range(MOVE_SIZE))
    tdef = bytes(random.randint(0, 255) for _ in range(TDEF_SIZE))
    udef = bytes(random.randint(0, 255) for _ in range(UDEF_SIZE))
    data = decode(move, tdef, udef)
    m2, t2, u2 = encode(data)
    assert (move, tdef, udef) == (m2, t2, u2), "round-trip 실패"
    print("terrain_dat self-test OK (round-trip byte-identical,",
          N_UNIT_TYPE, "unit types x", N_TERRAIN, "terrains)")
