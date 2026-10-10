"""Prove each release changed only the two labels and their sector checksums."""
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / '개조/scripts/balance'))
from disc_files import Disc, find

report = {}
for variant, relative in [('한글판', '한글화/build/disc-krpoc/track1.bin'),
                          ('개조판', '개조/build/disc-mod/track1.bin')]:
    old = Disc(str(HERE / 'backup' / relative))
    new = Disc(str(ROOT / relative))
    expected = Disc(str(HERE / 'backup' / relative))
    changed = [i for i in range(old.nsec) if old.data[i*2352:(i+1)*2352] != new.data[i*2352:(i+1)*2352]]
    assert changed == [286, 492], (variant, changed)
    bins = {}
    for name, offset in [('LANG1.BIN', 0x2a7ac), ('LANG2.BIN', 0x2c4e8)]:
        info = find(old, name)
        before = old.read_file(info['extent'], info['size'])
        after = bytearray(before)
        assert before[offset:offset+6] == bytes.fromhex('3c3d062f3f70')
        after[offset:offset+6] = bytes.fromhex('3c3d41427070')
        assert new.read_file(info['extent'], info['size']) == after
        expected.write_file(info['extent'], after, regen=True)
        bins[name] = {'offset': offset, 'old_label': '전투시ーン', 'new_label': '전투표시',
                      'changed_bytes': sum(x != y for x, y in zip(before, after))}
    assert expected.data == new.data, 'Unexpected data or invalid regenerated EDC/ECC'
    report[variant] = {'old_track1_sha256': hashlib.sha256(old.data).hexdigest(),
                       'new_track1_sha256': hashlib.sha256(new.data).hexdigest(),
                       'changed_sectors': changed, 'bins': bins,
                       'full_disc_matches_only_label_changes_and_regenerated_checksums': True}
    print(variant, report[variant]['new_track1_sha256'])
(HERE / 'menu_delta_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('두 판 모두 설정 문구 외 전체 디스크 보존 검사 통과')
