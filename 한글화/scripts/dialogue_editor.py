#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dialogue_editor.py — 랑그릿사 한글화 대사 검수/편집 로컬 웹툴 (에뮬과 별개).

브라우저에서 worksheet_dedup_final.json 의 대사를 직접 편집하며, 실제 게임 창
지오메트리(대사 14칸x3줄 / 나레이션 16칸x7줄)와 실제 게임 폰트(neodgm.ttf)로
줄바꿈·띄어쓰기·빈줄·오버플로를 눈으로 보고 저장(워크시트 직접 되쓰기)한다.

줄바꿈 정책 = 방식 A(수동 오버라이드): 미리보기는 사용자의 [NL]/[PAGE] 를 그대로
그린다(자동 reflow 안 함). 저장 시 그 항목에 manual_layout=true 를 달아 reinsert
가 그 항목만 reflow 를 끄고 사용자의 줄바꿈을 게임에 그대로 반영하게 한다.

실행:  python scripts/dialogue_editor.py   → http://127.0.0.1:8777
의존성 없음(파이썬 표준 라이브러리 + 프로젝트 kr_markup).
"""
import os, sys, io, re, json, html, datetime, shutil, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kr_markup as M                       # parse_markup / rewrap_markup / _ATOM / _atom_width
import kr_render                            # render_segment (reinsert의 no-markup 경로)
import kr_names                             # [NAME:xx] -> 실제 이름/칸수

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
FONT_PATH = os.path.join(ROOT, "fonts", "neodgm.ttf")
PORT = int(os.environ.get("DLGEDIT_PORT", "8777"))

# ── 리프 지오메트리 (reinsert_text.py 와 동일하게) ───────────────────────────
NARR_LEAF = (2, 7)     # 전체화면 나레이션: 16칸 x 7줄, absorb 없음
COND_LEAF = (2, 6)     # 조건/튜토리얼: 같은 전체화면 격자 16칸 x 4줄 (세션23 실측)
END_LEAF  = (2, 9)     # 엔딩 후일담: 같은 전체화면 격자 16칸 x 4줄 (세션23 실측)
DLG_LEAF  = (2, 5)     # 주 대사: 14칸 x 3줄
UI_LEAF   = (2, 0)     # 메뉴/UI: 전각 space(창 비움 안 함)
TITLE_LEAF = (2, 8)    # 시나리오 제목 테이블
WIDTH, MAX_LINES = 14, 3
DLG_PAGE2_LINES = 4    # 세션18 실기 확정: 시나리오 대화 2페이지+(이름 없음) = 4줄
NARR_WIDTH, NARR_LINES = 16, 7
# 전체화면 텍스트 격자 리프별 지오메트리 — 근거는 reinsert_text.FULLSCREEN_GEOM 주석 참조.
FULLSCREEN_GEOM = {NARR_LEAF: (NARR_WIDTH, NARR_LINES),
                   COND_LEAF: (16, 4), END_LEAF: (16, 4)}
FS_CAT = {NARR_LEAF: "나레이션", COND_LEAF: "조건/튜토리얼", END_LEAF: "엔딩"}

_backed_up = [False]   # 세션 첫 저장 때 1회 백업


# ── 워크시트 로드 ────────────────────────────────────────────────────────────
def load_ws():
    with open(WS_PATH, encoding="utf-8") as f:
        return json.load(f)

WS = load_ws()
# `[NAME:xx]`를 추정 4칸이 아니라 실제 이름 폭으로 재기 위한 게임별 표(세션23).
# NAME_TABLE = {tag: {세그먼트: 이름}}(칩에 실제 이름을 그린다), NAME_W = {tag: {xx: 칸수}}
# (조판기 rewrap_markup/max_line_width에 넘긴다). 이름표는 블록이 달라도 같다 — kr_names 참조.
NAME_TABLE = kr_names.name_table(WS)
NAME_W = kr_names.width_map(WS)
# `[WAIT]`({02})의 주인공 이름(세션24). 대사/나레이션/조건 리프의 {02}는 100% 주인공이고
# (아이템/병종명이 오는 건 UI 리프뿐), 이름은 개명 불가라 이름표 #1이 곧 실제 렌더 문자열이다.
PLAYER_NAME = {tag: tbl.get(1) for tag, tbl in NAME_TABLE.items()}    # L1 레딘 · L2 엘윈


def parse_id(id_str):
    """'L1:0/2/5#12' -> ('L1',(0,2,5),12) ; 'L2:101/2#5' -> ('L2',(101,2),5)."""
    tag, rest = id_str.split(":")
    path_s, seg_s = rest.split("#")
    return tag, tuple(int(x) for x in path_s.split("/")), int(seg_s)


def leaf_of(path):
    """(path[1],path[2]) 또는 짧은 id면 None."""
    return (path[1], path[2]) if len(path) >= 3 else None


def geometry(entry):
    """엔트리의 모든 id 를 보고 창 지오메트리/카테고리를 결정(reinsert 미러)."""
    leaves = []
    game = "?"
    for _id in entry["ids"]:
        tag, path, _ = parse_id(_id)
        game = tag
        lf = leaf_of(path)
        if lf:
            leaves.append(lf)
    fs = {lf for lf in leaves if lf in FULLSCREEN_GEOM}
    is_narr = bool(fs)                          # 전체화면 격자(대사 박스가 아님)
    is_ui   = any(lf == UI_LEAF for lf in leaves)
    is_dlg  = (not is_narr) and bool(leaves) and all(lf == DLG_LEAF for lf in leaves)
    is_title = bool(leaves) and all(lf == TITLE_LEAF for lf in leaves)
    goddess = bool(entry.get("absorb_box"))     # 여신/프롤로그 박스(흡수줄 예외)
    page2 = None                                # 2페이지+ 줄 수(None=1페이지와 동일)
    if is_narr:
        w = min(FULLSCREEN_GEOM[lf][0] for lf in fs)
        ml = min(FULLSCREEN_GEOM[lf][1] for lf in fs)
        cat, absorb = "/".join(FS_CAT[lf] for lf in sorted(fs)), False
    elif is_ui:
        cat, w, ml, absorb = "UI/메뉴", WIDTH, MAX_LINES, True
    elif is_dlg:
        cat, w, ml, absorb = "대사", WIDTH, MAX_LINES, True
        if not goddess:                          # 시나리오 대화: 2페이지+ 4줄, 흡수줄 없음
            page2, absorb = DLG_PAGE2_LINES, False
    elif is_title:
        cat, w, ml, absorb = "제목", WIDTH, MAX_LINES, True
    else:
        cat, w, ml, absorb = "기타", WIDTH, MAX_LINES, True
    sc = 1.0 if is_ui else 0.5      # UI = 전각 space(1.0칸), 그 외 = 반각 {01}(0.5칸)
    block = parse_id(entry["ids"][0])[1][0]
    return dict(game=game, cat=cat, w=w, ml=ml, absorb=absorb, sc=sc, page2=page2,
                goddess=goddess, block=block, is_narr=is_narr, is_ui=is_ui)


# ── 레이아웃(격자용): kr 마크업 -> 페이지 -> 줄 -> 셀 ─────────────────────────
def _emit_run(text, cells, sc):
    total = 0.0
    for ch in text:
        if ch == " ":
            cells.append({"t": "sp", "w": sc}); total += sc
        else:
            cells.append({"t": "ch", "c": ch, "w": 1}); total += 1
    return total


def layout_line(line, sc, names=None, player=None):
    """한 줄(마크업) -> (cells, width칸). [WAIT]/[MTE] 는 추정폭 칩, [C]/[RAW] 는 0폭.

    `names` = 이 게임의 {세그먼트: 이름} 표(kr_names). 주면 `[NAME:xx]` 칩이 **실제 이름과
    실제 칸수**로 그려진다(추정 4칸이 아니라 '베른하르트' 5칸 / '레딘' 2칸).
    `player` = 주인공 이름(엘윈/레딘). 주면 `[WAIT]` 칩도 실제 이름·실제 폭으로 그려진다
    (세션24: 대사/나레이션/조건 리프의 {02}는 100% 주인공 이름. UI 리프는 아이템명이라 None)."""
    cells, width, pos = [], 0.0, 0
    for m in M._ATOM.finditer(line):
        if m.start() > pos:
            width += _emit_run(line[pos:m.start()], cells, sc)
        tok = m.group(0)
        real = None
        if names and tok.startswith("[NAME:"):
            real = names.get(int(tok[6:-1], 16) + 1)     # {09 XX} = 세그먼트 #(XX+1)
        elif player and tok == "[WAIT]":
            real = player
        w = kr_names.cells(real) if real else M._atom_width(tok)
        kind = ("name" if tok.startswith("[NAME") else
                "wait" if tok == "[WAIT]" else
                "mte" if tok.startswith("[MTE") else
                "num" if tok == "[C:03]" else "ctrl")   # {03}=숫자(값) 삽입
        cells.append({"t": kind, "tok": (real or tok), "w": w})
        width += w
        pos = m.end()
    if pos < len(line):
        width += _emit_run(line[pos:], cells, sc)
    return cells, round(width, 2)


def layout_pages(kr, sc, names=None, player=None):
    """kr 마크업 -> [ page: [ line: {cells,width,blank} ] ]  (사용자 [NL]/[PAGE] 그대로)."""
    kr = kr.replace("\n", "[NL]")
    pages = []
    for page in kr.split("[PAGE]"):
        lines = []
        for raw in page.split("[NL]"):
            cells, width = layout_line(raw, sc, names, player)
            blank = not any(c["t"] in ("ch", "name", "wait", "mte") for c in cells)
            lines.append({"cells": cells, "width": width, "blank": blank})
        pages.append(lines)
    return pages


# reinsert의 has_markup 판정과 동일 (대괄호 컨트롤 토큰 유무). \n(줄바꿈)은 마크업 아님.
_MARKUP_RE = re.compile(r'\[(NAME|MTE|NL|PAGE|WAIT|C|RAW):?')


def _pieces_to_markup(pieces):
    """render_segment/parse 결과 pieces -> layout_pages용 마크업 문자열."""
    out = []
    for kind, val in pieces:
        if kind == "kr":
            out.append(val)
        elif val == M.CTRL_NL:
            out.append("[NL]")
        elif val == M.PAGE_BREAK:
            out.append("[PAGE]")
        elif val in (M.HW_SPACE, M.FW_SPACE):
            out.append(" ")
        elif len(val) == 2 and val[0] == 0x09:      # {09 XX} name var
            out.append("[NAME:%02x]" % val[1])
        elif val == b"\x02":                         # {02} wait/dynamic
            out.append("[WAIT]")
    return "".join(out)


def measure(kr, w, ml, sc, absorb, reflow, page2=None, sentence=None, game=None,
            is_ui=False):
    """미리보기 데이터: 사용자 원본 레이아웃 + 엔진(실제 게임) 결과 + 스킵 판정.

    reinsert 미러: 대괄호 마크업이 있으면 rewrap_markup(reflow), 없으면(평범한 텍스트+\\n)
    render_segment. page2=2페이지+ 줄 수(시나리오 대화=4, 이름 없음). None이면 1페이지와 동일.
    sentence=문장 단위 페이지네이션(세션21 규칙; reinsert는 manual_layout 항목에 적용). None이면
    수동 레이아웃(=reflow OFF)일 때 켜는 것으로 간주."""
    if sentence is None:
        sentence = not reflow
    names = NAME_TABLE.get(game)        # {세그먼트: 이름} — [NAME:xx]를 실제 폭으로
    name_w = NAME_W.get(game)           # {xx: 칸수} — 조판기에 넘길 표
    # {02}: UI 리프는 아이템/병종명(런타임)이라 추정 4칸, 그 외는 주인공 이름 확정(세션24).
    player = None if is_ui else PLAYER_NAME.get(game)
    wait_w = None if player is None else kr_names.cells(player)
    cap = max(ml, page2 or ml)          # 페이지 최대 줄 수(1페이지 ml, 2페이지+ page2)
    literal = layout_pages(kr, sc, names, player)
    over_w = any(ln["width"] > w + 1e-6 for pg in literal for ln in pg)
    over_l = any(len(pg) > cap for pg in literal)
    engine, skip, skip_reason, eng_maxw, eng_maxl = None, False, "", 0.0, 0
    space = M.FW_SPACE if sc >= 1.0 else M.HW_SPACE
    has_markup = bool(_MARKUP_RE.search(kr))
    try:
        if has_markup:
            engine_markup = M.rewrap_markup(kr, width=w, max_lines=ml, space_cells=sc,
                                            absorb=absorb, reflow=reflow, page2_lines=page2,
                                            sentence_pages=sentence, name_w=name_w,
                                            wait_w=wait_w)
            pieces = M.parse_markup(engine_markup, space=space, absorb=absorb)
        else:
            # 평범한 텍스트: reinsert처럼 render_segment (줄바꿈 유지 + 페이지네이션)
            pieces = kr_render.render_segment(kr, width=w, window_lines=ml, space=space,
                                              absorb=absorb, page2_lines=page2,
                                              sentence_pages=sentence)
            engine_markup = _pieces_to_markup(pieces)
        eng_maxl = M.max_page_lines(pieces)
        eng_maxw = round(M.max_line_width(pieces, name_w, wait_w), 2)
        if eng_maxl > cap:
            skip, skip_reason = True, f"페이지가 {cap}줄 초과({eng_maxl}줄)"
        elif eng_maxw > w + 1e-6:
            skip, skip_reason = True, f"줄이 {w}칸 초과({eng_maxw}칸)"
        engine = layout_pages(engine_markup, sc, names, player)
    except Exception as ex:
        skip, skip_reason = True, f"마크업 오류: {ex}"
    return dict(literal=literal, engine=engine, over_w=over_w, over_l=over_l,
                skip=skip, skip_reason=skip_reason,
                eng_maxw=eng_maxw, eng_maxl=eng_maxl, has_markup=has_markup,
                w=w, ml=ml, sc=sc, page2=page2)


# ── 목록 캐시(시작 시 1회) ───────────────────────────────────────────────────
_CAT_ORDER = {"나레이션": 0, "조건/튜토리얼": 1, "엔딩": 2, "대사": 3,
              "UI/메뉴": 4, "제목": 5, "기타": 6}


def scenario_titles():
    """블록(시나리오)별 제목 — 나레이션 리프(2,7)의 「…」 에서 추출."""
    titles = {}
    for e in WS:
        tag, path, _ = parse_id(e["ids"][0])
        if leaf_of(path) == NARR_LEAF:
            vis = re.sub(r"\[[^\]]*\]", "", e.get("kr", ""))
            m = re.search(r"「(.+?)」", vis)
            if m:
                titles[(tag, path[0])] = m.group(1).strip()
    return titles

TITLES = scenario_titles()


def build_index():
    idx = []
    for i, e in enumerate(WS):
        g = geometry(e)
        lit = layout_pages(e.get("kr", ""), g["sc"], NAME_TABLE.get(g["game"]),
                           None if g["is_ui"] else PLAYER_NAME.get(g["game"]))
        _c1, _c2 = g["ml"], (g.get("page2") or g["ml"])   # 1페이지 ml / 2페이지+ page2
        over = (any(ln["width"] > g["w"] + 1e-6 for pg in lit for ln in pg)
                or any(len(pg) > (_c1 if pi == 0 else _c2) for pi, pg in enumerate(lit)))
        kr = e.get("kr", "")
        idx.append({
            "i": i, "game": g["game"], "cat": g["cat"], "block": g["block"],
            "stitle": TITLES.get((g["game"], g["block"]), ""),
            "id0": e["ids"][0], "count": e.get("count", len(e["ids"])),
            "jp": e.get("jp", "")[:70], "kr": kr[:70],
            "empty": not kr.strip(), "over": over,
            "manual": bool(e.get("manual_layout")),
            "lines": e.get("lines", 1),
            # 정렬: 게임 → 시나리오(블록) → 종류 → 순번  (시나리오별 순서대로)
            "_sort": (0 if g["game"] == "L1" else 1, g["block"],
                      _CAT_ORDER.get(g["cat"], 9), parse_id(e["ids"][0])[2]),
        })
    idx.sort(key=lambda r: r["_sort"])
    for r in idx:
        del r["_sort"]
    return idx

INDEX = build_index()


# ── 저장 ─────────────────────────────────────────────────────────────────────
def save_entry(i, kr, manual_layout):
    # 검증: 마크업이 파싱되어야 저장
    M.parse_markup(kr)
    if not _backed_up[0]:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = os.path.join(ROOT, "build", f"worksheet_dedup_final.backup_editor_{ts}.json")
        shutil.copy2(WS_PATH, bak)
        _backed_up[0] = True
        print(f"[backup] {bak}")
    WS[i]["kr"] = kr
    if manual_layout:
        WS[i]["manual_layout"] = True
    else:
        WS[i].pop("manual_layout", None)
        # 수동 레이아웃을 끄면 문장 단위 페이지네이션(세션21)도 함께 해제 — reinsert가
        # reflow로 되돌리는데 페이지만 문장 단위로 끊으면 조판이 어긋난다.
        WS[i].pop("sentence_layout", None)
    tmp = WS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(WS, f, ensure_ascii=False)
    os.replace(tmp, WS_PATH)
    # 인덱스 캐시 갱신
    g = geometry(WS[i])
    lit = layout_pages(kr, g["sc"], NAME_TABLE.get(g["game"]),
                       None if g["is_ui"] else PLAYER_NAME.get(g["game"]))
    _c1, _c2 = g["ml"], (g.get("page2") or g["ml"])
    over = (any(ln["width"] > g["w"] + 1e-6 for pg in lit for ln in pg)
            or any(len(pg) > (_c1 if pi == 0 else _c2) for pi, pg in enumerate(lit)))
    for r in INDEX:
        if r["i"] == i:
            r["kr"] = kr[:70]; r["empty"] = not kr.strip()
            r["over"] = over; r["manual"] = manual_layout
            break
    return over


# ── HTTP 핸들러 ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):    # 조용히
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._send(200, HTML, "text/html; charset=utf-8")
        if p == "/neodgm.ttf":
            with open(FONT_PATH, "rb") as f:
                return self._send(200, f.read(), "font/ttf")
        if p == "/api/list":
            return self._send(200, INDEX)
        if p == "/api/entry":
            q = dict(pair.split("=") for pair in self.path.split("?", 1)[1].split("&"))
            i = int(q["i"])
            e = WS[i]; g = geometry(e)
            return self._send(200, {
                "i": i, "jp": e.get("jp", ""), "kr": e.get("kr", ""),
                "ids": e["ids"], "count": e.get("count", len(e["ids"])),
                "manual": bool(e.get("manual_layout")),
                "sentence": bool(e.get("sentence_layout")),
                "geom": {k: g[k] for k in ("game", "cat", "w", "ml", "absorb", "sc",
                                           "block", "is_narr", "is_ui", "page2", "goddess")},
            })
        return self._send(404, {"err": "not found"})

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            b = self._body()
            if p == "/api/measure":
                return self._send(200, measure(
                    b["kr"], b["w"], b["ml"], b["sc"], b["absorb"], b["reflow"],
                    b.get("page2"), b.get("sentence"), b.get("game"),
                    bool(b.get("is_ui"))))
            if p == "/api/save":
                over = save_entry(b["i"], b["kr"], b.get("manual_layout", True))
                return self._send(200, {"ok": True, "over": over})
        except Exception as ex:
            return self._send(200, {"ok": False, "err": str(ex)})
        return self._send(404, {"err": "not found"})


HTML = r"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>랑그릿사 대사 검수</title>
<style>
@font-face{font-family:neodgm;src:url(/neodgm.ttf) format('truetype');}
:root{--cell:26px;--row:32px;--bg:#12141a;--panel:#1a1d26;--line:#2a2f3d;
  --fg:#e6e8ee;--mut:#8b93a7;--accent:#5b9dff;--ok:#3ecf8e;--warn:#ffb454;--bad:#ff5d6c;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,'Malgun Gothic',sans-serif;height:100vh;display:flex;overflow:hidden}
#side{width:340px;min-width:340px;border-right:1px solid var(--line);display:flex;flex-direction:column;background:var(--panel)}
#filters{padding:10px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:8px}
#filters .row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
input,select,textarea,button{font-family:inherit}
#q{flex:1;background:var(--bg);border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:6px 8px}
.chip{background:var(--bg);border:1px solid var(--line);color:var(--mut);border-radius:20px;padding:3px 10px;cursor:pointer;font-size:12px}
.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
#list{flex:1;overflow-y:auto}
.item{padding:8px 10px;border-bottom:1px solid var(--line);cursor:pointer}
.item:hover{background:#20242f}
.item.sel{background:#26314a}
.sec{position:sticky;top:0;background:#0f1723;color:#7fb4ff;font-size:11px;font-weight:700;
  padding:6px 10px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);z-index:2;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .m{display:flex;gap:6px;align-items:center;font-size:11px;color:var(--mut);margin-bottom:2px}
.item .kr{font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--fg)}
.item.empty .kr{color:var(--warn);font-style:italic}
.badge{font-size:10px;padding:1px 6px;border-radius:4px;background:#2a2f3d;color:var(--mut)}
.badge.g{background:#243b2e;color:#7fe0b0}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
.dot.over{background:var(--bad)} .dot.man{background:var(--accent)}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#head{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
#head .t{font-size:15px;font-weight:600}
#head .meta{color:var(--mut);font-size:12px}
#body{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card h3{margin:0 0 8px;font-size:12px;color:var(--mut);font-weight:600;letter-spacing:.03em;text-transform:uppercase}
#jp{font-family:'Malgun Gothic',sans-serif;color:var(--mut);white-space:pre-wrap;font-size:13px}
/* 편집창: 투명 textarea 위에 색상 강조 pre 를 겹침 */
.editor{position:relative;height:220px}
.editor pre.hl,.editor textarea{margin:0;font:15px/1.8 'Malgun Gothic',monospace;padding:10px;
  border:1px solid var(--line);border-radius:8px;white-space:pre-wrap;word-break:break-word;
  overflow-wrap:break-word;box-sizing:border-box;position:absolute;inset:0;letter-spacing:0;
  tab-size:4;overflow-y:scroll;overflow-x:hidden}   /* 둘 다 스크롤바 gutter 고정 → 줄바꿈 폭 일치 */
.editor pre.hl{color:#f2f4fa;background:var(--bg);pointer-events:none;z-index:0}
.editor textarea{background:transparent;color:transparent;caret-color:#7fe0b0;z-index:1;resize:none;width:100%}
.editor textarea::selection{background:#2b62a355;color:transparent}
/* 토큰은 색상만 다르게 — bold/size 금지(글자 폭이 바뀌면 textarea 캐럿과 어긋남) */
.hl .tok{color:#3f4658}                 /* [C:xx]/[RAW] 서식·정렬 코드 = 아주 흐리게 */
.hl .tok.br{color:#6aa8ff}              /* [NL]/[PAGE] = 파랑(구조) */
.hl .tok.nm{color:#3ecf8e}              /* [NAME]/[WAIT]/[MTE] = 초록(치환값) */
.hl .tok.num{color:#ffb454}             /* [C:03] = 호박색(숫자 삽입) */
#toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
#toolbar button{background:#232734;border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:6px 10px;cursor:pointer}
#toolbar button:hover{border-color:var(--accent)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;margin:0 0 8px}
.legend span{white-space:nowrap}
#save{background:var(--ok);border-color:var(--ok);color:#062;font-weight:600}
#save.dirty{box-shadow:0 0 0 2px var(--ok)}
.status{font-size:12px;color:var(--mut);display:flex;gap:14px;flex-wrap:wrap;align-items:center}
.pill{padding:2px 8px;border-radius:12px;font-size:11px}
.pill.ok{background:#173a2a;color:var(--ok)} .pill.bad{background:#3a1a20;color:var(--bad)}
/* 격자 미리보기 */
.pages{display:flex;flex-direction:column;gap:12px}
.page{background:#0c0e13;border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.page .plabel{font-size:11px;color:var(--mut);margin-bottom:6px}
.win{position:relative;width:max-content}
.ruler{display:flex;height:14px;margin-bottom:2px}
.ruler .u{width:var(--cell);text-align:center;font-size:9px;color:#4a5162;border-left:1px solid #1c2029}
.line{position:relative;height:var(--row);display:flex;align-items:center;white-space:nowrap}
.line .cell{width:var(--cell);height:var(--row);display:flex;align-items:center;justify-content:center;
  font-family:neodgm;font-size:22px;color:#eef1f8;flex:0 0 auto}
.line .sp{height:var(--row);flex:0 0 auto;background:repeating-linear-gradient(45deg,#171b24,#171b24 3px,transparent 3px,transparent 6px)}
.line .ctrl{height:18px;align-self:center;font-family:monospace;font-size:9px;color:#6b7280;background:#1c2029;border:1px solid #2a2f3d;border-radius:3px;padding:0 3px;margin:0 1px;flex:0 0 auto;display:flex;align-items:center}
.line .chip{height:var(--row);background:#243b2e;color:#7fe0b0;border:1px dashed #3ecf8e;border-radius:4px;
  font-size:10px;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
.line .numc{height:18px;align-self:center;font-size:9px;color:#ffb454;background:#3a2e17;border:1px solid #ffb454;
  border-radius:3px;padding:0 4px;margin:0 1px;flex:0 0 auto;display:flex;align-items:center}
.line .gap{height:var(--row);flex:0 0 auto}   /* 숨김 모드에서 숫자 자리 빈칸 */
.line.over .cell{color:var(--bad)}
.wcount{position:absolute;left:100%;top:0;height:var(--row);display:flex;align-items:center;padding-left:8px;font-size:10px;color:var(--mut);white-space:nowrap}
.wcount.bad{color:var(--bad)}
.bound{position:absolute;top:0;bottom:0;width:0;border-left:2px dashed #3a4152;pointer-events:none}
.blankmark{color:#4a5162;font-size:10px;font-style:italic;padding-left:6px}
.row-over{color:var(--bad);font-size:11px;padding-left:6px}
.tabs{display:flex;gap:6px;margin-bottom:8px}
.tab{padding:4px 10px;border-radius:6px;font-size:12px;color:var(--mut);cursor:pointer;border:1px solid transparent}
.tab.on{color:var(--fg);border-color:var(--line);background:var(--bg)}
#idlist{font-size:11px;color:var(--mut);max-height:60px;overflow-y:auto;font-family:monospace}
label.sw{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--mut);cursor:pointer}
#empty{color:var(--mut);margin:auto;text-align:center}
</style></head><body>
<div id=side>
  <div id=filters>
    <div class=row><input id=q placeholder="검색 (한/일/id)…"></div>
    <div class=row id=gamechips>
      <span class="chip on" data-g="">전체</span>
      <span class=chip data-g=L1>L1</span><span class=chip data-g=L2>L2</span>
    </div>
    <div class=row id=catchips>
      <span class="chip on" data-c="">전체</span>
      <span class=chip data-c=나레이션>나레이션</span>
      <span class=chip data-c=대사>대사</span>
      <span class=chip data-c=UI/메뉴>UI</span>
      <span class=chip data-c=제목>제목</span>
      <span class=chip data-c=기타>기타</span>
    </div>
    <div class=row>
      <label class=sw><input type=checkbox id=fover> 오버플로만</label>
      <label class=sw><input type=checkbox id=fempty> 미번역만</label>
      <span id=count style="margin-left:auto;color:var(--mut);font-size:11px"></span>
    </div>
  </div>
  <div id=list></div>
</div>
<div id=main>
  <div id=head><div id=empty>왼쪽에서 대사를 고르세요</div></div>
  <div id=body></div>
</div>
<script>
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let LIST=[], FILT={g:'',c:'',over:false,empty:false,q:''}, CUR=null, DIRTY=false, VIEW='engine';

function catBadge(c){return c;}
async function loadList(){LIST=await (await fetch('/api/list')).json(); render();}
function passes(r){
  if(FILT.g && r.game!==FILT.g) return false;
  if(FILT.c && r.cat!==FILT.c) return false;
  if(FILT.over && !r.over) return false;
  if(FILT.empty && !r.empty) return false;
  if(FILT.q){const q=FILT.q.toLowerCase();
    if(!(r.kr.toLowerCase().includes(q)||r.jp.toLowerCase().includes(q)||r.id0.toLowerCase().includes(q)
        ||(r.stitle&&r.stitle.toLowerCase().includes(q)))) return false;}
  return true;
}
function render(){
  const rows=LIST.filter(passes);
  $('#count').textContent=rows.length+' / '+LIST.length;
  const box=$('#list'); box.innerHTML='';
  const frag=document.createDocumentFragment();
  let prevKey=null;
  rows.forEach(r=>{
    const key=r.game+'/'+r.block;
    if(key!==prevKey){                       // 시나리오(블록) 바뀔 때 구분 헤더
      prevKey=key;
      const h=document.createElement('div');h.className='sec';
      h.textContent=`${r.game} · 시나리오 ${r.block}`+(r.stitle?`  「${r.stitle}」`:'');
      frag.appendChild(h);
    }
    const d=document.createElement('div');
    d.className='item'+(r.empty?' empty':'')+(CUR&&CUR.i===r.i?' sel':'');
    d.innerHTML=`<div class=m><span class="badge g">${r.game}</span>
      <span class=badge>${r.cat}</span><span class=badge>블록${r.block}</span>
      ${r.over?'<span class="dot over" title=오버플로></span>':''}
      ${r.manual?'<span class="dot man" title="수동 레이아웃"></span>':''}
      <span style="margin-left:auto;font-family:monospace">${r.id0}</span></div>
      <div class=kr>${r.empty?'(미번역) '+esc(r.jp):esc(r.kr)}</div>`;
    d.onclick=()=>openEntry(r.i);
    frag.appendChild(d);
  });
  box.appendChild(frag);
}
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

async function openEntry(i){
  if(DIRTY && !confirm('저장하지 않은 변경이 있습니다. 버릴까요?')) return;
  CUR=await (await fetch('/api/entry?i='+i)).json(); DIRTY=false; render();
  const g=CUR.geom;
  const dims = g.page2 ? `${g.w}칸 · 1p ${g.ml}줄(이름) / 2p+ ${g.page2}줄(이름없음)` : `${g.w}칸 × ${g.ml}줄`;
  $('#head').innerHTML=`<span class=t>${g.cat} · ${dims}${g.goddess?' · 여신박스(예외)':''}</span>
    <span class=meta>${g.game} · 블록${g.block} · 중복 ${CUR.count}곳 · ${g.is_ui?'전각space':'반각space {01}'}</span>
    <label class=sw style="margin-left:auto"><input type=checkbox id=manual ${CUR.manual?'checked':''}> 수동 레이아웃(내 줄바꿈 고정)</label>`;
  $('#manual').onchange=()=>{DIRTY=true;markDirty();remeasure();};
  $('#body').innerHTML=`
    <div class=card><h3>일본어 원문</h3><div id=jp>${esc(CUR.jp)||'(없음)'}</div></div>
    <div class=card>
      <div id=toolbar>
        <button onclick="ins('[NL]')">⏎ 줄바꿈 [NL]</button>
        <button onclick="ins('[PAGE]')">▤ 페이지 [PAGE]</button>
        <button onclick="ins('[WAIT]')">[WAIT]</button>
        <button id=save onclick=save()>저장</button>
        <span class=status id=st></span>
      </div>
      <div class=legend>
        <span style="color:#f2f4fa">한글=대사</span>
        <span style="color:#ffb454">[C:03] 숫자삽입</span>
        <span style="color:#5b9dff">[NL]/[PAGE] 줄·페이지</span>
        <span style="color:#3ecf8e">[NAME]/[WAIT] 치환값</span>
        <span style="color:#3f4658">[C:05]류 서식/정렬</span>
      </div>
      <div class=editor><pre class=hl id=hl></pre><textarea id=kr spellcheck=false>${esc(CUR.kr)}</textarea></div>
    </div>
    <div class=card>
      <div class=tabs>
        <span class="tab on" data-v=engine onclick="setView('engine')">실제 게임 표시</span>
        <span class=tab data-v=literal onclick="setView('literal')">내가 입력한 그대로</span>
        <label class=sw style="margin-left:auto"><input type=checkbox id=hidecodes checked> 서식코드 숨기기</label>
      </div>
      <div id=preview></div>
    </div>
    <div class=card><h3>적용 위치 (${CUR.ids.length})</h3><div id=idlist>${CUR.ids.join('  ')}</div></div>`;
  const ta=$('#kr');
  ta.addEventListener('input',()=>{DIRTY=true;markDirty();syncHL();remeasure();});
  ta.addEventListener('scroll',syncHL);
  ta.addEventListener('keydown',onKeydown);
  $('#hidecodes').addEventListener('change',()=>doMeasure());
  syncHL();
  remeasure();
}
function hlEsc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function highlight(v){
  return hlEsc(v).replace(/\[(?:NL|PAGE|WAIT)\]|\[(?:NAME|MTE|C|RAW):[0-9A-Fa-f]+\]/g,m=>{
    let cls='tok';
    if(m==='[NL]'||m==='[PAGE]') cls+=' br';
    else if(m==='[WAIT]'||m.startsWith('[NAME')||m.startsWith('[MTE')) cls+=' nm';
    else if(m==='[C:03]') cls+=' num';
    return '<span class="'+cls+'">'+m+'</span>';
  })+'\n';
}
function syncHL(){const t=$('#kr'),h=$('#hl');if(!t||!h)return;
  h.innerHTML=highlight(t.value);h.scrollTop=t.scrollTop;h.scrollLeft=t.scrollLeft;}
// 백스페이스/딜리트 시 캐럿 옆의 완결된 토큰([NL]/[PAGE]/[WAIT]/[C:xx]/[NAME:xx]/[MTE:xx]/[RAW:..])을 통째로 삭제
const TOKSRC='\\[(?:NL|PAGE|WAIT)\\]|\\[(?:NAME|MTE|C|RAW):[0-9A-Fa-f]+\\]';
function onKeydown(e){
  if(e.key!=='Backspace'&&e.key!=='Delete') return;
  const t=e.target; if(t.selectionStart!==t.selectionEnd) return;   // 선택 삭제는 기본동작
  const pos=t.selectionStart, v=t.value;
  let m;
  if(e.key==='Backspace'){
    m=v.slice(0,pos).match(new RegExp('(?:'+TOKSRC+')$'));
    if(!m) return;
    e.preventDefault();
    t.setRangeText('',pos-m[0].length,pos,'start');       // 앞쪽 토큰 통째 삭제(undo 보존)
  }else{
    m=v.slice(pos).match(new RegExp('^(?:'+TOKSRC+')'));
    if(!m) return;
    e.preventDefault();
    t.setRangeText('',pos,pos+m[0].length,'start');       // 뒤쪽 토큰 통째 삭제
  }
  DIRTY=true;markDirty();syncHL();remeasure();
}
function markDirty(){const b=$('#save');if(b)b.classList.toggle('dirty',DIRTY);}
function ins(tok){const t=$('#kr');const s=t.selectionStart,e=t.selectionEnd;
  t.value=t.value.slice(0,s)+tok+t.value.slice(e);t.selectionStart=t.selectionEnd=s+tok.length;
  t.focus();DIRTY=true;markDirty();syncHL();remeasure();}
function setView(v){VIEW=v;$$('.tab').forEach(t=>t.classList.toggle('on',t.dataset.v===v));remeasure();}

let mt=null;
function remeasure(){clearTimeout(mt);mt=setTimeout(doMeasure,120);}
async function doMeasure(){
  if(!CUR) return;
  const g=CUR.geom;
  const manual = $('#manual') && $('#manual').checked;
  const reflow = !manual;               // 수동=OFF, 자동=ON
  const r=await (await fetch('/api/measure',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({kr:$('#kr').value,w:g.w,ml:g.ml,sc:g.sc,absorb:g.absorb,reflow,page2:g.page2,sentence:(manual&&CUR.sentence!==false),game:g.game,is_ui:g.is_ui})})).json();
  drawPreview(r,g);
  const st=$('#st');
  // 마크업 없는 평범한 텍스트는 reinsert가 render_segment 사용(줄바꿈 유지, reflow 무관)
  const ship = !r.has_markup ? '평범한 텍스트 — 줄바꿈 유지 + '+g.w+'칸 자동 워드랩'
             : (manual ? '내 줄바꿈 그대로 게임 반영' : '게임이 자동 재배치(reflow)');
  st.innerHTML = (r.skip
      ? `<span class="pill bad">미적용(SKIP): ${r.skip_reason}</span>`
      : `<span class="pill ok">적용됨</span>`)
    + `<span>최대 ${r.eng_maxw}칸 / ${r.eng_maxl}줄</span><span>· ${ship}</span>`;
}
function drawPreview(r,g){
  const pages = (VIEW==='engine' ? r.engine : r.literal) || [];
  const wrap=document.createElement('div'); wrap.className='pages';
  pages.forEach((pg,pi)=>{
    const pd=document.createElement('div');pd.className='page';
    // 1페이지 = ml줄, 2페이지+ = page2줄(이름 없는 시나리오 대화 4줄). 여신/기타는 page2=null.
    const cap = (pi===0 ? g.ml : (g.page2||g.ml));
    const nameNote = (pi>0 && g.page2) ? ' · 이름 없음' : '';
    const over=pg.length>cap;
    pd.innerHTML=`<div class=plabel>페이지 ${pi+1} · ${pg.length}/${cap}줄${nameNote} ${over?'<span class=row-over>⚠ 줄 수 초과</span>':''}</div>`;
    const win=document.createElement('div');win.className='win';
    // 눈금자
    const ruler=document.createElement('div');ruler.className='ruler';
    for(let c=0;c<g.w;c++){const u=document.createElement('div');u.className='u';u.textContent=(c+1)%2?'':(c+1);ruler.appendChild(u);}
    win.appendChild(ruler);
    // 창 경계선
    const bnd=document.createElement('div');bnd.className='bound';bnd.style.left=`calc(var(--cell) * ${g.w})`;win.appendChild(bnd);
    pg.forEach((ln,li)=>{
      const rowOver = li>=cap;
      const hide=$('#hidecodes')&&$('#hidecodes').checked;
      const L=document.createElement('div');L.className='line'+(ln.width>g.w+1e-6?' over':'');
      ln.cells.forEach(cl=>{
        if(hide){
          if(cl.t==='ctrl'){
            if(cl.tok==='[C:05]'){                // {05}=커서 +1타일=8px=0.5칸 (RE 확증) → 0.5칸 비움
              const gp=document.createElement('div');gp.className='gap';gp.style.width='calc(var(--cell) * 0.5)';
              L.appendChild(gp);}
            return;                               // 그 외 [C:xx]/[RAW]: 0폭 접음
          }
          if(cl.t==='num'){                       // [C:03] 숫자: 칩 숨기고 1칸 비워둠(글자 위치 보존)
            const gp=document.createElement('div');gp.className='gap';gp.style.width='var(--cell)';
            L.appendChild(gp);return;}
        }
        const el=document.createElement('div');
        if(cl.t==='ch'){el.className='cell';el.textContent=cl.c;}
        else if(cl.t==='sp'){el.className='sp';el.style.width=`calc(var(--cell) * ${cl.w})`;}
        else if(cl.t==='name'||cl.t==='wait'||cl.t==='mte'){el.className='chip';el.style.width=`calc(var(--cell) * ${cl.w})`;el.textContent=cl.tok;}
        else if(cl.t==='num'){el.className='numc';el.textContent='숫자';}
        else {el.className='ctrl';el.textContent=cl.tok;}
        L.appendChild(el);
      });
      const wc=document.createElement('div');wc.className='wcount'+(ln.width>g.w+1e-6?' bad':'');
      wc.textContent=ln.width+'칸'+(ln.blank?' · 빈줄':'')+(rowOver?' · ⚠줄초과':'');
      L.appendChild(wc);
      win.appendChild(L);
    });
    pd.appendChild(win);wrap.appendChild(pd);
  });
  if(!pages.length){wrap.innerHTML='<div style="color:#8b93a7">(내용 없음)</div>';}
  $('#preview').innerHTML='';$('#preview').appendChild(wrap);
}
async function save(){
  if(!CUR) return;
  const manual = $('#manual') ? $('#manual').checked : true;
  const r=await (await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({i:CUR.i,kr:$('#kr').value,manual_layout:manual})})).json();
  if(r.ok){DIRTY=false;markDirty();
    const it=LIST.find(x=>x.i===CUR.i);if(it){it.kr=$('#kr').value.slice(0,70);it.empty=!$('#kr').value.trim();it.over=r.over;it.manual=manual;}
    render();
    const st=$('#st');const old=st.innerHTML;st.innerHTML='<span class="pill ok">저장됨 ✓</span>'+old;
  } else alert('저장 실패: '+r.err);
}
// 필터 이벤트
let qtimer=null;
$('#q').addEventListener('input',e=>{FILT.q=e.target.value;clearTimeout(qtimer);qtimer=setTimeout(render,140);});
$('#fover').addEventListener('change',e=>{FILT.over=e.target.checked;render();});
$('#fempty').addEventListener('change',e=>{FILT.empty=e.target.checked;render();});
$$('#gamechips .chip').forEach(c=>c.onclick=()=>{$$('#gamechips .chip').forEach(x=>x.classList.remove('on'));c.classList.add('on');FILT.g=c.dataset.g;render();});
$$('#catchips .chip').forEach(c=>c.onclick=()=>{$$('#catchips .chip').forEach(x=>x.classList.remove('on'));c.classList.add('on');FILT.c=c.dataset.c;render();});
window.ins=ins;window.save=save;window.setView=setView;
loadList();
</script></body></html>"""


def main():
    print(f"워크시트: {WS_PATH}  ({len(WS)} 엔트리, 인덱스 {len(INDEX)})")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"대사 검수 툴 → {url}   (Ctrl+C 로 종료)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료.")


if __name__ == "__main__":
    main()
