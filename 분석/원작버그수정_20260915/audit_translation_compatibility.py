"""Independent re-audit against pre-port backups and donor machine code.
Reads ROMs only; writes this directory's compatibility_audit.json.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
A = Path(__file__).resolve().parent
R = A.parent.parent
sys.path[:0] = [str(R/'한글화/scripts'), str(R/'한글화/tests'), str(R/'개조/scripts/balance')]
from disc_tool import Disc
from disc_files import find
import scen_tool
import bugfixes_l2 as B
from img_re.img_codec import decompress
from test_bugfixes_l2 import Machine
from build_manifest import sha256, input_hashes


def read(d, path):
    info = find(d, path)
    return d.read_file(info['extent'], info['size'])


result = {'projects': {}, 'roms_modified': False}
original_bin = (R/'한글화/original/LANG2.BIN').read_bytes()
for name, folder in [('한글화', 'disc-krpoc'), ('개조', 'disc-mod')]:
    before_path = A/(name+'_before_track1.bin')
    after_path = R/name/'build'/folder/'track1.bin'
    before, after = Disc(before_path), Disc(after_path)
    old_bin, new_bin = read(before, 'LANG2.BIN'), read(after, 'LANG2.BIN')
    preexisting = {i for i, (x, y) in enumerate(zip(original_bin, old_bin)) if x != y}
    bug_region = {i for off, old, _, _ in B.patches() for i in range(off, off+len(old))}
    overlap = preexisting & bug_region
    assert not overlap
    assert B.patch_bin(old_bin) == new_bin
    unchanged_segments = changed_stats = 0
    frozen = []
    for tag in ['LANG1', 'LANG2']:
        for asset in ['FONT.DAT', 'IMG.DAT', 'CLASS.DAT', 'FIGHT.DAT']:
            assert read(before, tag+'/'+asset) == read(after, tag+'/'+asset)
        x, y = read(before, tag+'/SCEN.DAT'), read(after, tag+'/SCEN.DAT')
        tx, ty = scen_tool.parse(x), scen_tool.parse(y)
        assert [(n.start, n.end) for n in tx.children] == [(n.start, n.end) for n in ty.children]
        for stage, (bx, by) in enumerate(zip(tx.children, ty.children)):
            if (tag, stage) in [('LANG1', 20), ('LANG2', 98), ('LANG2', 100)]:
                assert x[bx.start:bx.end] == y[by.start:by.end]
                frozen.append([tag, stage])
        lx, ly = dict(scen_tool.iter_leaves(tx)), dict(scen_tool.iter_leaves(ty))
        assert lx.keys() == ly.keys()
        for path, leaf in lx.items():
            newer = ly[path]
            if len(path) >= 3 and path[1] == 2:
                sx, sy = leaf.raw.split(b'\0'), newer.raw.split(b'\0')
                assert len(sx) == len(sy)
                for i, (p, q) in enumerate(zip(sx, sy)):
                    if p == q:
                        if p: unchanged_segments += 1
                    else:
                        assert path[1:] == (2, 2) and i == 69
                        changed_stats += 1
            elif leaf.raw != newer.raw:
                if not any(leaf.raw) and not any(newer.raw): continue
                assert tag == 'LANG2' and path == (9, 0)
                p, q = decompress(leaf.raw), decompress(newer.raw)
                assert q == p[:0x577]+bytes.fromhex('7609')+p[0x579:]
                assert len(p) == len(q) == 2146
        if tag == 'LANG1': assert read(before, 'LANG1.BIN') == read(after, 'LANG1.BIN')
    assert changed_stats == 118
    result['projects'][name] = {
        'before_sha256': sha256(before_path), 'after_sha256': sha256(after_path),
        'preexisting_bin_changed_bytes': len(preexisting),
        'bugfix_regions_overlap_preexisting_changes': len(overlap),
        'only_expected_bin_edits': True, 'fonts_and_images_unchanged': True,
        'unchanged_nonempty_text_segments': unchanged_segments,
        'separately_requested_item_stats_changes': changed_stats,
        'scenario_top_level_boundaries_unchanged': True, 'voice_event_only_two_bytes_changed': True,
        'frozen_blocks_byte_identical': frozen,
    }
    del before, after

# Look for other direct callers or literal readers that would still expect the old handlers.
references = {}
for target in (0x060278C4, 0x060278EC):
    pattern = struct.pack('>I', target)
    absolute = [i for i in range(len(original_bin)-3) if original_bin[i:i+4] == pattern]
    relative = []
    for off in range(B.START-4200, B.END+4200, 2):
        w = int.from_bytes(original_bin[off:off+2], 'big')
        if w >> 12 in (10, 11):
            disp = Machine.signed(w & 4095, 12)
            if 0x06010000+off+4+disp*2 == target: relative.append(off)
    expected = 0x63830 if target == 0x060278C4 else 0x63834
    assert absolute == [expected] and not relative
    references[hex(target)] = {'absolute': absolute, 'relative': relative}
external_literals = []
for off in range(B.START-1024, B.END+4, 2):
    if B.START <= off < B.END: continue
    w = int.from_bytes(original_bin[off:off+2], 'big')
    target = None
    if w >> 12 == 13: target = ((off+4)&~3)+(w&255)*4
    elif w >> 12 == 9: target = off+4+(w&255)*2
    if target is not None and B.START <= target < B.END: external_literals.append([off, target])
assert not external_literals
result['direct_handler_references'] = references
result['external_pc_literal_reads_into_replaced_region'] = external_literals
result['caller_review'] = '0x18114 calls handler; 0x18118 onward reloads r1/r2, uses preserved r8; no dependence on MACL or final r0-r3.'

# Compare the actual installed instructions against the supplied donor's instructions.
d = Disc(R/'한글화/build/disc-krpoc/track1.bin')
installed = read(d, 'LANG2.BIN')
donor = (R/'분석/타인패치/extracted/LANG2.BIN').read_bytes()
rng = random.Random(20260915)
for case in range(1200):
    character, field, value, old = rng.randrange(20), rng.randrange(256), rng.randrange(256), rng.randrange(256)
    for kind in ['add', 'assign']:
        machines = [Machine(installed), Machine(donor)]
        for vm in machines:
            vm.write(0x0609FEB0, 0x06120000, 4)
            vm.write(0x0609CD94, 0x06121000, 4)
            vm.write(0x06121047, character, 1)
            vm.write(0x06120000, field, 1)
            vm.write(0x06120001, value, 1)
            for i in range(20*40+256): vm.write(0x0609C9C8+i, old, 1)
        machines[0].run(0x178C4 if kind == 'add' else 0x178F6)
        machines[1].run(0x178C4 if kind == 'add' else 0x62430)
        assert machines[0].mem == machines[1].mem, (kind, case)
        assert machines[0].reg[4:] == machines[1].reg[4:]
result['donor_vs_installed_machine_code'] = {'input_sets': 1200, 'handlers': 2, 'comparisons_passed': 2400}
manifest = json.loads((R/'한글화/build/translation-manifest.json').read_text(encoding='utf-8'))
assert manifest['inputs'] == input_hashes(R/'한글화')
assert manifest['tracks']['track1.bin'] == result['projects']['한글화']['after_sha256']
result['translation_manifest_current'] = True
result['limitations'] = ['No gameplay or real emulator execution was performed.',
    'Direct references were inspected; computed or undocumented entry paths cannot be fully ruled out by static scans.']
(A/'compatibility_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
