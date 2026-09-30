#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카타카나 라벨 리다이렉트 — ゲーム設定→게임설정, フェイズ終了→페이즈종료.

세션6 발견(LABELS_CATALOG.md 참조): 메뉴 라벨은 **라벨→글리프 인덱스 테이블**이
LANG{1,2}.BIN에 평문으로 있고, 게임이 그 인덱스를 그대로 그린다. 값은 전 뱅크 통합
인덱스(0x00-0x3F=res#29, 0x40-0x7F=res#30, 0x80-0xBF=res#31)이고 0x70(=res#30 g48)이
빈칸이다. ∴ 칸 수 < 원래 글자 수여도 남는 자리를 0x70으로 채우면 되고, 라벨이 쓸
글리프를 고를 수 있으니 **공유 글리프를 건드리지 않고** 비켜갈 수 있다.

전략(공유 회피):
  ゲーム設定(2e 2f 30 31 32 70) -> 게임설정(2e 30 31 32 70 70)
    ゲ(46)→게, ム(48)→임, 設(49)·定(50)은 이미 설·정. **ー(47)는 슬롯에서 빼기만**
    하고 내용은 그대로 둔다 — セーブ/ロード/戦闘シーン이 ー를 공유하기 때문.
  フェイズ終了(1d 1e 01 20 21 22) -> 페이즈종료(1d 01 20 21 22 70)
    フ(29)→페, イ(1)은 **이미 "이"**(アイテム→아이템에서 매핑됨)라 그대로 재활용,
    ズ(32)→즈, 終(33)·了(34)는 이미 종·료. **ェ(30)는 슬롯에서 빼기만** 한다.
  → 새로 그릴 글리프는 4개(게/임/페/즈)뿐이고, 공유 글리프 ー(47)·イ(1)·ェ(30)는
    내용을 건드리지 않으므로 다른 화면이 깨지지 않는다.

디스크의 파일을 읽어 그 위에 패치한다(원본이 아니라) — 기존 한자 라벨/배틀커맨드/
번역을 되돌리지 않기 위함.
"""
import io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))       # .../kr-patch/scripts/img_re
ROOT = os.path.dirname(os.path.dirname(HERE))           # .../kr-patch
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from img_codec import parse_archive, build_archive, decompress, compress
from gen_menu_kr_all import syl_tiles, HEADER

TRACK1 = os.path.join(ROOT, "build", "disc-krpoc", "track1.bin")

# 새로 그릴 글리프: res#29(L1)/res#27(L2) 로컬 인덱스 -> 한글 음절
NEW_GLYPHS = {
    29: "페",   # フ
    32: "즈",   # ズ  (카탈로그의 "32 ス"는 오독; 실제 フェイ**ズ**終了)
    46: "게",   # ゲ
    48: "임",   # ム  (res#29 g48 = ゲーム의 ム. アイテム의 ム는 g3로 별개)
}

# 라벨 테이블 패치: (파일오프셋, 원본바이트, 새바이트)
#   0x2e=46 ゲ  0x2f=47 ー  0x30=48 ム  0x31=49 設  0x32=50 定
#   0x1d=29 フ  0x1e=30 ェ  0x01=1 イ   0x20=32 ズ  0x21=33 終  0x22=34 了
#   0x70 = 빈칸
_GAME_OLD = bytes.fromhex("2e2f30313270")   # ゲーム設定
_GAME_NEW = bytes.fromhex("2e30313270 70".replace(" ", ""))  # 게임설정 + 빈칸
_PHASE_OLD = bytes.fromhex("1d1e01202122")  # フェイズ終了
_PHASE_NEW = bytes.fromhex("1d01202122 70".replace(" ", ""))  # 페이즈종료 + 빈칸
# 세션16: 시스템 메뉴 セーブ/ロード (system+0x00 / +0x06). 글리프는 refont_labels.SAVELOAD_{29,30}.
#   0x36=res#29 g54(セ→세)  0x01=res#29 g1(イ→이, 재활용)  0x3e=res#29 g62(ブ→브)  0x2f=ー  0x70=빈칸
#   0x49=res#30 g9(ロ→로)   0x4a=res#30 g10(ド→드)
_SAVE_OLD = bytes.fromhex("362f3e707070")   # セーブ (セ ー ブ)
_SAVE_NEW = bytes.fromhex("36013e707070")   # 세이브 (세 이 브) — ー(2f)→이(01)
_LOAD_OLD = bytes.fromhex("492f4a707070")   # ロード (ロ ー ド)
_LOAD_NEW = bytes.fromhex("494a70707070")   # 로드 (로 드) — ー 제외, ド를 앞으로

CONFIGS = {
    "L1": dict(binf="LANG1.BIN", bin_lba=202, bin_size=0x64F14,
               img="LANG1_IMG.DAT", img_lba=134794, img_size=514624, res=29,
               settei=0x2A794, system=0x2A8C8),
    "L2": dict(binf="LANG2.BIN", bin_lba=404, bin_size=0x65D0C,
               img="LANG2_IMG.DAT", img_lba=144236, img_size=546162, res=27,
               settei=0x2C4D0, system=0x2C604),
}


def _apply(buf, off, old, new, what):
    if bytes(buf[off:off + len(old)]) != old:
        raise SystemExit(f"{what}: @0x{off:x} 기대값 불일치 "
                         f"(got {bytes(buf[off:off+len(old)]).hex(' ')}, want {old.hex(' ')})")
    assert len(new) == len(old)
    buf[off:off + len(new)] = new


def patch_bin(buf, cfg, tag):
    b = bytearray(buf)
    # 게임설정 화면 테이블: 첫 슬롯이 ゲーム設定 (타이틀)
    _apply(b, cfg["settei"], _GAME_OLD, _GAME_NEW, f"{tag} settei/ゲーム設定")
    # 시스템 메뉴 테이블: +0x00 セーブ, +0x06 ロード, +0x12 ゲーム設定, +0x18 フェイズ終了
    _apply(b, cfg["system"] + 0x00, _SAVE_OLD, _SAVE_NEW, f"{tag} system/セーブ")
    _apply(b, cfg["system"] + 0x06, _LOAD_OLD, _LOAD_NEW, f"{tag} system/ロード")
    _apply(b, cfg["system"] + 0x12, _GAME_OLD, _GAME_NEW, f"{tag} system/ゲーム設定")
    _apply(b, cfg["system"] + 0x18, _PHASE_OLD, _PHASE_NEW, f"{tag} system/フェイズ終了")
    return bytes(b)


def patch_img(buf, cfg, tag):
    res = parse_archive(buf)
    raw = bytearray(decompress(res[cfg["res"]]))
    cache = {ch: syl_tiles(ch) for ch in set(NEW_GLYPHS.values())}
    for g, ch in NEW_GLYPHS.items():
        for qi in range(4):
            off = HEADER + (g * 4 + qi) * 32
            raw[off:off + 32] = cache[ch][qi]
    raw = bytes(raw)
    comp = compress(raw)
    assert decompress(comp) == raw, f"{tag}: 코덱 라운드트립 실패"
    res[cfg["res"]] = comp
    new = build_archive(res)
    assert decompress(parse_archive(new)[cfg["res"]]) == raw, f"{tag}: 재파싱 검증 실패"
    if len(new) > cfg["img_size"]:
        raise SystemExit(f"{tag}: IMG.DAT 초과 {len(new)} > {cfg['img_size']}")
    return new + bytes(cfg["img_size"] - len(new))   # 원본 크기로 0패딩(ISO 배치 고정)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    import disc_tool
    disc = disc_tool.Disc(TRACK1)
    for tag, cfg in CONFIGS.items():
        b = disc.read_file(cfg["bin_lba"], cfg["bin_size"])
        disc.write_file(cfg["bin_lba"], patch_bin(b, cfg, tag))
        print(f"{tag} {cfg['binf']}: 테이블 5곳 리다이렉트 (게임설정 x2, 페이즈종료, 세이브, 로드)")
        # ⚠ 세이브/로드 글리프(세·브=res#29, 로·드=res#30)는 refont_labels가 굽는다 —
        #   standalone patch_img(아래)는 res#29 NEW_GLYPHS만 처리하므로 세/브/로/드는 안 나온다.

        img = disc.read_file(cfg["img_lba"], cfg["img_size"])
        disc.write_file(cfg["img_lba"], patch_img(img, cfg, tag))
        print(f"{tag} {cfg['img']}: res#{cfg['res']} 글리프 {sorted(NEW_GLYPHS)} -> "
              + "/".join(NEW_GLYPHS[g] for g in sorted(NEW_GLYPHS)))
    disc.save(TRACK1)
    print("saved:", TRACK1)


if __name__ == "__main__":
    main()
