#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IMG.DAT 메뉴 그래픽 라벨 일괄 한글화 (배틀프렙 + UI 라벨).

발견: 라벨 글리프는 리소스 내 연속 4타일(2x2) 글리프 스트립으로 저장되며,
LANG1 res#29 == LANG2 res#27 (동일 배치). 각 글리프 인덱스를 한글 음절(또는 공백)로
치환한다. 한자는 독음 1:1(글리프 공유돼도 독음 일관이라 안전), 카타카나 로안워드는
음절 수 차이를 공백으로 흡수.

글리프 인덱스(렌더 판독, res#29/res#27 공통):
 0 ア 1 イ 2 テ 3 ム 4 装 5 備 6 シ 7 ョ 8 ッ 9 プ 10 指 11 揮 12 官 13 配 14 置 15 兵
 16 士 17 属 ...(18-20 BND) 21 購 22 入 23 売 24 却 25 選 26 択 27 出 28 撃 ...
 37 条 38 件 ... 46 ゲ 47 ー 48 ム 49 設 50 定 ... 55 速 56 度 57 高 58 通 59 常 60 戦 61 闘
"""
import struct, sys, io, os
from PIL import Image, ImageFont, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from img_codec import parse_archive, build_archive, decompress, compress

FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "fonts", "neodgm.ttf")
FONT_PX = 16      # neodgm은 16px 설계의 픽셀 폰트 — 이 크기에서만 픽셀 그리드에 정확히 맞는다
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HEADER = 4  # decompressed 리소스 선두 4바이트 헤더; 타일은 그 뒤부터

# glyph index -> 한글 음절 ("" = 빈 타일). 미확신 글리프는 생략(일본어 유지).
GLYPH_KR = {
    # ⚠ 카타카나 공유 주의: シ(g6)는 シナリオ와 공유 → ショップ 건드리면 시나리오 깨짐(유지).
    # 단 ア/イ/テ/ム(g0-3)은 シナリオ 미사용·타 리소스라 アイテム 전용 → 안전.
    0: "아", 1: "이", 2: "템", 3: "",   4: "장", 5: "비",     # アイテム装備 -> 아이템 장비 (テ→템, ム(무) 삭제)
    10: "지", 11: "휘", 12: "관", 13: "배", 14: "치",          # 指揮官配置 -> 지휘관배치
    15: "병", 16: "사", 17: "속",                              # 兵士 + 配(13)배 + 属속 -> 병사배속
    33: "종", 34: "료",                                        # 終了 -> 종료
    35: "승", 36: "리",                                        # 勝利 -> 승리 (勝利条件=승리조건)
    57: "고",                                                  # 高 -> 고
    21: "구", 22: "입",                                        # 購入 -> 구입
    23: "매", 24: "각",                                        # 売却 -> 매각
    25: "선", 26: "택",                                        # 選択 -> 선택
    27: "출", 28: "격",                                        # 出撃 -> 출격
    37: "조", 38: "건",                                        # 条件 -> 조건
    49: "설", 50: "정",                                        # 設定 -> 설정 (ゲーム 카타카나는 공유위험이라 원본유지)
    55: "속", 56: "도",                                        # 速度 -> 속도
    58: "통", 59: "상",                                        # 通常 -> 통상
    60: "전", 61: "투",                                        # 戦闘 -> 전투
}


def syl_nibbles(ch, size=None):
    """한 음절을 16x16 니블 그리드로. 팔레트 니블 1 = 흰색(240,240,240)이 본체 색.

    neodgm(네오둥근모)은 16px 설계의 1비트 픽셀 폰트라 FONT_PX에서 픽셀 그리드에 정확히
    떨어진다(안티에일리어싱 0 — 검증됨). 따라서 **리샘플링 없이 그대로 그리고, 남는 여백은
    상하좌우 패딩으로 중앙 정렬**해 16x16에 맞춘다.

    (이전 방식은 굴림을 48px로 그려 16x16으로 LANCZOS 축소 후 이진화했다. 굴림 임베디드
    비트맵이 셀을 못 채워 "글씨가 작다"는 피드백을 그렇게 우회했는데, 3배 축소 + 임계값
    이진화가 획 굵기를 들쭉날쭉하게 만들고 가는 획을 끊어 "글씨체가 이상하다"는 문제가 됐다.
    픽셀 폰트를 네이티브 크기로 쓰면 애초에 축소가 없으므로 획이 깨지지 않는다.)
    """
    im = Image.new("L", (48, 48), 0)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, FONT_PX)
    bb = d.textbbox((0, 0), ch, font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    if w > 16 or h > 16:        # 픽셀 폰트를 벗어난 크기 — 축소하면 다시 뭉개지므로 막는다
        raise ValueError(f"glyph {ch!r} ink {w}x{h} exceeds the 16x16 cell at {FONT_PX}px")
    # 잉크를 셀 중앙에 배치(수평 중앙, 수직은 반올림 시 위쪽에 여백을 더 준다)
    d.text(((16 - w) // 2 - bb[0], (16 - h) // 2 - bb[1]), ch, fill=255, font=f)
    return [[1 if im.getpixel((x, y)) >= 128 else 0 for x in range(16)] for y in range(16)]


def syl_tiles(ch):
    if ch == "":
        return [bytes(32)] * 4
    nib = syl_nibbles(ch)
    tiles = []
    for qy, qx in ((0, 0), (0, 1), (1, 0), (1, 1)):
        t = bytearray()
        for row in range(8):
            for cx in range(4):
                t.append((nib[qy*8+row][qx*8+cx*2] << 4) | nib[qy*8+row][qx*8+cx*2+1])
        tiles.append(bytes(t))
    return tiles


def patch_resource(raw):
    out = bytearray(raw)
    kr_cache = {ch: syl_tiles(ch) for ch in set(GLYPH_KR.values())}
    for g, ch in GLYPH_KR.items():
        tiles = kr_cache[ch]
        for qi in range(4):
            off = HEADER + (g * 4 + qi) * 32
            out[off:off+32] = tiles[qi]
    return bytes(out)


def render_grid(raw, path):
    o = raw
    nglyph = (len(o) - HEADER) // 32 // 4
    cols = 16
    rows = (nglyph + cols - 1) // cols
    G = 18
    img = Image.new("L", (cols*G, rows*G), 200)
    for g in range(nglyph):
        gx, gy = (g % cols)*G, (g // cols)*G
        for qi, (qy, qx) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
            t = o[HEADER + (g*4+qi)*32: HEADER + (g*4+qi)*32+32]
            for row in range(8):
                for cx in range(4):
                    b = t[row*4+cx]
                    for k, n in enumerate((b >> 4, b & 0xf)):
                        img.putpixel((gx+qx*8+cx*2+k, gy+qy*8+row), 255-min(n, 3)*80)
    img.resize((img.width*3, img.height*3), Image.NEAREST).save(path)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    for arch_name, idx in [("LANG1_IMG.DAT", 29), ("LANG2_IMG.DAT", 27)]:
        buf = open(os.path.join(DATA, arch_name), "rb").read()
        res = parse_archive(buf)
        raw = decompress(res[idx])
        patched = patch_resource(raw)
        assert decompress(compress(patched)) == patched
        res[idx] = compress(patched)
        newbuf = build_archive(res)
        assert decompress(parse_archive(newbuf)[idx]) == patched
        open(os.path.join(outdir, arch_name), "wb").write(newbuf)
        render_grid(patched, os.path.join(outdir, arch_name + ".preview.png"))
        print(f"{arch_name}: res#{idx} patched, 0x{len(buf):x}->0x{len(newbuf):x}")
    print("labels:", ", ".join(sorted(set(v for v in GLYPH_KR.values() if v))))


if __name__ == "__main__":
    main()
