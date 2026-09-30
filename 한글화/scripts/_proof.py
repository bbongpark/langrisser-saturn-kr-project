import sys, io, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
import kr_font
# read the 3 baked glyphs from the patched FONT extracted concept: use patched font file
fd = kr_font.FontDat.load(r"C:\Project\Lang Korean\kr-patch\build\LANG1_FONT.patched.dat")
# 크리스 assigned to block4 idx 0,1,2
glyphs = [fd.read_glyph(4, i) for i in (0,1,2)]
kr_font.render_montage_png(glyphs, r"C:\Project\Lang Korean\kr-patch\build\poc_keuriseu.png", swap=True, scale=10, cols=3)
print("rendered poc_keuriseu.png (크리스 from patched FONT.DAT, swap-undone)")
