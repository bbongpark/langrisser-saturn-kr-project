"""Record the exact translation inputs and finished disc; no ROM writes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_JSON = ('worksheet_dedup_final.json', 'classnames.json', 'steam_charnames.json', 'steam_glossary.json')

def sha256(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def input_hashes(root=ROOT):
    root = Path(root)
    paths = set()
    for directory, suffixes in [('scripts', {'.py', '.json'}), ('fonts', {'.ttf'}), ('original', {'.DAT', '.BIN'})]:
        paths.update(p for p in (root / directory).rglob('*') if p.is_file() and p.suffix in suffixes)
    paths.update(root / 'build' / name for name in INPUT_JSON)
    paths.add(root / 'requirements.txt')
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(paths)}

def publish():
    import platform
    import PIL
    import numpy
    disc = ROOT / 'build/disc-krpoc'
    manifest = {
        'kind': 'translation-only', 'inputs': input_hashes(),
        'base_bugfixes': __import__('bugfixes_l2').FIX_IDS,
        'runtime': {'python': platform.python_version(), 'Pillow': PIL.__version__, 'numpy': numpy.__version__},
        'tracks': {f'track{i}.bin': sha256(disc / f'track{i}.bin') for i in range(1, 7)},
        'cue_sha256': sha256(disc / 'langrisser-krpoc.cue'),
    }
    path = ROOT / 'build/translation-manifest.json'
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    print('한글화 빌드 기록 저장:', path)

if __name__ == '__main__':
    publish()
