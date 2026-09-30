#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebuild.py — 검수한 워크시트를 게임 디스크에 반영(3단계 빌드 한 번에).

  python scripts/rebuild.py

  = 1) reinsert_text.py build/worksheet_dedup_final.json   (SCEN/FONT/BIN 재삽입)
    2) build_launch_disc.py                                 (디스크 조립)
    3) KR_CLASSNAMES=1 KR_HUD8=1 img_re/gen_hud8.py         (IMG.DAT 한글 라벨+8px HUD)

⚠ 실행 중 에뮬레이터가 build/disc-krpoc/track1.bin 을 잡고 있으면 파일 잠금으로 2단계가
   실패한다 — 먼저 에뮬을 닫을 것.
⚠ 실기 검증은 세이브스테이트가 아니라 **새 게임으로 시나리오 진입**해야 반영됨(SCEN이 RAM에 캐시됨).

정본 인자 = build/worksheet_dedup_final.json (검수 툴 dialogue_editor.py 가 저장하는 그 파일).
"""
import os
import subprocess
import sys

# 자기 stdout도 UTF-8로 (한글 요약 출력이 cp949에서 죽는다).
# ⚠ TextIOWrapper로 다시 감싸지 말 것 — 세션21의 이중 래핑 버그.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WS = os.path.join(ROOT, "build", "worksheet_dedup_final.json")

STEPS = [
    ("reinsert", [sys.executable, os.path.join(HERE, "reinsert_text.py"), WS]),
    ("build_launch_disc", [sys.executable, os.path.join(HERE, "build_launch_disc.py")]),
    ("gen_hud8", [sys.executable, os.path.join(HERE, "img_re", "gen_hud8.py")]),
]


def main():
    try:
        import PIL
        import numpy
    except ImportError:
        print('필수 도구가 없습니다. 한글화 폴더의 환경_준비.bat를 실행하세요.')
        sys.exit(1)
    if not os.path.exists(WS):
        print(f"워크시트 없음: {WS}")
        sys.exit(1)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", KR_CLASSNAMES="1", KR_HUD8="1")
    env['LANGRISSER_DISC'] = os.environ.get('LANGRISSER_DISC', os.path.join(
        os.path.dirname(ROOT), 'Langrisser - Dramatic Edition (Japan) (1M)'))
    for setting in ('KR_DLG_LINES', 'KR_DLG_PAGE2', 'KR_NO_ABSORB', 'KR_SCEN_TITLES'):
        env.pop(setting, None)
    manifest = os.path.join(ROOT, 'build', 'translation-manifest.json')
    if os.path.exists(manifest):
        os.remove(manifest)
    for i, (name, cmd) in enumerate(STEPS, 1):
        print(f"\n=== {i}/3: {name} ===")
        if subprocess.run(cmd, env=env, cwd=ROOT).returncode != 0:
            print(f"\n!! 단계 {i}({name}) 실패. 위 오류를 확인하세요. 파일 잠금 오류라면 에뮬레이터를 닫으세요.")
            sys.exit(1)
    for check in ('verify_disc_layout.py', 'verify_goddess_frozen.py', 'fix_josa_all.py', 'verify_base_fixes.py'):
        subprocess.run([sys.executable, '-B', os.path.join(HERE, check)], env=env, cwd=ROOT, check=True)
    from build_manifest import publish
    publish()
    print("\n한글화 전용 완료 — build/disc-krpoc 에 반영됨. 개조 폴더는 변경하지 않았습니다.")
    print("에뮬 재시작 후 **새 게임으로** 시나리오에 진입해 확인하세요(세이브스테이트는 옛 SCEN 캐시).")


if __name__ == "__main__":
    main()
