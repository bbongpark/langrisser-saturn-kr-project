"""Independently reconstruct the requested two BIN writes on the Korean base."""
import hashlib
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '개조/scripts/balance'))
from disc_files import Disc, find
sys.path.insert(0, str(ROOT / '한글화/scripts'))
import bugfixes_l2

base_path = ROOT / '한글화/build/disc-krpoc/track1.bin'
mod_path = ROOT / '개조/build/disc-mod/track1.bin'
expected = Disc(str(base_path))
mod = Disc(str(mod_path))
report = {}
for name, effect, price, shop, sites in [
    ('LANG1.BIN', 0x60a68, 0x644aa, 0x64354, [0xf6bd, 0xf787, 0xfee7]),
    ('LANG2.BIN', 397276, 413750, 413004, [70505, 70707, 72599]),
]:
    info = find(expected, name)
    original = expected.read_file(info['extent'], info['size'])
    result = bytearray(original)
    writes = [
        (effect + 32*16 + 12, 'ffffffff', '00080014'),
        (price + 32*2, '01f4', '0001'),
        (price + 34*2, '05dc', '0001'),
        (shop, '01150000', '01212300'),
    ]
    for s in sites:
        before = original[s-1:s+7]
        assert before in (bytes.fromhex('71486110601c880b'), bytes.fromhex('72486120601c880b'))
        after = bytearray(before)
        after[1], after[7] = 0x49, 0x21
        writes.append((s-1, before.hex(), after.hex()))
    occupied = set()
    for offset, before_hex, after_hex in writes:
        before, after = bytes.fromhex(before_hex), bytes.fromhex(after_hex)
        assert original[offset:offset+len(before)] == before, (name, hex(offset))
        positions = set(range(offset, offset + len(before)))
        assert not occupied & positions
        occupied |= positions
        result[offset:offset+len(after)] = after
    actual = mod.read_file(info['extent'], info['size'])
    assert actual == result, name
    expected.write_file(info['extent'], result, regen=True)
    report[name] = {'changed_bytes': sum(a != b for a, b in zip(original, actual)),
                    'writes': [{'offset': off, 'before': old, 'after': new} for off, old, new in writes]}
    if name == 'LANG2.BIN':
        bugfixes_l2.verify_bin(actual)
        assert actual[bugfixes_l2.START:bugfixes_l2.END] == original[bugfixes_l2.START:bugfixes_l2.END]

assert expected.data == mod.data, 'Unexpected final track difference'
base = Disc(str(base_path))
changed = [i for i in range(base.nsec) if base.data[i*2352:(i+1)*2352] != mod.data[i*2352:(i+1)*2352]]
report['changed_sectors'] = changed
report['translation_track_sha256'] = hashlib.sha256(base.data).hexdigest()
report['mod_track_sha256'] = hashlib.sha256(mod.data).hexdigest()
report['full_track_matches_independent_write_plan'] = True
report['mercenary_classes_hooks_and_all_other_files_match_translation'] = True
report['runtime_screen_check'] = 'not run for this changed profile'
Path(__file__).with_name('final_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print('Full disc matches the requested crown/rune profile. All mercenary and text changes reverted/preserved as intended.')
print('Changed bytes per BIN:', {k:v['changed_bytes'] for k,v in report.items() if k.endswith('.BIN')})
print('SHA-256:', report['mod_track_sha256'])
