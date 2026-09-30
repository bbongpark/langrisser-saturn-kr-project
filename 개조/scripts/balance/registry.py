#!/usr/bin/env python3
"""
registry.py — 해독된 밸런스 데이터 테이블 목록. extract/apply가 이 목록을 순회한다.

각 테이블은 1개 이상의 "구간"(regions)으로 이뤄진다 — 대부분 1개(class/fight/
magic/shop)지만 item·character처럼 서로 다른 오프셋 2곳을 합쳐야 레코드 하나가
완성되는 경우도 있다. `module.decode(*byte_strings)`가 구간 개수만큼 인자를 받고,
`module.encode(records)`는 구간이 1개면 bytes 하나, 여러 개면 그 순서의 bytes
튜플을 돌려준다 — extract/apply가 이 규칙으로 자동 처리한다.

새 테이블을 풀 때마다 여기에 추가하면 extract_balance.py / apply_balance.py가
자동으로 다룬다. game(L1/L2)별로 검증된 것만 등록한다 — 미검증 쪽은 아예 빼서
실수로 잘못된 오프셋에 쓰는 사고를 막는다.
"""
import class_dat
import fight_dat
import magic_dat
import item_dat
import character_dat
import shop_dat
import terrain_dat
import matchup_dat
import stage_reward_dat
import promotion_dat

TABLES = [
    {
        "key": "class",
        "module": class_dat,
        "games": {
            "L1": [{"path": "LANG1/CLASS.DAT", "offset": 0, "size": 7140}],
            "L2": [{"path": "LANG2/CLASS.DAT", "offset": 0, "size": 7140}],
        },
    },
    {
        "key": "fight",
        "module": fight_dat,
        "games": {
            "L1": [{"path": "LANG1/FIGHT.DAT", "offset": fight_dat.REGION_OFFSET, "size": fight_dat.REGION_SIZE}],
            "L2": [{"path": "LANG2/FIGHT.DAT", "offset": fight_dat.REGION_OFFSET, "size": fight_dat.REGION_SIZE}],
        },
    },
    {
        # ⚠ L1 오프셋 미검증 — L2만 확인됨(BALANCE_PIPELINE.md 8절 참고)
        "key": "magic",
        "module": magic_dat,
        "games": {
            "L2": [{"path": magic_dat.BIN_PATH, "offset": magic_dat.REGION_OFFSET, "size": magic_dat.REGION_SIZE}],
        },
    },
    {
        "key": "item",
        "module": item_dat,
        "games": {
            "L2": [
                {"path": item_dat.BIN_PATH, "offset": item_dat.EFFECTS_OFFSET, "size": item_dat.EFFECTS_SIZE},
                {"path": item_dat.BIN_PATH, "offset": item_dat.PRICE_OFFSET, "size": item_dat.PRICE_SIZE},
            ],
        },
    },
    {
        "key": "character",
        "module": character_dat,
        "games": {
            "L2": [
                {"path": character_dat.BIN_PATH, "offset": character_dat.STATS_OFFSET, "size": character_dat.STATS_SIZE},
                {"path": character_dat.BIN_PATH, "offset": character_dat.INIT_OFFSET, "size": character_dat.INIT_SIZE},
            ],
        },
    },
    {
        "key": "shop",
        "module": shop_dat,
        "games": {
            "L2": [{"path": shop_dat.BIN_PATH, "offset": shop_dat.OFFSET, "size": shop_dat.SIZE}],
        },
    },
    {
        "key": "terrain",
        "module": terrain_dat,
        "games": {
            "L2": [
                {"path": terrain_dat.BIN_PATH, "offset": terrain_dat.MOVE_OFFSET, "size": terrain_dat.MOVE_SIZE},
                {"path": terrain_dat.BIN_PATH, "offset": terrain_dat.TDEF_OFFSET, "size": terrain_dat.TDEF_SIZE},
                {"path": terrain_dat.BIN_PATH, "offset": terrain_dat.UDEF_OFFSET, "size": terrain_dat.UDEF_SIZE},
            ],
        },
    },
    {
        "key": "matchup",
        "module": matchup_dat,
        "games": {
            "L2": [{"path": matchup_dat.BIN_PATH, "offset": matchup_dat.OFFSET, "size": matchup_dat.SIZE}],
        },
    },
    {
        "key": "stage_reward",
        "module": stage_reward_dat,
        "games": {
            "L2": [
                {"path": stage_reward_dat.BIN_PATH, "offset": stage_reward_dat.GOLD_OFFSET, "size": stage_reward_dat.STAGE_COUNT},
                {"path": stage_reward_dat.BIN_PATH, "offset": stage_reward_dat.EXP_OFFSET, "size": stage_reward_dat.STAGE_COUNT},
            ],
        },
    },
    {
        "key": "promotion",
        "module": promotion_dat,
        "games": {
            "L2": [{"path": promotion_dat.BIN_PATH, "offset": promotion_dat.REGION_OFFSET, "size": promotion_dat.REGION_SIZE}],
        },
    },
]
