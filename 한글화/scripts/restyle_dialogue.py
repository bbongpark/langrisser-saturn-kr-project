#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
restyle_dialogue.py — 대사(2,5) 전체를 세션21 조판 규칙으로 재조판한다.

세션21 사용자 규칙(정본):
  1. 문장이 끝나면 줄을 바꾼다.                     → 문장 사이에만 [NL]
  2. 그 외에는 일부러 줄바꿈을 넣지 않는다.          → 문장 중간 [NL] 전부 제거(자동 워드랩에 맡김)
  3. 가독성을 생각한다.                              → 어절 경계 공백 복원, 부호 뒤 공백 정리
  4. 처음 여신 대사는 건드리지 않는다.                → L1:20 / L2:98(캐릭터메이킹) 블록 전면 제외
  5. 문장 중간에 페이지가 넘어가면 그 문장을 다음      → [PAGE] 제거 + manual_layout=true
     페이지로 넘긴다.                                  (reinsert가 sentence_pages로 문장 단위 페이지네이션)
  6. 문장부호는 반각으로 통일(사용자 확정).            → ，→, ‥→… 。→. ！→!

동작:
  - 대상 = 모든 ids의 리프가 (2,5)인 항목(=reinsert의 is_dialogue와 같은 기준). 여신 블록에
    한 곳이라도 걸치면 제외.
  - kr의 [PAGE]/[NL]/\\n 을 전부 풀어 한 흐름으로 만든 뒤 문장 단위로 다시 나눠 [NL]로 잇는다.
  - 재조판한 항목에 manual_layout=true 를 달아 reinsert가 reflow를 끄고 문장 단위로 페이지를 끊게 한다.
  - 저장 전에 rewrap/parse로 칸수·페이지 줄수를 전수 검증한다(초과 항목은 리포트).

사용:
  python scripts/restyle_dialogue.py --dry-run     # 통계 + 샘플만 (기본)
  python scripts/restyle_dialogue.py --apply       # 백업 후 워크시트에 반영
  python scripts/restyle_dialogue.py --apply --report build/restyle_report.json
"""
import argparse
import datetime
import json
import os
import re
import sys

# 콘솔 인코딩: sys.stdout.buffer를 TextIOWrapper로 다시 감싸면, 한 프로세스에서 두 모듈이
# 각자 감쌌을 때 먼저 만든 래퍼가 GC되며 buffer를 닫아 "I/O operation on closed file"이 난다
# (apply_fixes → restyle_dialogue import 조합에서 실제로 터졌다). reconfigure는 감싸지 않는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kr_markup as M                       # noqa: E402
import kr_render                            # noqa: E402

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")
DLG_LEAF = (2, 5)
# 여신(캐릭터메이킹) 블록 — 사용자 지시로 전면 동결
FROZEN_BLOCKS = {("L1", 20), ("L2", 98)}

WIDTH = 14
MAX_LINES = 3            # 1페이지(이름줄 아래)
PAGE2_LINES = 4          # 2페이지+(이름 없음)

_ID = re.compile(r"(L\d):(\d+)/(\d+)/(\d+)#(\d+)$")
_ATOM = M._ATOM          # [NAME:xx] / [WAIT] / [C:xx] / [MTE:xx] / [NL] / [PAGE] / [RAW:..]
# 화면에 아무것도 그리지 않는 0폭 제어 토큰. [NAME]/[WAIT]/[MTE]는 런타임에 글자로 펼쳐지는
# '가시 토큰'이라 여기 넣으면 안 된다(넣었더니 "괜찮아![NL][NAME:03]!"가 한 줄로 붙었다).
_CTRL_TOK = re.compile(r"\[(?:C|RAW):[0-9A-Fa-f]+\]")

# ── 문장부호 반각 통일 ────────────────────────────────────────────────────────
PUNCT_MAP = {"，": ",", "．": ".", "。": ".", "、": ",",
             "！": "!", "？": "?", "：": ":", "；": ";",
             "‥": "…"}

# 문장 종결 부호(반각 통일 후)와, 종결부호 뒤에 붙어 따라오는 닫는 기호
TERMS = ".!?"
CLOSERS = "\"'」』）)]”’》〉"
# 여는 기호(뒤에 공백을 넣지 않는다)
OPENERS = "(（「『《〈[“‘"
# 줄을 이을 때 앞에 공백을 두지 않는 선두 문자(닫는 부호·쉼표류)
NOSPACE_LEAD = M._NOSPACE_LEAD + CLOSERS

# '…' 가 문장 끝인지 판정할 때 쓰는 한국어 종결 표지(보수적으로 강한 것만).
# 1음절 표지는 오분리가 잦은 것('나','지','자','라' 등 — 대명사/조사와 겹침)을 빼고,
# 의문형은 겹칠 일이 없는 복합 표지로만 잡는다('무리였는가…', '죽었나…').
_FINAL_ENDING = re.compile(r"(?:다|까|요|죠|군|네|냐|는가|은가|던가|인가|을까|겠나|었나|았나|구나)$")


def parse_id(s):
    m = _ID.match(s)
    if not m:
        return None
    return (m.group(1), int(m.group(2)), (int(m.group(3)), int(m.group(4))), int(m.group(5)))


def normalize_punct(s):
    for a, b in PUNCT_MAP.items():
        s = s.replace(a, b)
    # 말줄임표 뒤 마침표 제거: 원문 '‥‥。'의 직역이라 406곳에 남아 있었다. 게임 자막
    # 관례대로 '…'만 남긴다("어리석은 놈들……." → "어리석은 놈들……").
    s = re.sub(r"(…+)\.(?!\.)", r"\1", s)
    return s


# ── 맞춤법 자동 교정(전수 검수에서 확인한 확실한 것만) ───────────────────────────
ORTHO = [
    # 부정 부사 '안'은 띄어 쓴다: 말도 안되는 → 말도 안 되는.
    # 뒤 글자 범위 돼-됳 = '돼'~'됳' + '되'~'됳' — 되다의 모든 활용형(되/된/될/됐/됩…)을
    # 덮는다. [되돼]로만 쓰면 '안된다/안될/안됐다'를 통째로 놓친다(실제로 놓쳤다).
    (re.compile(r"(?<![가-힣])안(?=[돼-됳])"), "안 "),
    # 보조용언 '않다'도 띄어 쓴다: 좋지않은 → 좋지 않은. '머지않아'는 한 단어라 예외
    (re.compile(r"(?<!머)지않"), "지 않"),
    # 보조용언 '말다': 죽지마라 → 죽지 마라 / 신경쓰지말고 → 신경 쓰지 말고
    (re.compile(r"(?<=[가-힣])지(?=마[라세요!?.…,\s]|마$|말[고아자])"), "지 "),
    # '~야 하다': 해야할까 → 해야 할까. 뒤가 '하/해'로 시작하는 활용형이면 모두.
    (re.compile(r"(?<=[가-힣])야(?=[하해한할함합했])"), "야 "),
    # '-ㄹ게'를 '-ㄹ께'로 쓴 것: 구해줄께 → 구해줄게 (아래 _fix_kke가 ㄹ받침일 때만 바꾼다.
    # '님께/폐하께'의 높임 조사 '께'는 건드리면 안 된다)
    # 의존명사 띄어쓰기
    (re.compile(r"([날갈올볼들])때"), r"\1 때"),
    # '것'의 준말 '건' — 아래 _fix_geon()이 종성으로 판정해 처리(정규식만으로는 '된건가'처럼
    # 관형형 ㄴ이 앞 글자에 합쳐진 형태를 못 잡는다).
    (re.compile(r"(?<=[가-힣])([을던는])줄(?=[이은을도])"), r"\1 줄"),
    (re.compile(r"(?<=[가-힣])할줄"), "할 줄"),
    (re.compile(r"(?<=[가-힣])([던는을])것"), r"\1 것"),
    (re.compile(r"(?<=[가-힣])([았었])을텐데"), r"\1을 텐데"),
    # 인명 뒤 '님'은 의존명사라 띄어 쓴다: [NAME:0d]님 → [NAME:0d] 님 (251+18곳, 표기 혼재였음).
    # '왕자님/사제님'처럼 일반명사+님(접미사)은 붙여 쓰므로 토큰 뒤만 건드린다.
    (re.compile(r"(\[(?:NAME:[0-9A-Fa-f]+|WAIT)\])님"), r"\1 님"),
    # 쉼표 뒤에는 공백을 둔다(15곳 누락). 게임 렌더는 parse_markup이 부호 뒤 공백 바이트를
    # 지우므로 화면은 그대로지만, 워드랩이 어절 경계를 잡을 수 있게 된다.
    (re.compile(r",(?=[가-힣\[])"), ", "),
    # 물음표+느낌표 순서 통일 — 다수파이자 스팀판 표기인 '!?'로 (?! 73곳)
    (re.compile(r"\?!"), "!?"),
    # '명사 + 못 하다'(부정)는 띄어 쓴다: 용서못해 → 용서 못 해.
    # '깨닫지 못하는/믿지 못할' 같은 보조용언 '-지 못하다'는 붙여 쓰는 게 맞으므로 건드리지 않는다.
    (re.compile(r"(?<![가-힣])(용서|용납|통과|이해|납득|상상|짐작)\s*못([해한할했하])"), r"\1 못 \2"),
    # 붙여 써야 하는 것 / 표준 표기
    (re.compile(r"수 밖에"), "수밖에"),
    (re.compile(r"할께"), "할게"),
    (re.compile(r"(?<=[가-힣])알고있"), "알고 있"),
    (re.compile(r"^알고있"), "알고 있"),
    (re.compile(r"애시당초"), "애당초"),
]


_KKE = re.compile(r"([가-힣])께")


def _fix_kke(s):
    """'-ㄹ께' → '-ㄹ게'(어미). 앞 글자가 ㄹ받침일 때만 — '님께/폐하께'(높임 조사)는 보존."""
    def rep(m):
        prev = m.group(1)
        return f"{prev}게" if (ord(prev) - 0xAC00) % 28 == 8 else m.group(0)
    return _KKE.sub(rep, s)


_GEON = re.compile(r"([가-힣])(건가|건지|건데|거야|거지|거다)(?![가-힣])")


def _fix_geon(s):
    """관형형(종성 ㄴ/ㄹ) 뒤의 의존명사 '건/거'를 띄운다: 된건가 → 된 건가.
    '사건가'처럼 앞 글자에 ㄴ/ㄹ 받침이 없으면 손대지 않는다."""
    def rep(m):
        prev, dep = m.group(1), m.group(2)
        jong = (ord(prev) - 0xAC00) % 28
        return f"{prev} {dep}" if jong in (4, 8) else m.group(0)
    return _GEON.sub(rep, s)


def normalize_ortho(s):
    for rx, rep in ORTHO:
        s = rx.sub(rep, s)
    s = _fix_kke(_fix_geon(s))
    return re.sub(r" {2,}", " ", s)


def unwrap(kr):
    """[PAGE]/[NL]/\\n 을 모두 풀어 한 줄 흐름으로 만든다(어절 경계는 공백으로 복원)."""
    kr = kr.replace("\n", "[NL]").replace("[PAGE]", "[NL]")
    parts = [p.strip() for p in kr.split("[NL]")]
    flow, prev_ctrl_only = "", False
    for p in parts:
        if not p:
            continue
        ctrl_only = not _CTRL_TOK.sub("", p).strip()
        if not flow:
            flow, prev_ctrl_only = p, ctrl_only
            continue
        # 앞줄이 정렬코드만 있는 줄([C:05] 등)이거나 여는 기호로 끝나거나, 뒷줄이 닫는
        # 기호/쉼표로 시작하면 공백 없이 붙인다(정렬코드 뒤 0.5칸이 밀리지 않게).
        # 가시 토큰([NAME]/[WAIT]/[MTE])으로 시작하는 줄은 일반 낱말로 취급해 공백을 둔다.
        head = _CTRL_TOK.sub("", p).lstrip()
        vis_head = "" if head.startswith("[") else head[:1]
        if prev_ctrl_only or flow[-1] in OPENERS or (vis_head and vis_head in NOSPACE_LEAD):
            flow += p
        elif flow[-1] == " ":
            flow += p
        else:
            flow += " " + p
        prev_ctrl_only = ctrl_only
    return re.sub(r" {2,}", " ", flow).strip()


def split_sentences(flow):
    """흐름을 문장 리스트로 나눈다. 마크업 토큰([NAME:xx] 등)은 통째로 보호."""
    out, buf, i, n = [], "", 0, len(flow)

    def flush():
        nonlocal buf
        s = buf.strip()
        if s:
            out.append(s)
        buf = ""

    while i < n:
        m = _ATOM.match(flow, i)
        if m:                                    # 마크업 토큰은 분해하지 않는다
            buf += m.group(0)
            i = m.end()
            continue
        ch = flow[i]
        i += 1
        buf += ch
        if ch in TERMS:
            # 소수점/약어 보호: 앞뒤가 숫자면 문장 끝이 아니다
            if ch == "." and i < n and flow[i].isdigit() and len(buf) >= 2 and buf[-2].isdigit():
                continue
            while i < n and flow[i] in TERMS:    # !!, ?!, ... 연속 흡수
                buf += flow[i]; i += 1
            while i < n and flow[i] in CLOSERS:  # 닫는 따옴표/괄호 흡수
                buf += flow[i]; i += 1
            # 뒤에 공백이 있을 때(=원래 줄이 갈렸거나 띄어쓴 자리)만 문장 끝으로 본다.
            # 공백 없이 글자가 이어지면 인용 뒤 조사("가자!"라고) 같은 경우라 끊지 않는다.
            if i >= n or flow[i] == " ":
                flush()
                while i < n and flow[i] == " ":
                    i += 1
        elif ch == "…":
            while i < n and flow[i] == "…":
                buf += flow[i]; i += 1
            while i < n and flow[i] in CLOSERS:
                buf += flow[i]; i += 1
            if i >= n:
                flush()
            elif flow[i] == " ":
                # 말줄임 앞이 종결어미일 때만 문장 끝으로 본다(아니면 문장 중간의 뜸들임).
                stem = re.sub(r"(?:\[[^\]]*\]|[…\"'」』）)\]”’》〉])+$", "", buf)
                if _FINAL_ENDING.search(stem):
                    flush()
                    while i < n and flow[i] == " ":
                        i += 1
    flush()
    return out


def restyle(kr):
    """kr 한 항목을 세션21 규칙으로 재조판한 문자열을 돌려준다.

    ⚠ 세션22: `[PAGE]`는 **지우지 않고 페이지별로 처리**한다. 원문 `{06}{07}`는 조판이 아니라
    **음성 재생 구간과 동기화**된 경계여서, 페이지를 합치면 음성이 중간에 끊긴다(사용자 실플레이
    보고). 페이지 수는 `repaginate.py`가 원문 이상으로 보장하고, 여기서는 그 경계를 보존한 채
    페이지 안에서만 문장 단위로 다시 나눈다."""
    s = normalize_ortho(normalize_punct(kr))
    return "[PAGE]".join(
        "[NL]".join(split_sentences(unwrap(p))) for p in s.split("[PAGE]"))


# ── 검증 ─────────────────────────────────────────────────────────────────────
def check(kr, space_cells=0.5):
    """재조판 결과를 reinsert와 같은 경로로 조판해 (최대 칸, 최대 페이지 줄수)를 잰다."""
    has_markup = bool(re.search(r"\[(NAME|MTE|NL|PAGE|WAIT|C|RAW):?", kr))
    if has_markup:
        fixed = M.rewrap_markup(kr, width=WIDTH, max_lines=MAX_LINES, space_cells=space_cells,
                                absorb=False, reflow=False, page2_lines=PAGE2_LINES,
                                sentence_pages=True)
        pieces = M.parse_markup(fixed, space=M.HW_SPACE, absorb=False)
    else:
        pieces = kr_render.render_segment(kr, width=WIDTH, window_lines=MAX_LINES,
                                          space=kr_render.HW_SPACE, absorb=False,
                                          page2_lines=PAGE2_LINES, sentence_pages=True)
    return round(M.max_line_width(pieces), 2), M.max_page_lines(pieces)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="워크시트에 실제로 반영(백업 후)")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--report", default=os.path.join(ROOT, "build", "restyle_report.json"))
    ap.add_argument("--samples", type=int, default=12)
    a = ap.parse_args()

    ws = json.load(open(WS_PATH, encoding="utf-8"))
    changed, skipped_frozen, over = [], 0, []
    for idx, e in enumerate(ws):
        ids = [parse_id(i) for i in e["ids"]]
        if not all(ids) or not all(i[2] == DLG_LEAF for i in ids):
            continue                                   # 대사 전용 항목만
        if any((i[0], i[1]) in FROZEN_BLOCKS for i in ids):
            skipped_frozen += 1
            continue                                   # 여신 블록 동결
        old = e.get("kr") or ""
        if not old.strip():
            continue
        new = restyle(old)
        if not new.strip():
            continue
        w, l = check(new)
        if w > WIDTH + 1e-6 or l > max(MAX_LINES, PAGE2_LINES):
            over.append({"i": idx, "id0": e["ids"][0], "kr": new, "w": w, "lines": l})
        if new != old:
            changed.append({"i": idx, "id0": e["ids"][0], "old": old, "new": new})
        if a.apply:
            e["kr"] = new
            e["manual_layout"] = True                  # reflow OFF — 내 문장 줄바꿈 고정
            e["sentence_layout"] = True                # 문장 단위 페이지네이션(세션21 규칙)

    print(f"대상 대사 항목: 재조판 {len(changed)}건 · 여신 블록 동결 제외 {skipped_frozen}건")
    print(f"조판 초과(칸/줄): {len(over)}건")
    for c in changed[:a.samples]:
        print(f"\n--- {c['id0']}")
        print("  before:", c["old"].replace("\n", "\\n"))
        print("  after :", c["new"])

    if a.apply:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = WS_PATH.replace(".json", f".backup_restyle_{ts}.json")
        os.replace(WS_PATH, bak)
        tmp = WS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ws, f, ensure_ascii=False)
        os.replace(tmp, WS_PATH)
        print(f"\n[백업] {os.path.basename(bak)}")
        print(f"[저장] {os.path.basename(WS_PATH)}")
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump({"changed": changed, "over": over}, f, ensure_ascii=False, indent=1)
    print(f"[리포트] {a.report}")


if __name__ == "__main__":
    main()
