#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_hud8.py — 8px HUD 병종명·캐릭터명 한글 타일을 IMG.DAT 리소스에 굽는다.

★ 세션22 전환: 런타임 self-heal 폐기 → **게임이 스스로 로드하는 타일**로
  세션14/15는 8px 글리프를 FONT.DAT payload에 블롭으로 싣고 케이브가 VDP2→VDP2로
  자가 복사(heal)했다. 안드로이드 Yaba Sanshiro는 **SH-2의 VDP2 VRAM 쓰기를
  재현하지 못해** 그 뱅크가 쓰레기로 남았고 8px 병종명이 모자이크로 보였다
  (사용자 RG34XX SP 보고, 세션21). 이제 글리프는 IMG.DAT의 **원래 빈(전부 0) 타일**에
  직접 굽고, 게임의 정상 압축해제 경로가 VRAM에 올린다. 케이브는 PND 계산만 한다.

파이프라인:
  1. gen_classnames.tile_map(원본 BIN, tag) → {풀 서수 k: 음절}.
  2. gen_classnames.tile_slots()[k] = (리소스 번호, 타일 번호) — 케이브의
     세그먼트 룩업과 **같은 표**를 쓰므로 글리프 위치와 charno가 절대 어긋나지 않는다.
  3. **달무리**(dalmoori.ttf) 8x8 픽셀폰트로 렌더 → 4bpp(잉크=색인1, res#0
     카타카나와 동일 팔레트1) 타일 32B. 렌더 주의사항은 FONT 상수 주석 참조.
  4. 해당 리소스를 압축해제 → 타일 write → compress_optimal → build_archive →
     디스크 IMG.DAT 재삽입.

⚠ 대상 타일은 **원본에서 전부 0인 슬롯만** 쓴다(_assert_slots_free가 원본
아카이브로 매 실행 검사). 카타카나(res#0 64-127)는 건드리지 않는다 — 병종명이
아닌 문자열은 여전히 원래 카타카나 경로로 그려지기 때문.

⚠ 실행 순서: refont_labels.py 등 IMG.DAT를 다시 빌드하는 스크립트를 돌린 뒤에는
반드시 이 스크립트를 다시 돌려야 한다. 이 스크립트 자체는 멱등이다.
"""
import io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from img_codec import parse_archive, build_archive, decompress, compress_optimal
import gen_classnames
import refont_labels as _rl
import gen_titlemenu as _tm
from gen_menu_kr_all import syl_tiles, HEADER

TRACK1 = os.path.join(ROOT, "build", "disc-krpoc", "track1.bin")
ORIG = os.path.join(ROOT, "original")
HDR = 4                      # 압축해제 출력의 4B 헤더 (타일 0 = off HDR)

# --- 8px 폰트: 달무리 (세션22에서 갈무리M[고딕,8x8]에서 교체, 사용자 지정) ---
# 달무리는 unitsPerEm=64 · 8유닛=디자인픽셀 1개인 8x8 픽셀폰트(아웃라인 전용,
# 임베디드 비트맵 없음). 갈무리M보다 획이 얇고 오른쪽 여백이 있어 글자가 잘 분리된다.
# ⛔ ppem 8로 바로 렌더하면 안 된다 — FreeType 힌팅이 아웃라인을 픽셀 그리드에서
#    밀어내 글리프가 9px로 번지고 획이 뭉갠다(모노 렌더도 마찬가지). 그래서
#    **ppem 8*SS로 렌더한 뒤 SS×SS 블록 평균으로 정수 다운샘플**한다 — 힌팅이
#    한두 픽셀 흔들려도 블록 판정이 흡수한다.
FONT = os.path.join(ROOT, "fonts", "dalmoori.ttf")          # 세션24: 프로젝트 안으로 이사
if not os.path.exists(FONT):                                 # 옛 배치(형제 폴더) 폴백
    FONT = os.path.join(os.path.dirname(ROOT), "dalmoori-font", "dalmoori.ttf")
FONT8_PPEM_SCALE = 8         # 렌더 ppem = 8 * 이 값
# (구 폰트: ../갈무리m[고딕,8x8]/갈무리M[고딕,8x8].ttf — 임베디드 비트맵이라
#  size=16으로 열어 좌상단 8x8을 크롭하는 방식이었다. 되돌리려면 _font8()과
#  render_glyph8의 다운샘플을 그 방식으로 바꿔야 한다.)


def _font8():
    from PIL import ImageFont
    return ImageFont.truetype(FONT, 8 * FONT8_PPEM_SCALE)

CONFIGS = {
    "L1": dict(bin="LANG1.BIN", lba=134794, size=514624,
               src="LANG1.BIN", img="LANG1_IMG.DAT"),
    "L2": dict(bin="LANG2.BIN", lba=144236, size=546162,
               src="LANG2.BIN", img="LANG2_IMG.DAT"),
}


def render_glyph8(font, ch):
    """달무리 8x8 → 4bpp 타일 32B (잉크=색인 1, 배경=0).

    font은 _font8()이 만든 ppem 8*SS 폰트다. 8x8 디자인픽셀 하나가 화면 SS×SS
    블록이 되므로 블록 평균 ≥ 50%면 잉크로 본다(위 FONT 주석의 힌팅 함정 참조).
    em 박스가 정확히 (0,0)-(8*SS,8*SS)라 원점 보정은 필요 없다 — 벗어나면 아래
    assert가 잡는다."""
    from PIL import Image, ImageDraw
    ss = FONT8_PPEM_SCALE
    n = 8 * ss
    img = Image.new("L", (n * 2, n * 2), 0)
    ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=255)
    px = img.load()
    # 8x8 셀 밖으로 잉크가 나가면 폰트/렌더 회귀 — 빌드 에러로 승격
    for y in range(n * 2):
        for x in range(n * 2):
            if px[x, y] > 127 and (x >= n or y >= n):
                raise ValueError(f"glyph {ch!r} ink outside the 8x8 cell "
                                 f"at design px ({x/ss:.1f},{y/ss:.1f})")
    tile = bytearray(32)
    ink = 0
    half = 128 * ss * ss
    for y in range(8):
        for x in range(8):
            s = 0
            for j in range(ss):
                row = y * ss + j
                for i in range(ss):
                    s += px[x * ss + i, row]
            if s >= half:
                ink += 1
                tile[y * 4 + x // 2] |= (1 << (0 if x & 1 else 4))
    if ink == 0:
        raise ValueError(f"glyph {ch!r} rendered empty")
    return bytes(tile)


def kr8_tiles(tag):
    """{res#: {tile: 32B}} — 8px 한글 글리프를 gen_classnames.tile_slots()가
    지정한 IMG.DAT 자리에 배치한다. 입력은 **원본** LANG*.BIN(병종명·캐릭터명이
    아직 일본어라야 tile_map이 번역 매핑을 만들 수 있다)."""
    font = _font8()
    binx = open(os.path.join(ORIG, CONFIGS[tag]["src"]), "rb").read()
    tmap = gen_classnames.tile_map(binx, tag)
    slots = gen_classnames.tile_slots()
    assert max(tmap) < len(slots), f"{tag} tile_map overflows the tile segments"
    out = {}
    for k, ch in sorted(tmap.items()):
        res, tile = slots[k]
        # ' ' = 여백 음절(스팀 이름의 '드 모토프' 등) → 투명 타일 그대로
        out.setdefault(res, {})[tile] = (b"\x00" * 32 if ch == " "
                                         else render_glyph8(font, ch))
    return out


def _assert_slots_free(tag, kr8):
    """굽기 대상 타일이 (a) 원본 아카이브에서 **전부 0**이고 (b) 게임이 **참조하지
    않는** charno인지 확인한다.
    (b)가 핵심이다 — 세션22 첫 빌드는 (a)만 봤다가 res#1 tile 128(=charno 0x380,
    맵 HUD의 빈칸 타일)에 '토'를 구워 화면에 토가 깔렸다."""
    gen_classnames.assert_slots_unreferenced()
    buf = open(os.path.join(ORIG, CONFIGS[tag]["img"]), "rb").read()
    res = parse_archive(buf)
    for i, tiles in kr8.items():
        raw = decompress(res[i])
        for t in tiles:
            off = HDR + t * 32
            assert raw[off:off + 32] == b"\x00" * 32, \
                f"{tag} res#{i} tile {t} is NOT empty in the original archive"


# res#0 히라가나 타일 48~55 재굽기: しきはんい/しゅうせい 패널 라벨은 BIN의 타일워드
# 배열이 이 타일들을 직접 참조한다(gen_classnames 5c 참조). 지휘범위 배열[48..52]은
# 그대로 두고 타일 내용만 지/휘/범/위/_로, 수정은 53/54에 수/정을 굽고 배열을 돌린다.
HIRA_TILES = {48: "지", 49: "휘", 50: "범", 51: "위", 52: " ",
              53: "수", 54: "정", 55: " "}

# res#1 = 전투(VS/마법) 패널 찰셋 (세션14 말미 발견; VRAM charno 0x300+i로 로드,
# 마법 씬 덤프 build/dump_magic_kanji_s14 로 특정):
#   타일 164/165 = 地/形 (8px, 잉크 색인 0xE·배경 0x7 — ATDF 레터와 동일)
#   타일 168/169+184/185 = 魔 (16px: TL/TR/BL/BR), 170/171+186/187 = 法 (잉크 1·배경 7)
RES1_8PX = {164: "지", 165: "형"}
RES1_16PX = {"마": (168, 169, 184, 185), "법": (170, 171, 186, 187)}


def _recolor(tile, ink, bg):
    """1bpp식(잉크=비제로 니블) 타일을 지정 색인(ink/bg)으로 재배색."""
    out = bytearray()
    for b in tile:
        hi = ink if (b >> 4) else bg
        lo = ink if (b & 15) else bg
        out.append((hi << 4) | lo)
    return bytes(out)


def _rebake_res1(raw, font):
    out = bytearray(raw)
    for t, ch in RES1_8PX.items():
        out[4 + t * 32:4 + (t + 1) * 32] = _recolor(render_glyph8(font, ch), 0xE, 0x7)
    for ch, quads in RES1_16PX.items():
        for q, t in zip(syl_tiles(ch), quads):   # syl_tiles: TL,TR,BL,BR (잉크=1)
            out[4 + t * 32:4 + (t + 1) * 32] = _recolor(q, 0x1, 0x7)
    return bytes(out)


def _rebake_res0(raw, font):
    out = bytearray(raw)
    for t, ch in HIRA_TILES.items():
        tile = b"\x00" * 32 if ch == " " else render_glyph8(font, ch)
        out[4 + t * 32:4 + (t + 1) * 32] = tile     # +4 = 디컴프레스 헤더
    return bytes(out)


def _rebake_labels(raw, mapping):
    """refont_labels의 16px 라벨 글리프 재굽기(neodgm)를 repack 안에서 수행.
    (별도 refont_labels.py 실행은 블롭이 실린 디스크에서 마지막 리소스에 슬랙이
    딸려 들어가 오버플로한다 — IMG 재빌드는 이 스크립트 하나로 끝낸다.)"""
    out = bytearray(raw)
    cache = {ch: syl_tiles(ch) for ch in set(mapping.values())}
    for g, ch in mapping.items():
        for qi in range(4):
            off = HEADER + (g * 4 + qi) * 32
            out[off:off + 32] = cache[ch][qi]
    return bytes(out)


def _write_tiles(raw, tiles):
    out = bytearray(raw)
    for t, data in tiles.items():
        out[HDR + t * 32:HDR + (t + 1) * 32] = data
    return bytes(out)


def repack_with_blob(img_buf, blob, blob_off, size, tag, hud8):
    """hud8=True: res#0 히라가나(지휘범위/수정)·res#1 전투패널 재굽기 + **세션22:
    8px 병종명/캐릭터명 한글 타일을 res#0/res#5/res#1의 빈 슬롯에 굽기**
    (blob/blob_off 인자는 세션14 이후 미사용).
    hud8=False: 라벨 재굽기·재압축만."""
    font = _font8()
    label_banks = _rl.CONFIGS[tag]["banks"]     # {res#: {glyph: 한글}}
    kr8 = kr8_tiles(tag) if hud8 else {}
    if kr8:
        _assert_slots_free(tag, kr8)
    res = parse_archive(img_buf)
    new_res = []
    for i, r in enumerate(res):
        if len(r) < 3:
            new_res.append(r)
            continue
        raw = decompress(r)
        edited = False
        if i == 0 and hud8:
            raw = _rebake_res0(raw, font)
            edited = True
        if i == 1 and hud8:
            raw = _rebake_res1(raw, font)
            edited = True
        if i in kr8:
            raw = _write_tiles(raw, kr8[i])
            edited = True
        if hud8 and i == _tm.RES[tag]:      # 에피소드 타이틀 메뉴(VDP1 스프라이트)
            raw = _tm.patch_sprite(raw)
            edited = True
        if i in label_banks:
            raw = _rebake_labels(raw, label_banks[i])
            edited = True
        c = compress_optimal(raw)
        assert decompress(c) == raw, f"{tag} res#{i}: optimal round-trip failed"
        # 내용이 바뀐 리소스는 항상 재압축본을 쓴다
        new_res.append(c if (edited or len(c) < len(r)) else r)
    new = build_archive(new_res)
    # 세션22: 빈 타일에 글리프가 들어가면 그 리소스의 압축률이 나빠진다 — 파일
    # 슬롯을 넘기면 조용히 잘리지 않고 여기서 멈춘다.
    assert len(new) <= size, \
        f"{tag} IMG archive {len(new)}B > file slot {size}B (타일이 너무 많다)"
    # 재파스 검증 (오프셋 테이블 재빌드 무결성; res#0은 의도적 변경이라 자기 자신과 대조)
    res2 = parse_archive(new + b"\x00" * (size - len(new)))
    for i, (a, b) in enumerate(zip(new_res, res2)):
        if len(a) >= 3:
            assert decompress(a) == decompress(b), f"{tag} res#{i}: repack mismatch"
    out = bytearray(size)
    out[:len(new)] = new
    return bytes(out), len(new)


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    hud8 = os.environ.get("KR_HUD8", "1") != "0"
    import disc_tool
    disc = disc_tool.Disc(TRACK1)
    for tag, cfg in CONFIGS.items():
        buf = disc.read_file(cfg["lba"], cfg["size"])
        out, arch_len = repack_with_blob(buf, None, None, cfg["size"], tag, hud8)
        disc.write_file(cfg["lba"], out)
        mode = "HUD8" if hud8 else "labels-only(안정)"
        if hud8:
            n = kr8_tiles(tag)
            mode += " 8px타일 " + " ".join(
                f"res#{i}:{len(t)}" for i, t in sorted(n.items()))
            mode += f" +타이틀메뉴 res#{_tm.RES[tag]}"
        print(f"{tag} {cfg['bin']}_IMG [{mode}]: archive {len(buf)} -> {arch_len} "
              f"(slack {cfg['size']-arch_len}B)")
    disc.save(TRACK1)
    print("saved:", TRACK1)


if __name__ == "__main__":
    main()
