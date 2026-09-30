"""Check the final disc after all Korean font/HUD patches have run."""
import hashlib
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
import bugfixes_l2 as B
import disc_tool
import scen_tool
import reinsert_text as R
from img_re.img_codec import decompress


def main():
    root = Path(__file__).resolve().parents[1]
    disc = disc_tool.Disc(root / 'build/disc-krpoc/track1.bin')
    cfg = R.FILES['L2']
    size = (root / 'original/LANG2.BIN').stat().st_size
    B.verify_bin(disc.read_file(cfg['bin_lba'], size))
    tree = scen_tool.parse(disc.read_file(cfg['scen_lba'], cfg['alloc']))
    event = decompress(tree.children[9].children[0].raw)
    if hashlib.sha256(event).hexdigest() != '0b82a08a1caa5873a52fcf4d35fc79e671fae5bce34f1368acc151f3ac347999':
        raise ValueError('레온 음성 수정 또는 다른 장면 명령이 예상과 다릅니다.')
    count = 0
    for tag, cfg in R.FILES.items():
        tree = scen_tool.parse(disc.read_file(cfg['scen_lba'], cfg['alloc']))
        for i, block in enumerate(tree.children):
            if (tag, i) in R.LEGACY_GEOM_BLOCKS: continue
            try:
                segments = block.children[2].children[2].raw.split(b'\0')
            except (TypeError, IndexError, AttributeError): continue
            if len(segments) <= 69: continue
            stats = segments[69]
            # These item-name/description tables have 142 or more strings.
            if len(segments) < 142: continue
            if b'\x08' in stats or not all(c.encode('shift_jis') in stats for c in '４３２'):
                raise ValueError(f'{tag}:{i} 메사이얀소드 수치가 한 줄에 없습니다.')
            count += 1
    if count != 118:
        raise ValueError(f'아이템 설명 검사 수 불일치: {count} != 118')
    print(f'원작 버그 4건 + 메사이얀소드 수치 {count}곳 최종 디스크 확인 완료')


if __name__ == '__main__': main()
