"""Four original-game fixes, separate from optional crown/shop modifications.

The hire increase fix handles only the event command (field=6, delta=+2).
Every other add command retains the original handler, including character
creation. The small helper lives in verified zero padding after game data.
"""
import hashlib
import struct

FIX_IDS = ('retreat-count', 'hire-increase', 'elemental-hiring', 'scenario10-leon-voice')
START, END = 0x178C4, 0x17918
CAVE_START, CAVE_SIZE = 0x65B00, 0x100
HIRE_START = CAVE_START + 0x80
ORIGINAL_FUNCTIONS = bytes.fromhex(
    '2fe66ef3d305d206e1032212d10561126214602c61100314000b6ef6'
    '0609c9f00609feb40609feb02fe66ef3d306d207e1032212d1066212'
    '6124601c013c6220312c0314000b6ef60609c9f00609feb40609feb0')


def _assemble(base, words, refs, branches, literals):
    """Resolve the small set of PC-relative loads and branches used below."""
    while (base + 2 * len(words)) % 4:
        words.append(0x0009)
    labels = {}
    for name, value in literals:
        labels[name] = base + 2 * len(words)
        words.extend((value >> 16, value & 0xFFFF))
    for index, reg, label in refs:
        pc = base + 2 * index
        distance = labels[label] - ((pc + 4) & ~3)
        assert distance % 4 == 0
        disp = distance // 4
        assert 0 <= disp <= 255
        words[index] = 0xD000 | (reg << 8) | disp
    for index, opcode, target in branches:
        pc = base + 2 * index
        distance = (base + 2 * target) - (pc + 4)
        assert distance % 2 == 0
        disp = distance // 2
        assert -128 <= disp <= 127
        words[index] = opcode | (disp & 255)
    return struct.pack('>' + 'H' * len(words), *words)


def hire_code():
    """Keep original 0x49/0x4A handlers; divert only 4A 06 02.

    The character-making script uses 4A for A/D and other stats. Replacing the
    generic handler caused 7/7, and a partial guard caused 2/0. Tail-jumping to
    the original handler for every other command preserves its exact behavior.
    """
    words, refs, branches = [], [], []
    def word(v): words.append(v)
    def load(reg, label): refs.append((len(words), reg, label)); word(0)
    word(0x0302)             # stc sr,r3 (preserve caller's T flag)
    load(1, 'script')
    for v in (0x6112, 0x6014, 0x8806): word(v)  # field == 6?
    branches.append((len(words), 0x8B00, None)); word(0)
    for v in (0x6010, 0x8802): word(v)          # delta == 2?
    branches.append((len(words), 0x8B00, None)); word(0)
    for v in (0x430E,): word(v)                 # restore SR
    load(2, 'hire')
    for v in (0x422B, 0x0009): word(v)         # tail-jump hire helper
    original_label = len(words)
    word(0x430E)                              # restore SR
    load(2, 'original')
    for v in (0x422B, 0x0009): word(v)         # tail-jump original add
    branches = [(i, op, original_label) for i, op, _ in branches]
    wrapper = _assemble(CAVE_START, words, refs, branches, [
        ('script', 0x0609FEB0),
        ('hire', 0x06010000 + HIRE_START),
        ('original', 0x06010000 + 0x178EC),
    ])

    words, refs = [], []
    def word(v): words.append(v)
    def load(reg, label): refs.append((len(words), reg, label)); word(0)
    for v in (0x0002, 0x2F06): word(v)         # save SR on stack
    load(1, 'script')
    for v in (0xE003, 0x1101, 0x6212, 0x6024, 0x600C, 0x6320): word(v)
    load(1, 'character')
    for v in (0x6112, 0x7147, 0x6110, 0x611C, 0xE228, 0x0127, 0x011A): word(v)
    load(2, 'table')
    for v in (0x312C, 0x310C, 0x6210, 0xE003, 0x3203, 0x8900,
              0x6203, 0x323C, 0x60F6, 0x400E, 0xE006, 0x000B, 0x2120): word(v)
    hire = _assemble(HIRE_START, words, refs, [], [
        ('script', 0x0609FEB0),
        ('character', 0x0609CD94),
        ('table', 0x0609C9C8),
    ])
    assert len(wrapper) <= HIRE_START - CAVE_START
    assert len(hire) <= CAVE_SIZE - (HIRE_START - CAVE_START)
    code = bytearray(CAVE_SIZE)
    code[:len(wrapper)] = wrapper
    code[HIRE_START-CAVE_START:HIRE_START-CAVE_START+len(hire)] = hire
    return bytes(code)


def patches():
    return [
        (0xCEE8, bytes.fromhex('8f04'), bytes.fromhex('890d'), 'retreat-count'),
        (CAVE_START, bytes(CAVE_SIZE), hire_code(), 'hire-increase-helper'),
        (0x63834, bytes.fromhex('060278ec'),
         struct.pack('>I', 0x06010000 + CAVE_START), 'hire-increase-dispatch'),
        (0x2B3EE, bytes.fromhex('e144'), bytes.fromhex('e146'), 'elemental-hiring'),
    ]


def patch_bin(data):
    out = bytearray(data)
    for off, old, new, label in patches():
        if data[off:off+len(old)] != old:
            raise ValueError(f'{label}: unexpected LANG2.BIN bytes at {off:#x}')
        out[off:off+len(new)] = new
    return bytes(out)


def patch_scenario(tree):
    """Change only the voice reference; keep every top-level block size fixed."""
    from img_re.img_codec import decompress, compress
    import scen_tool
    block = tree.children[9]
    leaf = block.children[0]
    original_block = bytes(scen_tool.serialize(block))
    decoded = decompress(leaf.raw)
    if len(decoded) != 2146 or decoded[0x574:0x582] != bytes.fromhex('33c102c202c302c402c502c60202'):
        raise ValueError('scenario10-leon-voice: unexpected event data')
    fixed = decoded[:0x577] + bytes.fromhex('7609') + decoded[0x579:]
    compressed = compress(fixed)
    if decompress(compressed) != fixed:
        raise ValueError('scenario10-leon-voice: compression round-trip failed')
    # Keep alignment of every following child by padding to a four-byte boundary.
    compressed += b'\0' * (-len(compressed) % 4)
    growth = len(compressed) - len(leaf.raw)
    pads = [n for _, n in scen_tool.iter_leaves(block) if n is not leaf and n.raw and not any(n.raw)]
    if not pads:
        raise ValueError('scenario10-leon-voice: no safe padding')
    pad = max(pads, key=lambda n: len(n.raw))
    if growth > len(pad.raw):
        raise ValueError('scenario10-leon-voice: insufficient padding')
    # All validation precedes mutation.
    leaf.raw = compressed
    pad.raw = pad.raw[:len(pad.raw)-growth] if growth >= 0 else pad.raw + b'\0' * -growth
    if len(scen_tool.serialize(block)) != len(original_block):
        raise ValueError('scenario10-leon-voice: block size changed')
    return {'event_bytes': len(decoded), 'compressed_growth': growth,
            'event_sha256': hashlib.sha256(fixed).hexdigest()}


def verify_bin(data):
    for off, _, new, label in patches():
        if data[off:off+len(new)] != new:
            raise ValueError(f'{label}: final build mismatch at {off:#x}')
