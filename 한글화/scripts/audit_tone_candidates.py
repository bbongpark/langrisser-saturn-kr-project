#!/usr/bin/env python3
"""Create a compact, contextual queue for Korean character-tone review.

This is deliberately read-only. It combines existing diagnostics, catches
archaic endings unsupported by the Japanese voice, and attaches neighboring
lines so a reviewer does not judge isolated sentences.
"""
import argparse
import collections
import json
import os
import re
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import audit_dialogue as AD
import audit_register as AR
import dump_scenario_kr as D

OUT_DIR = os.path.join(ROOT, 'build', 'tone_audit')
OUT_JSON = os.path.join(OUT_DIR, 'candidates.json')
OUT_MD = os.path.join(OUT_DIR, 'summary.md')
ACCEPTED_JSON = os.path.join(OUT_DIR, 'accepted.json')
FROZEN = {('L1', 20), ('L2', 98)}

BROKEN = [
    (re.compile(r'(?:구먼|일세|다네|하게|하오)(?:요|습니다)'), 'broken_ending', 100),
    (re.compile(r'게지(?=[.!?…\[]|$)'), 'geji', 40),
    (re.compile(r'(?:것이|거에) 다름(?:이 )?아니'), 'literal_phrase', 12),
    (re.compile(r'하지 않으면 안 (?:된다|돼)'), 'literal_phrase', 10),
    (re.compile(r'(?:해|하여) 주었으면 (?:한다|좋겠다)'), 'literal_phrase', 10),
]
ARCHAIC_KR = re.compile(r'(?:구먼|일세|다네|라네|하시게|하오|하겠네|하게나)(?=[.!?…\[]|$)')
OLD_JP = re.compile(r'(?:わし|ワシ|おぬし|そなた|じゃ|ぢゃ|の[うぅ]|わい|ぞい|儂)')
ROUGH_JP = re.compile(r'(?:俺|オレ|お前|オマエ|貴様|てめえ|てめぇ|だぜ|ねぇ|ねえ|やがれ)')
POLITE_KR = re.compile(r'(?:습니다|습니까|십시오|세요|셔요|군요|네요|예요|에요)(?=[.!?…\[]|$)')


def locations(entry, tag_filter=None):
    out = []
    for raw in entry.get('ids', []):
        parsed = AD.parse_id(raw)
        if not parsed:
            continue
        tag, block, leaf, seg = parsed
        if leaf != AD.DLG_LEAF or (tag, block) in FROZEN:
            continue
        if tag_filter and tag != tag_filter:
            continue
        out.append((tag, block, seg, raw))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', choices=['L1', 'L2'], default='L2')
    args = ap.parse_args()
    ws = D.load()
    accepted = {}
    if os.path.exists(ACCEPTED_JSON):
        with open(ACCEPTED_JSON, encoding='utf-8') as f:
            accepted = json.load(f)
    by_loc = {}
    for idx, entry in enumerate(ws):
        for tag, block, seg, _ in locations(entry, args.tag):
            by_loc[(tag, block, seg)] = (idx, entry)

    candidates = {}
    for idx, entry in enumerate(ws):
        locs = locations(entry, args.tag)
        if not locs or not (entry.get('kr') or '').strip():
            continue
        reasons = []
        kr, jp = entry.get('kr', ''), entry.get('jp', '')
        visible = AD.visible(kr)
        for rx, kind, score in BROKEN:
            if rx.search(visible):
                reasons.append({'kind': kind, 'score': score, 'detail': rx.pattern})
        if AR.jp_register(jp) and AR.kr_register(kr) and AR.jp_register(jp) != AR.kr_register(kr):
            reasons.append({'kind': 'register_mismatch', 'score': 9,
                            'detail': f"JP {AR.jp_register(jp)} / KR {AR.kr_register(kr)}"})
        for kind, detail in AD.audit(entry):
            score = {'mixed_speech': 11, 'jp_calque': 8, 'punct': 8,
                     'glued': 8, 'unsplit': 3, 'spacing': 1}.get(kind, 2)
            reasons.append({'kind': kind, 'score': score, 'detail': detail})
        if ARCHAIC_KR.search(visible) and not OLD_JP.search(jp):
            reasons.append({'kind': 'unsupported_archaism', 'score': 12,
                            'detail': '한국어 고풍스러운 어미, 일본어 노인 말투 표지 없음'})
        if ROUGH_JP.search(jp) and POLITE_KR.search(visible):
            reasons.append({'kind': 'rough_to_polite', 'score': 8,
                            'detail': '일본어 거친 말투와 한국어 존댓말이 함께 발견됨'})
        if not reasons:
            continue
        accepted_row = accepted.get(entry['ids'][0])
        # 번역문이 그대로일 때만 예외로 인정한다. 나중에 문장이 바뀌면 다시 검사된다.
        if accepted_row and accepted_row.get('kr') == kr:
            continue
        # Deduplicate same detector result while keeping the strongest score.
        merged = {}
        for reason in reasons:
            key = (reason['kind'], reason['detail'])
            merged[key] = max(merged.get(key, 0), reason['score'])
        reasons = [{'kind': k[0], 'detail': k[1], 'score': score}
                   for k, score in merged.items()]
        contexts = []
        for tag, block, seg, raw in locs[:8]:
            around = []
            for n in range(max(0, seg-2), seg+3):
                hit = by_loc.get((tag, block, n))
                if hit:
                    ni, ne = hit
                    around.append({'segment': n, 'worksheet_index': ni,
                                   'jp': ne.get('jp', ''), 'kr': ne.get('kr', ''),
                                   'target': n == seg})
            contexts.append({'id': raw, 'tag': tag, 'block': block,
                             'segment': seg, 'around': around})
        candidates[entry['ids'][0]] = {
            'worksheet_index': idx, 'ids': entry['ids'], 'jp': jp, 'kr': kr,
            'score': sum(r['score'] for r in reasons),
            'reasons': sorted(reasons, key=lambda x: (-x['score'], x['kind'])),
            'contexts': contexts,
        }

    ordered = dict(sorted(candidates.items(), key=lambda kv: (-kv[1]['score'], kv[1]['worksheet_index'])))
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)
    counts = collections.Counter(r['kind'] for c in ordered.values() for r in c['reasons'])
    bands = collections.Counter('urgent' if c['score'] >= 30 else 'high' if c['score'] >= 12
                                else 'medium' if c['score'] >= 8 else 'low'
                                for c in ordered.values())
    lines = [f'# {args.tag} 말투 재검수 후보', '',
             f'- 대사 위치: {len(by_loc):,}개', f'- 고유 후보: {len(ordered):,}개',
             f'- 사람이 확인한 정상 예외: {sum(1 for v in accepted.values() if v.get("kr")):,}개',
             f'- 우선순위: {dict(bands)}', '', '## 검출 종류', '']
    lines += [f'- `{k}`: {v}개' for k, v in counts.most_common()]
    lines += ['', '## 긴급·높음 후보', '']
    for id0, c in ordered.items():
        if c['score'] < 12:
            break
        why = ', '.join(r['kind'] for r in c['reasons'])
        lines += [f'### {id0} · 점수 {c["score"]} · {why}', '',
                  f'- JP: {c["jp"]}', f'- KR: {c["kr"]}', '']
    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'{args.tag} 대사 위치 {len(by_loc):,}개 → 고유 후보 {len(ordered):,}개')
    print('우선순위:', dict(bands))
    print('검출 종류:', dict(counts))
    print('저장:', OUT_JSON)


if __name__ == '__main__':
    main()
