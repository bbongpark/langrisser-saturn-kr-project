"""Read-only comparison of the decoded third-party data track and our builds.

Writes analysis artifacts in this directory only. Never applies a patch to a ROM.
Run with Python 3; uses existing project parsers without modifying them.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
A = Path(__file__).resolve().parent
R = A.parent.parent
sys.path[:0] = [str(R / "한글화/scripts"), str(R / "한글화/scripts/img_re"),
                str(R / "개조/scripts"), str(R / "개조/scripts/balance")]
from disc_tool import Disc
from disc_files import find
from scen_tool import parse
from img_codec import decompress
from sh2dis import disasm_one
import registry


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(disc, path):
    f = find(disc, path)
    return disc.read_file(f["extent"], f["size"])


paths = {
    "original": next((R / "Langrisser - Dramatic Edition (Japan) (1M)").glob("*Track 1*")),
    "third_party": A / "patched-track1.bin",
    "translation": R / "한글화/build/disc-krpoc/track1.bin",
    "mod": R / "개조/build/disc-mod/track1.bin",
}
sites = [("retreat_condition", 0xCEE8, 2), ("hire_add_function", 0x178C4, 84),
         ("mercenary_range", 0x2B3EE, 2), ("event_dispatch", 0x63830, 8)]
evidence = {"files": {}, "sites": {}, "table_differences": [], "scenario10": {}}
bins = {}
for label, path in paths.items():
    disc = Disc(path)
    evidence["files"][label] = {"path": str(path), "size": path.stat().st_size,
                                "sha256": digest(path)}
    b = read(disc, "LANG2.BIN")
    bins[label] = b
    evidence["sites"][label] = {name: {"file_offset": off, "hex": b[off:off+n].hex()}
                                for name, off, n in sites}
    sc = parse(read(disc, "LANG2/SCEN.DAT"))
    event = decompress(sc.children[9].children[0].raw)
    evidence["scenario10"][label] = {"decoded_length": len(event),
        "sha256": hashlib.sha256(event).hexdigest(), "offset": 0x577,
        "hex": event[0x577:0x579].hex(), "little_endian_value": int.from_bytes(event[0x577:0x579], "little")}
    del disc

original = Disc(paths["original"])
patched = Disc(paths["third_party"])
for table in registry.TABLES:
    for game, regions in table["games"].items():
        differences = []
        for region in regions:
            off, size = region["offset"], region["size"]
            old = read(original, region["path"])[off:off+size]
            new = read(patched, region["path"])[off:off+size]
            differences.extend({"path": region["path"], "offset": off+i,
                                "before": x, "after": y}
                               for i, (x, y) in enumerate(zip(old, new)) if x != y)
        evidence["table_differences"].append({"game": game, "table": table["key"],
                                                "differences": differences})

evidence["patch"] = {"path": str(R / "SS_Lang1_2_Patch/SS_Lang1_2_Patch.xdelta"),
    "sha256": digest(R / "SS_Lang1_2_Patch/SS_Lang1_2_Patch.xdelta")}
evidence["retreat_condition_truth_table"] = [
    {"flag_80": flag, "byte_3_is_zero": zero,
     "original_enters_increment_block": flag or zero,
     "patched_enters_increment_block": flag and zero}
    for flag in (False, True) for zero in (False, True)]
evidence["limits"] = [
    "First data track is covered by verified xdelta windows; entire joined image did not decode successfully.",
    "Static analysis only: no gameplay or voice playback verification.",
    "No previous version of the third-party Korean patch available to isolate its bold-name fix.",
    "No project source or build ROM was changed by this script.",
]
(A / "analysis_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

lines = []
for lo, hi in [(0xCEDE, 0xCF06), (0x178C4, 0x17918), (0x2B3AA, 0x2B3F6), (0x62430, 0x62446)]:
    lines.append(f"\nLANG2.BIN file offsets {lo:#x}..{hi:#x}; PC shown relative to file\n")
    for off in range(lo, hi, 2):
        row = []
        for label in ("original", "third_party"):
            word = struct.unpack_from(">H", bins[label], off)[0]
            row.append(f"{word:04x} {disasm_one(word, off)[0]}")
        lines.append(f"{off:06x}: {row[0]:52s} | {row[1]}")
(A / "code_comparison.txt").write_text("\n".join(lines), encoding="utf-8")
print("분석 근거 저장 완료:", A / "analysis_evidence.json")
