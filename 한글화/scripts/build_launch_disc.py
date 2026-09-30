#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_launch_disc.py — assemble a launchable patched disc folder.

Track 1 = the patched build (build/Track 1 (patched).bin).
Tracks 1-6 are independent copies; no input/output hardlinks.
Writes a .cue mirroring the original TOC. Result is a self-contained folder
that emucap/Mednafen can launch directly.
"""
import os, shutil

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD  = os.path.join(ROOT, "build")
DISCSRC = os.environ.get("LANGRISSER_DISC",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Langrisser - Dramatic Edition (Japan) (1M)"))
OUT    = os.path.join(BUILD, "disc-krpoc")
BASE   = "Langrisser - Dramatic Edition (Japan) (1M)"

PATCHED_T1 = os.path.join(BUILD, "Track 1 (patched).bin")

# (track file suffix, output name) — tracks 2..6 copied from originals
TRACKS = [(f"{BASE} (Track {i}).bin", f"track{i}.bin") for i in range(1, 7)]

# CUE body mirroring the original TOC (T1 MODE1/2352, T2 MODE2/2352, T3-6 AUDIO)
CUE = """FILE "track1.bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
FILE "track2.bin" BINARY
  TRACK 02 MODE2/2352
    INDEX 00 00:00:00
    INDEX 01 00:03:00
FILE "track3.bin" BINARY
  TRACK 03 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
FILE "track4.bin" BINARY
  TRACK 04 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
FILE "track5.bin" BINARY
  TRACK 05 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
FILE "track6.bin" BINARY
  TRACK 06 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
"""

def link_or_copy(src, dst):
    if os.path.exists(dst):
        os.remove(dst)
    # Each output owns its bytes: editing a build must never modify its input.
    shutil.copy2(src, dst)
    return "독립 복사"

def main():
    assert os.path.exists(PATCHED_T1), "run build_poc_disc.py first"
    os.makedirs(OUT, exist_ok=True)
    # track1 = independent copy of the translation build
    how = link_or_copy(PATCHED_T1, os.path.join(OUT, "track1.bin"))
    print(f"track1.bin <- patched build ({how})")
    # tracks 2..6 = independent copies of originals
    for src_name, out_name in TRACKS[1:]:
        src = os.path.join(DISCSRC, src_name)
        how = link_or_copy(src, os.path.join(OUT, out_name))
        print(f"{out_name} <- original ({how})")
    cue_path = os.path.join(OUT, "langrisser-krpoc.cue")
    with open(cue_path, "w", newline="\r\n") as f:
        f.write(CUE)
    print(f"\ncue -> {cue_path}")
    print("launch this cue via emucap (system=saturn) once the bridge is up.")

if __name__ == "__main__":
    main()
