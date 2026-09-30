#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""이미 한글화된 그래픽 라벨 글리프를 **새 폰트로 다시 굽는다**(디스크 인플레이스).

왜 별도 스크립트인가: 현재 디스크의 IMG.DAT에는 패치가 누적돼 있다 —
  ① 프렙/UI 한자 라벨(gen_menu_kr_all의 GLYPH_KR, res#29)
  ② 배틀 커맨드·상태어(res#30/31) — **당시 스크립트가 남아있지 않다**
  ③ 카타카나 리다이렉트(patch_katakana_redirect, res#29 g29/32/46/48)
gen_menu_kr_all.py를 원본에서 다시 돌리면 ②③이 사라진다. 그래서 원본이 아니라
**디스크의 현재 IMG.DAT를 읽어** 아래 매핑의 글리프만 새 폰트로 덮어쓴다.

②의 매핑은 스크립트가 없어 **디스크 글리프를 렌더해 판독·복원**했다(2026-07-17):
res#30 51~60 = 移動攻魔法召喚治療令 → 이동공마법소환치료령,
res#31 2,3,4,5,6,17,36 = 最大防御手敵突 → 최대방어수적돌.
⚠ res#30 g50(H)·res#31 g1(費)/g16(ト)/g35(ぎ)는 원본과 니블 3~6px만 다른 **비-한글**
글리프라 대상에서 제외한다(원본 유지).

폰트: gen_menu_kr_all.FONT(=neodgm 16px, 픽셀 폰트 네이티브 + 중앙 패딩).
"""
import io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from img_codec import parse_archive, build_archive, decompress, compress
from gen_menu_kr_all import GLYPH_KR, syl_tiles, HEADER

TRACK1 = os.path.join(ROOT, "build", "disc-krpoc", "track1.bin")

# 카타카나 리다이렉트로 추가된 글리프(patch_katakana_redirect.NEW_GLYPHS와 동일해야 함)
REDIRECT_GLYPHS = {29: "페", 32: "즈", 46: "게", 48: "임"}

# 세션16: 시스템 메뉴 セーブ/ロード 한글화. BIN 테이블 리다이렉트는 patch_katakana_redirect.patch_bin.
#   セ(res#29/27 g54)→세, ブ(g62)→브  => セーブ(36 2f 3e ..) -> 세이브(36 01 3e ..) [이=g1 재활용]
#   ロ(res#30/28 g9)→로, ド(g10)→드    => ロード(49 2f 4a ..) -> 로드(49 4a 70 ..) [ー 제외]
# 이 글리프들은 정적 라벨(시스템 5슬롯·프렙 4슬롯) 중 セーブ/ロード 외엔 미사용 실측(2026-07-19).
SAVELOAD_29 = {54: "세", 62: "브"}      # res#29(L1)/res#27(L2)
SAVELOAD_30 = {9: "로", 10: "드"}       # res#30(L1)/res#28(L2)

# 세션19: 세이브 화면 하단 `次のシナリオへ` + 시나리오 타이틀 카드 `シナリオ␣N` 한글화.
#   두 라벨은 **런타임 조립**(정적 인덱스 테이블 없음 — 라이브 RE로 확증)이라 인덱스는 못 바꾼다.
#   대신 그 라벨들이 쓰는 글리프 7개의 *내용*을 한글로 재굽는다. 전역인덱스 = res#29 g + 0 / res#30 g + 64.
#     次のシナリオへ = [31, 94, 6, 82, 83, 84, 42] -> 다 음 시 나 리 오 로
#     シナリオ␣N     = [6, 82, 83, 84, 112, 96+N] -> 시 나 리 오 ␣ N   (같은 글리프 재사용 → 동시 한글화)
#   VRAM 글리프 = 1280 + 전역인덱스, 타일데이터 = vdp2vram 0x28000 + 전역인덱스*128 (라이브 검증됨).
# ⚠ 부작용: シ(res#29 g6)는 ショップ(g6-9)와 공유 → Ep2 상점 라벨이 `시ョップ`로 보인다.
#   상점 라벨은 원래 미번역(일본어)이고 동적 조립이라 별도 과제. 되돌리려면 아래 6을 빼면 된다.
# ⚠ の(res#30 g30)·ヘ(res#29 g42)가 백업RAM 관리 등 **미번역 일본어 메시지**에 쓰이면 그쪽에
#   `음`/`로`가 섞여 보일 수 있다(해당 화면 자체가 미번역 백로그).
NEXTSCEN_29 = {31: "다", 42: "로", 6: "시"}          # 次 ヘ シ
NEXTSCEN_30 = {30: "음", 18: "나", 19: "리", 20: "오"}  # の ナ リ オ

# 배틀 커맨드/상태어 — 디스크 렌더 판독으로 복원한 매핑
CMD_GLYPHS = {51: "이", 52: "동", 53: "공", 54: "마", 55: "법",
              56: "소", 57: "환", 58: "치", 59: "료", 60: "령",
              # 세션13 선제 재굽기(순수 한자 낱말만 — 카탈로그 세션6 재판독표 기준):
              1: "표", 2: "시",          # 表示(設定) -> 표시(설정)
              14: "장",                  # 面 -> 장 (gen_menutext의 面->장과 일치)
              61: "부", 62: "족"}        # 不足 -> 부족 (⚠뒤따르는 で는 가나라 유지)
# g32 決 -> 결 (세션13: 병사배속 트룹 화면 "決定" -> "결정"; 定=res#29 g50은 이미 정.
# ⚠ 決め… 계열 일본어 메시지가 이 글리프를 공유하면 "결め"로 보일 수 있음 — 그 메시지
# 자체가 미번역 백로그라 수용)
STATE_GLYPHS = {2: "최", 3: "대", 4: "방", 5: "어", 6: "수", 17: "적", 36: "돌",
                32: "결",
                # 세션13 선제 재굽기:
                0: "소", 1: "비",        # 消費 -> 소비
                12: "아", 13: "군",      # 味方 -> 아군 (단어 매핑)
                27: "과",                # (戦)果 -> (전)과: 戦=res#29 g60 이미 '전'
                28: "보", 29: "고",      # 報告 -> 보고
                30: "이", 31: "름"}      # 名前 -> 이름 (단어 매핑)

CONFIGS = {
    "L1": dict(img="LANG1_IMG.DAT", lba=134794, size=514624,
               banks={29: {**GLYPH_KR, **REDIRECT_GLYPHS, **SAVELOAD_29, **NEXTSCEN_29},
                      30: {**CMD_GLYPHS, **SAVELOAD_30, **NEXTSCEN_30}, 31: STATE_GLYPHS}),
    "L2": dict(img="LANG2_IMG.DAT", lba=144236, size=546162,
               banks={27: {**GLYPH_KR, **REDIRECT_GLYPHS, **SAVELOAD_29, **NEXTSCEN_29},
                      28: {**CMD_GLYPHS, **SAVELOAD_30, **NEXTSCEN_30}, 29: STATE_GLYPHS}),
}


def rebake(buf, banks, tag):
    res = parse_archive(buf)
    total = 0
    for idx, mapping in banks.items():
        raw = bytearray(decompress(res[idx]))
        cache = {ch: syl_tiles(ch) for ch in set(mapping.values())}
        for g, ch in mapping.items():
            for qi in range(4):
                off = HEADER + (g * 4 + qi) * 32
                raw[off:off + 32] = cache[ch][qi]
        raw = bytes(raw)
        comp = compress(raw)
        assert decompress(comp) == raw, f"{tag} res#{idx}: codec round-trip failed"
        res[idx] = comp
        total += len(mapping)
    new = build_archive(res)
    for idx in banks:
        assert decompress(parse_archive(new)[idx]) == decompress(res[idx]), \
            f"{tag} res#{idx}: re-parse verify failed"
    return new, total


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    import disc_tool
    disc = disc_tool.Disc(TRACK1)
    for tag, cfg in CONFIGS.items():
        buf = disc.read_file(cfg["lba"], cfg["size"])
        new, n = rebake(buf, cfg["banks"], tag)
        if len(new) > cfg["size"]:
            raise SystemExit(f"{tag}: IMG.DAT overflow {len(new)} > {cfg['size']}")
        disc.write_file(cfg["lba"], new + bytes(cfg["size"] - len(new)))
        print(f"{tag} {cfg['img']}: {n} glyphs re-baked "
              f"(banks {sorted(cfg['banks'])}), {len(buf)} -> {len(new)} (padded)")
    disc.save(TRACK1)
    print("saved:", TRACK1)


if __name__ == "__main__":
    main()
