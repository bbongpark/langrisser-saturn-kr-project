#!/usr/bin/env python3
"""
disc_tool.py — read/write files inside a Saturn MODE1/2352 data track, with
correct CD-ROM EDC/ECC regeneration for changed sectors.

Sector (2352 bytes, MODE1):
  0x000 sync(12)  0x00C header(4)  0x010 user-data(2048)
  0x810 EDC(4, LE)  0x814 zero(8)  0x81C ECC-P(172)  0x8C8 ECC-Q(104)

EDC/ECC = standard CD algorithm (Neill Corlett ECM). Validated in __main__ by
recomputing over untouched original sectors and comparing to stored bytes.
"""
import struct, os

RAW, UD, HDR = 2352, 2048, 16

# ---- lookup tables ----
_ecc_f = bytearray(256)
_ecc_b = bytearray(256)
_edc_lut = [0] * 256

def _init_tables():
    for i in range(256):
        j = (i << 1) ^ (0x11D if (i & 0x80) else 0)
        _ecc_f[i] = j & 0xFF
        _ecc_b[i ^ (j & 0xFF)] = i
        edc = i
        for _ in range(8):
            edc = (edc >> 1) ^ (0xD8018001 if (edc & 1) else 0)
        _edc_lut[i] = edc & 0xFFFFFFFF
_init_tables()

def edc_compute(data):
    edc = 0
    for b in data:
        edc = (edc >> 8) ^ _edc_lut[(edc ^ b) & 0xFF]
    return edc & 0xFFFFFFFF

def _ecc_block(sector, major_count, minor_count, major_mult, minor_inc, dest_off):
    size = major_count * minor_count
    src_base = 0x0C
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = 0
        ecc_b = 0
        for _ in range(minor_count):
            temp = sector[src_base + index]
            index += minor_inc
            if index >= size:
                index -= size
            ecc_a ^= temp
            ecc_b ^= temp
            ecc_a = _ecc_f[ecc_a]
        ecc_a = _ecc_b[_ecc_f[ecc_a] ^ ecc_b]
        sector[dest_off + major] = ecc_a
        sector[dest_off + major + major_count] = (ecc_a ^ ecc_b) & 0xFF

def regen_sector(sector):
    """sector: bytearray(2352) MODE1. Recompute EDC (0x810) and ECC P/Q in place."""
    edc = edc_compute(sector[0x00:0x810])          # over sync+header+data (2064B)
    struct.pack_into("<I", sector, 0x810, edc)
    # 8 intermediate zero bytes at 0x814 must be zero for ECC
    for i in range(0x814, 0x81C):
        sector[i] = 0
    _ecc_block(sector, 86, 24, 2, 86, 0x81C)       # P
    _ecc_block(sector, 52, 43, 86, 88, 0x8C8)      # Q
    return sector


class Disc:
    def __init__(self, track1_path):
        self.path = track1_path
        with open(track1_path, "rb") as f:
            self.data = bytearray(f.read())
        assert len(self.data) % RAW == 0, "track1 not a multiple of 2352"
        self.nsec = len(self.data) // RAW

    def read_file(self, lba, size):
        nsec = (size + UD - 1) // UD
        out = bytearray()
        for i in range(nsec):
            base = (lba + i) * RAW + HDR
            out += self.data[base:base + UD]
        return bytes(out[:size])

    def write_file(self, lba, payload, regen=True):
        """Write payload across sectors starting at lba, regenerating EDC/ECC.
        payload length must fit the file's original sector count (same-size patch)."""
        nsec = (len(payload) + UD - 1) // UD
        for i in range(nsec):
            sec_off = (lba + i) * RAW
            sector = self.data  # view
            chunk = payload[i * UD:(i + 1) * UD]
            # write user data
            sector[sec_off + HDR: sec_off + HDR + len(chunk)] = chunk
            if len(chunk) < UD:  # zero-pad tail of last sector's user area
                sector[sec_off + HDR + len(chunk): sec_off + HDR + UD] = b"\x00" * (UD - len(chunk))
            if regen:
                s = bytearray(self.data[sec_off:sec_off + RAW])
                regen_sector(s)
                self.data[sec_off:sec_off + RAW] = s

    def save(self, out_path):
        with open(out_path, "wb") as f:
            f.write(self.data)


if __name__ == "__main__":
    TRACK1 = os.path.join(os.environ.get("LANGRISSER_DISC",
           os.environ.get("LANGRISSER_DISC",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Langrisser - Dramatic Edition (Japan) (1M)"))), "Langrisser - Dramatic Edition (Japan) (1M) (Track 1).bin")
    d = Disc(TRACK1)
    print(f"sectors: {d.nsec:,}")
    # VALIDATE: recompute EDC/ECC on untouched sectors, compare to stored bytes.
    import random
    random.seed(1)
    test_lbas = [16, 20, 142, 202, 404, 136946, 157751] + [random.randint(0, d.nsec - 1) for _ in range(40)]
    ok_edc = ok_ecc = bad = skipped = 0
    for lba in test_lbas:
        off = lba * RAW
        sec = d.data[off:off + RAW]
        # only MODE1 sectors (mode byte at 0x0F == 1)
        if sec[0x0F] != 0x01:
            skipped += 1
            continue
        ref = bytearray(sec)
        test = bytearray(sec)
        regen_sector(test)
        edc_match = test[0x810:0x814] == ref[0x810:0x814]
        ecc_match = test[0x81C:0x930] == ref[0x81C:0x930]
        ok_edc += edc_match
        ok_ecc += ecc_match
        if not (edc_match and ecc_match):
            bad += 1
            print(f"  LBA {lba}: EDC {'ok' if edc_match else 'MISMATCH'} ECC {'ok' if ecc_match else 'MISMATCH'}")
    print(f"validated MODE1 sectors: EDC ok={ok_edc}, ECC ok={ok_ecc}, bad={bad}, skipped(non-MODE1)={skipped}")
    print("EDC/ECC implementation:", "CORRECT" if bad == 0 and ok_ecc > 0 else "WRONG")
