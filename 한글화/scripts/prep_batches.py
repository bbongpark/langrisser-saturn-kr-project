#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prep_batches.py — split the still-untranslated worksheet entries into batch files
for parallel translation subagents, converting the extractor's {xx} control codes into
kr_markup tokens and attaching a Steam-remake tone reference (fuzzy JP match -> KR) so
each subagent can match character/situation speech style.

Outputs:
  build/batches/batch_<name>.json   (list of {key, jp, jp_markup, block, tone_ref, kr})
  build/batches/glossary.json       (JP term -> KR, from steam_glossary)
Each subagent fills `kr` per entry (Korean using the SAME [..] tokens) and saves the file.
"""
import sys, io, os, json, re, difflib
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")
BATCH = os.path.join(BUILD, "batches")
os.makedirs(BATCH, exist_ok=True)

CTRL = re.compile(r'\{[0-9a-f]{2}(?::[0-9a-f]{2})?\}')

def to_markup(jp):
    s = jp.replace('{06}{07}', '[PAGE]').replace('{08}', '[NL]')
    s = re.sub(r'\{09:([0-9a-f]{2})\}', r'[NAME:\1]', s)
    s = re.sub(r'\{04:([0-9a-f]{2})\}', r'[MTE:\1]', s)
    s = s.replace('{02}', '[WAIT]')
    s = re.sub(r'\{([0-9a-f]{2})\}', r'[C:\1]', s)      # {05},{03},... -> [C:xx]
    s = re.sub(r'<([0-9a-f]{2})>', r'[RAW:\1]', s)      # stray raw bytes
    return s

def norm(s):
    s = CTRL.sub('', s)
    for ch in '　 \n「」『』（）()':
        s = s.replace(ch, '')
    return s.strip()

def leaf(e):
    p = e['ids'][0].split(':')[1].split('#')[0].split('/')
    return p[2] if len(p) > 2 else 'D' + p[1]

def block(e):
    return int(e['ids'][0].split(':')[1].split('/')[0])

def main():
    final = json.load(open(os.path.join(BUILD, "worksheet_dedup_final.json"), encoding="utf-8"))
    un = [e for e in final if not e.get('kr', '').strip()]
    # steam tone index: normalized JP -> KR (first close match wins)
    dlg = json.load(open(os.path.join(BUILD, "steam_dialogue.json"), encoding="utf-8"))
    steam = {}
    for jp_key, kr_val in dlg.items():
        jpn = norm(jp_key)
        if jpn and jpn not in steam:
            steam[jpn] = kr_val
    # bucket steam keys by first 2 chars for fast fuzzy lookup
    buckets = {}
    for k in steam:
        buckets.setdefault(k[:2], []).append(k)

    def tone_ref(jp):
        q = norm(jp)
        if not q or len(q) < 3:
            return ''
        cand = buckets.get(q[:2], [])
        m = difflib.get_close_matches(q, cand, n=1, cutoff=0.55)
        return steam[m[0]] if m else ''

    def rec(e, with_tone):
        return {
            "key": e['ids'][0], "n_ids": len(e['ids']), "bytes": e['bytes'],
            "block": block(e), "jp": e['jp'], "jp_markup": to_markup(e['jp']),
            "tone_ref": tone_ref(e['jp']) if with_tone else "", "kr": "",
        }

    # classify
    def tag(e): return e['ids'][0].split(':')[0]
    L1 = [e for e in un if tag(e) == 'L1']
    L2 = [e for e in un if tag(e) == 'L2']
    l1_narr = [e for e in L1 if leaf(e) == '7']
    l1_rest = [e for e in L1 if leaf(e) != '7' and not leaf(e).startswith('D')]
    l2_narr = [e for e in L2 if leaf(e) == '7']
    l2_dlg = [e for e in L2 if leaf(e) == '5']
    l2_cond = [e for e in L2 if leaf(e) == '6']
    held = [e for e in un if leaf(e).startswith('D')]   # L2 D2 fragments -> hold

    batches = {}
    batches['L1_all'] = [rec(e, True) for e in l1_rest]
    batches['narration'] = [rec(e, True) for e in (l1_narr + l2_narr)]
    batches['L2_cond'] = [rec(e, True) for e in l2_cond]
    # split L2 dialogue into ~450-sized batches
    CHUNK = 450
    for i in range(0, len(l2_dlg), CHUNK):
        batches[f'L2_dlg_{i//CHUNK+1}'] = [rec(e, True) for e in l2_dlg[i:i+CHUNK]]

    for name, recs in batches.items():
        json.dump(recs, open(os.path.join(BATCH, f"batch_{name}.json"), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        withref = sum(1 for r in recs if r['tone_ref'])
        print(f"batch_{name}.json: {len(recs)} entries ({withref} with tone_ref)")
    # glossary
    glo = json.load(open(os.path.join(BUILD, "steam_glossary.json"), encoding="utf-8"))
    json.dump(glo, open(os.path.join(BATCH, "glossary.json"), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"glossary.json: {len(glo)} terms")
    print(f"HELD (L2 D2 fragments, not batched): {len(held)}")
    print(f"TOTAL batched: {sum(len(v) for v in batches.values())}")

if __name__ == "__main__":
    main()
