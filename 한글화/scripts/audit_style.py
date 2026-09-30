#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_style.py — 맞춤법·표준어에 어긋난 표기를 전수 검색한다.

  python scripts/audit_style.py            # 규칙별 건수 + 사례
  python scripts/audit_style.py --apply    # `safe=True` 규칙만 일괄 치환(백업 자동)
  python scripts/audit_style.py -r 구만    # 규칙 하나만 자세히

★ `safe=True` 는 **문맥과 무관하게 항상 틀린 표기**만 붙인다. 한 글자라도 문맥에 따라
  옳을 수 있으면 safe=False 로 두고 사람이 판단한다(목록만 보여준다).
⚠ 폭이 바뀌는 치환은 조판을 흔들 수 있다 — `--apply` 뒤에는 반드시
  `rebuild.py` + `verify_disc_layout.py` 를 돌려라.
"""
import argparse
import collections
import json
import os
import re
import shutil
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

WS_PATH = os.path.join(ROOT, "build", "worksheet_dedup_final.json")

# (이름, 찾을 정규식, 바꿀 문자열, safe, 설명)
RULES = [
    ("구만", r"구만(?=[!.?…\"'\s]|$)", "구먼", True,
     "종결어미 '-구만'은 비표준. 표준어는 '-구먼'"),
    ("로군요", r"로군요", "로군요", False, "(참고용)"),
    ("몇일", r"몇\s?일", "며칠", True, "'몇일'은 없는 말. 표준은 '며칠'"),
    ("왠만", r"왠만", "웬만", True, "'왠만'→'웬만'"),
    ("웬지", r"웬지", "왠지", True, "'웬지'→'왠지'(왜인지)"),
    ("금새", r"금새", "금세", True, "'금새'→'금세'(금시에)"),
    ("역활", r"역활", "역할", True, "'역활'→'역할'"),
    ("어의없", r"어의없", "어이없", True, "'어의없다'→'어이없다'"),
    ("설레임", r"설레임", "설렘", True, "'설레임'→'설렘'"),
    ("바램", r"바램(?=[을이는과])", "바람", False, "소망의 뜻이면 '바람'"),
    ("~로써", r"로써", "로써", False, "수단이면 '로써', 자격이면 '로서'"),
    # ⚠ '-슴다'는 L2:92 개그 캐릭터의 의도된 말투다 — 고치지 말 것(safe=False).
    ("슴다", r"슴다", "습니다", False, "'-슴다'(의도된 말투인지 확인)"),
    ("띄다", r"눈에 띄", "눈에 띄", False, "(참고용)"),
    ("이예요", r"이예요", "이에요", True, "'이예요'→'이에요'"),
    ("않되", r"않되", "안 되", True, "'않되'→'안 되'"),
    # ⛔ 한자 슬롯은 한글 글리프로 덮어썼다 — 본문에 한자가 남으면 **엉뚱한 한글로 그려진다**.
    ("한자", r"[一-龥]", "", False, "한자 잔존 — 렌더 깨짐 위험(반드시 확인)"),
    ("일본어", r"[ぁ-んァ-ヶ]", "", False, "일본어 가나 잔존"),
    ("전각영문", r"[Ａ-Ｚａ-ｚ]{3,}", "", False, "전각 영문 연속(폭 낭비 가능)"),
    ("이중공백", r"  +", " ", True, "공백 두 칸 이상"),
    ("공백앞부호", r"\s+[,.!?]", "", False, "부호 앞 공백"),
]


def load():
    with open(WS_PATH, encoding="utf-8") as f:
        return json.load(f)


def strip_tok(s):
    """⛔ 토큰을 **지우면 안 된다** — `[NAME:xx] 님이` 가 '  님이'(공백 두 칸)로 보여
    '이중공백'·'부호 앞 공백' 규칙이 전부 오탐이 난다(세션24 실제 오탐 838건).
    자리를 차지하는 한 글자(◆)로 바꿔서 주변 공백 구조를 보존한다."""
    return re.sub(r"\[[^\]]*\]", "◆", s or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="safe 규칙 일괄 치환")
    ap.add_argument("-r", "--rule", help="규칙 하나만")
    ap.add_argument("-n", type=int, default=6, help="사례 표시 개수")
    a = ap.parse_args()

    ws = load()
    changed = 0
    for name, pat, rep, safe, desc in RULES:
        if a.rule and name != a.rule:
            continue
        rx = re.compile(pat)
        hits = []
        for e in ws:
            kr = e.get("kr") or ""
            if not kr:
                continue
            if rx.search(strip_tok(kr)):
                hits.append(e)
        if not hits:
            continue
        print("── %s  %d건  %s%s" % (name, len(hits), desc, "  [safe]" if safe else ""))
        for e in hits[:a.n]:
            print("     %s  %s" % (e["ids"][0], strip_tok(e["kr"])[:64]))
        if len(hits) > a.n:
            print("     … 외 %d건" % (len(hits) - a.n))
        if a.apply and safe:
            for e in hits:
                new = rx.sub(rep, e["kr"])
                if new != e["kr"]:
                    e["kr"] = new
                    changed += 1
        print()

    if a.apply and changed:
        shutil.copy2(WS_PATH, WS_PATH.replace(".json", ".backup_style.json"))
        with open(WS_PATH + ".tmp", "w", encoding="utf-8") as f:
            json.dump(ws, f, ensure_ascii=False)
        os.replace(WS_PATH + ".tmp", WS_PATH)
        print("✅ %d엔트리 치환. 백업: %s"
              % (changed, os.path.basename(WS_PATH.replace(".json", ".backup_style.json"))))
        print("⚠ 이어서 rebuild.py + verify_disc_layout.py 를 반드시 돌려라.")


if __name__ == "__main__":
    main()
