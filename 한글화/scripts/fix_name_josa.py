#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_name_josa.py — [NAME:XX] 뒤 조사를 실제 이름의 받침에 맞게 교정한다.

⚠ DEPRECATED — off-by-one 매핑으로 폐기. fix_josa_all.py를 쓸 것.
{09 XX}(마크업 [NAME:XX])는 이름 리프 (block,2,1) 세그먼트 **#(XX+1)** 을 삽입한다
(BIN {09} 핸들러 @0x0601bfd0 역공학 + 콜드부트 확증: Ep1 {09:06}→#7 호킹, {09:01}→#2
나암; 플레이어명 레딘/엘윈은 {09}가 아니라 동적 {02}/[WAIT]). 이 파일의 #XX 직접
매핑은 틀렸다.
개명 기능이 없으므로 각 XX의 한국어 이름 받침이 고정 → 텍스트의 조사를 정적으로 교정한다.

dedup 엔트리의 ids가 여러 블록에 걸치고 블록별 이름의 받침이 갈리면 엔트리를
받침 그룹별로 분할한다(ids 부분집합 + kr 변형).
"""
import os
import io, sys, json, re, copy
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "worksheet_dedup_final.json")

# 받침 있음(True) → 교정, 받침 없음(False) → 교정. 긴 조사 우선.
J_TO_BATCHIM = [("가", "이"), ("는", "은"), ("를", "을"), ("와", "과"),
                ("야", "아"), ("란", "이란"), ("나", "이나"), ("라고", "이라고")]
J_TO_OPEN = [("이라고", "라고"), ("이란", "란"), ("이나", "나"), ("으로", "로"),
             ("이", "가"), ("은", "는"), ("을", "를"), ("과", "와"), ("아", "야")]


def batchim(name):
    for ch in reversed(name):
        if 0xAC00 <= ord(ch) <= 0xD7A3:
            return (ord(ch) - 0xAC00) % 28
    return None                     # 한글 없음 → 판정 불가


def fix_josa(kr, resolve):
    """resolve(xx) -> name or None. [NAME:xx] 직후 조사를 교정한 kr을 반환."""
    out = []
    pos = 0
    for m in re.finditer(r"\[NAME:([0-9a-fA-F]{2})\]", kr):
        out.append(kr[pos:m.end()])
        pos = m.end()
        name = resolve(m.group(1).lower())
        b = batchim(name) if name else None
        if b is None:
            continue
        rest = kr[pos:]
        table = J_TO_BATCHIM if b else J_TO_OPEN
        for wrong, right in sorted(table, key=lambda x: -len(x[0])):
            if rest.startswith(wrong):
                # '로'는 ㄹ받침(8)이면 그대로 둔다
                if wrong == "로" or (b == 8 and right == "으로"):
                    break
                # 뒤가 한글 이어지면 어절 일부일 수 있음 — 조사+비한글/공백/끝만 교정
                nxt = rest[len(wrong):len(wrong) + 1]
                if wrong in ("가", "는", "를", "와", "야", "이", "은", "을", "과", "아") \
                        and nxt and 0xAC00 <= ord(nxt) <= 0xD7A3:
                    # 대부분 조사 뒤엔 공백/구두점. 한글이 이어지면 스킵(보수적).
                    break
                out.append(right)
                pos += len(wrong)
                break
    out.append(kr[pos:])
    return "".join(out)


def main():
    ws = json.load(open(WS, encoding="utf-8"))
    names = {}                       # (tag, block, xx) -> kr name
    for e in ws:
        for i in e["ids"]:
            m = re.match(r"(L[12]):(\d+)/2/1#(\d+)$", i)
            if m and e.get("kr", "").strip():
                names[(m.group(1), int(m.group(2)), int(m.group(3)))] = e["kr"].strip()

    changed = split = 0
    new_entries = []
    for e in ws:
        kr = e.get("kr", "")
        if "[NAME:" not in kr or not kr.strip():
            continue
        # 그룹: id별 kr 교정 결과
        groups = {}                  # fixed_kr -> [ids]
        for i in e["ids"]:
            m = re.match(r"(L[12]):(\d+)/", i)
            tag, blk = m.group(1), int(m.group(2))
            fixed = fix_josa(kr, lambda xx: names.get((tag, blk, int(xx, 16))))
            groups.setdefault(fixed, []).append(i)
        if len(groups) == 1:
            fixed = next(iter(groups))
            if fixed != kr:
                print("---", e["ids"][0])
                print(" 전:", kr.replace("\n", "|")[:90])
                print(" 후:", fixed.replace("\n", "|")[:90])
                e["kr"] = fixed
                changed += 1
        else:
            # 블록별 받침이 갈림 → 분할
            items = sorted(groups.items(), key=lambda x: -len(x[1]))
            print("=== 분할", e["ids"][0], f"({len(items)}그룹)")
            (fixed0, ids0) = items[0]
            e["kr"], e["ids"] = fixed0, ids0
            print("  주:", fixed0.replace("\n", "|")[:80], len(ids0), "ids")
            for fixed_k, ids_k in items[1:]:
                clone = copy.deepcopy(e)
                clone["kr"], clone["ids"] = fixed_k, ids_k
                new_entries.append(clone)
                print("  부:", fixed_k.replace("\n", "|")[:80], len(ids_k), "ids")
            split += 1
            changed += 1
    ws.extend(new_entries)
    print(f"\n교정 {changed}건 (분할 {split}건, 신규 엔트리 {len(new_entries)}개)")
    json.dump(ws, open(WS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
