"""One configured translation dependency, read-only for modification tools."""
import json
from pathlib import Path

MOD_ROOT = Path(__file__).resolve().parents[2]
config = json.loads((MOD_ROOT / 'project.json').read_text(encoding='utf-8'))
TRANSLATION_ROOT = (MOD_ROOT / config['translation_project']).resolve()
TRANSLATION_SCRIPTS = str(TRANSLATION_ROOT / 'scripts')
