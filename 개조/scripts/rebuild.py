"""Build modifications on a verified translation copy, never writing upstream."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'balance'))
from project_paths import MOD_ROOT, TRANSLATION_ROOT, TRANSLATION_SCRIPTS
sys.path.insert(0, TRANSLATION_SCRIPTS)
from build_manifest import input_hashes, sha256
from disc_tool import Disc
import disc_files
import registry
import scen_tool
import stage_dat

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def apply_delta(target, original, desired, start, label):
    """Only patch changed bytes; reject collisions with newer translations."""
    if len(original) != len(desired) or start < 0 or start + len(desired) > len(target):
        raise ValueError(f'{label}: 크기 또는 위치 불일치')
    changes = [(start+i, old, new) for i, (old, new) in enumerate(zip(original, desired)) if old != new]
    for pos, old, new in changes:
        if target[pos] != old:
            raise ValueError(f'{label}: 한글화와 충돌 @0x{pos:X}, 예상 {old:02x}, 현재 {target[pos]:02x}')
    for pos, _, new in changes:
        target[pos] = new
    return len(changes)

def main():
    manifest_path = TRANSLATION_ROOT / 'build/translation-manifest.json'
    if not manifest_path.exists():
        raise ValueError('먼저 한글화 폴더의 한글화_빌드.bat를 실행하세요.')
    manifest = load(manifest_path)
    if manifest.get('kind') != 'translation-only' or manifest['inputs'] != input_hashes(TRANSLATION_ROOT):
        raise ValueError('한글화 입력이 바뀌었습니다. 한글화_빌드.bat 실행 후 다시 시도하세요.')
    base_dir = TRANSLATION_ROOT / 'build/disc-krpoc'
    base_hashes = {f'track{i}.bin': sha256(base_dir / f'track{i}.bin') for i in range(1,7)}
    if base_hashes != manifest['tracks'] or sha256(base_dir/'langrisser-krpoc.cue') != manifest['cue_sha256']:
        raise ValueError('한글화 결과물이 빌드 기록과 다릅니다. 한글화를 다시 빌드하세요.')
    data_hashes = {p.relative_to(MOD_ROOT).as_posix(): sha256(p) for p in sorted((MOD_ROOT/'data').rglob('*.json'))}
    original_dir = Path(os.environ.get('LANGRISSER_DISC', str(TRANSLATION_ROOT.parent / 'Langrisser - Dramatic Edition (Japan) (1M)')))
    original = Disc(str(original_dir/'Langrisser - Dramatic Edition (Japan) (1M) (Track 1).bin'))
    disc = Disc(str(base_dir/'track1.bin'))
    if hashlib.sha256(disc.data).hexdigest() != base_hashes['track1.bin']:
        raise ValueError('읽는 중 한글화 파일이 바뀌었습니다.')
    files = {}
    originals = {}
    def contents(name):
        if name not in files:
            info = disc_files.find(disc,name)
            files[name] = bytearray(disc.read_file(info['extent'],info['size']))
            oi = disc_files.find(original,name)
            originals[name] = original.read_file(oi['extent'],oi['size'])
            if len(files[name]) != len(originals[name]):
                raise ValueError(f'{name}: 원본과 크기가 다릅니다.')
        return files[name], originals[name]
    changed = {}
    for table in registry.TABLES:
        for game, parts in table['games'].items():
            path = MOD_ROOT/'data/balance'/f"{table['key']}_{game.lower()}.json"
            value = table['module'].encode(load(path))
            payloads = (value,) if isinstance(value,(bytes,bytearray)) else tuple(value)
            if len(parts) != len(payloads):
                raise ValueError(f'{path}: 구간 개수 불일치')
            for part,payload in zip(parts,payloads):
                if len(payload) != part['size']:
                    raise ValueError(f'{path}: 테이블 크기 변경은 지원하지 않습니다.')
                target, pristine = contents(part['path'])
                start = part['offset']
                n=apply_delta(target,pristine[start:start+part['size']],payload,start,path.name)
                changed[part['path']] = changed.get(part['path'],0)+n
    for patch in load(MOD_ROOT/'data/code_patches.json')['patches']:
        target,_ = contents(patch['file'])
        n=apply_delta(target,bytes.fromhex(patch['before']),bytes.fromhex(patch['after']),patch['offset'],patch['label'])
        changed[patch['file']] = changed.get(patch['file'],0)+n

    stage_name='LANG2/SCEN.DAT'
    target,pristine=contents(stage_name)
    tree=scen_tool.parse(bytes(target)); original_tree=scen_tool.parse(pristine)
    stages=load(MOD_ROOT/'data/balance/stage_l2.json')
    if len(stages)!=stage_dat.STAGE_COUNT:
        raise ValueError('스테이지 개수 변경은 지원하지 않습니다.')
    stage_changes=0
    for i,entry in enumerate(stages):
        old=original_tree.children[i].children[1].raw
        if stage_dat.unchanged(old,entry): continue
        leaf=tree.children[i].children[1]
        if leaf.raw!=old: raise ValueError(f'스테이지 {i}: 한글화 기반과 배치 데이터 충돌')
        leaf.raw=stage_dat.encode_stage(entry)
        stage_changes+=1
    if stage_changes:
        result=bytes(scen_tool.serialize(tree))
        if len(result)!=len(target):raise ValueError('SCEN 전체 크기가 바뀝니다.')
        files[stage_name]=bytearray(result)
        changed[stage_name]=sum(x!=y for x,y in zip(target,result))
    for name,count in changed.items():
        if count:
            info=disc_files.find(disc,name)
            disc.write_file(info['extent'],files[name],regen=True)
            print(f'{name}: 개조 바이트 {count}개')

    # Build into an independent staging folder. No hardlinks, no upstream writes.
    build=MOD_ROOT/'build'; build.mkdir(exist_ok=True)
    work=build/'disc-mod.pending'
    if work.exists():
        raise ValueError(f'이전 임시 결과가 남았습니다. 확인 후 이름을 바꾸고 다시 실행하세요: {work}')
    work.mkdir()
    disc.save(str(work/'track1.bin'))
    for i in range(2,7):shutil.copy2(base_dir/f'track{i}.bin',work/f'track{i}.bin')
    shutil.copy2(base_dir/'langrisser-krpoc.cue',work/'langrisser-mod.cue')
    output_hashes={f'track{i}.bin':sha256(work/f'track{i}.bin') for i in range(1,7)}
    if any(output_hashes[f'track{i}.bin'] != base_hashes[f'track{i}.bin'] for i in range(2,7)):
        raise ValueError('보조 트랙 복사 중 변경을 발견했습니다.')
    if input_hashes(TRANSLATION_ROOT)!=manifest['inputs'] or any(sha256(base_dir/k)!=v for k,v in base_hashes.items()):
        raise ValueError('빌드 중 한글화 원본이 바뀌었습니다. 다시 실행하세요.')
    if any(sha256(MOD_ROOT/k)!=v for k,v in data_hashes.items()):
        raise ValueError('빌드 중 개조 입력이 바뀌었습니다. 다시 실행하세요.')
    record={'profile':load(MOD_ROOT/'project.json')['profile'],'translation_tracks':base_hashes,
            'translation_inputs':manifest['inputs'],'mod_inputs':data_hashes,'output_tracks':output_hashes,
            'changed_file_bytes':{k:v for k,v in changed.items() if v},'changed_stages':stage_changes}
    (work/'build-manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    output=build/'disc-mod'
    previous=build/'disc-mod.previous'
    if previous.exists():
        import datetime
        previous=build/('disc-mod.previous-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    if output.exists():output.rename(previous)
    try:work.rename(output)
    except OSError:
        if previous.exists() and not output.exists():previous.rename(output)
        raise
    print('개조 빌드 완료:',output/'langrisser-mod.cue')
    print('한글화 프로젝트는 변경하지 않았습니다. 새 CHD는 만들지 않았습니다.')

if __name__=='__main__':
    try:main()
    except (ValueError, FileNotFoundError) as e:
        print('중단:',e);sys.exit(1)
