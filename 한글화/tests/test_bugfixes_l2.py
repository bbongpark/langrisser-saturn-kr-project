"""Behavior tests for the actual emitted SH-2 words and scenario boundaries."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bugfixes_l2 as B
import scen_tool
from img_re.img_codec import decompress


class Machine:
    """Small strict interpreter for instructions used by these two handlers.

    Unknown instructions fail. Includes signed byte loads, PC-load alignment,
    comparison, multiplication and the return delay slot.
    """
    def __init__(self, code):
        self.code = code
        self.mem = {}
        self.reg = [0x20000000 + 256*i for i in range(16)]
        self.t = False
        self.macl = 0

    def read(self, addr, size):
        if 0x06010000 <= addr < 0x06010000 + len(self.code):
            return int.from_bytes(self.code[addr-0x06010000:addr-0x06010000+size], 'big')
        return int.from_bytes(bytes(self.mem.get(addr+i, 0) for i in range(size)), 'big')

    def write(self, addr, val, size):
        for i, b in enumerate((val & ((1 << (8*size))-1)).to_bytes(size, 'big')):
            self.mem[addr+i] = b

    @staticmethod
    def signed(v, bits):
        return v - (1 << bits) if v & (1 << (bits-1)) else v

    def run(self, offset):
        pc = 0x06010000 + offset
        returning = False
        jump_target = None
        for _ in range(150):
            w = self.read(pc, 2)
            n, m, lo, op = (w >> 8) & 15, (w >> 4) & 15, w & 15, w >> 12
            r = self.reg
            next_pc = pc + 2
            was_returning = returning
            was_jump = jump_target
            jump_target = None
            if w == 0x000B: returning = True
            elif w == 0x0009: pass
            elif op == 0xD: r[n] = self.read(((pc+4) & ~3) + (w & 255)*4, 4)
            elif op == 0xE: r[n] = self.signed(w & 255, 8)
            elif op == 1: self.write(r[n]+lo*4, r[m], 4)
            elif op == 2 and lo == 0: self.write(r[n], r[m], 1)
            elif op == 2 and lo == 2: self.write(r[n], r[m], 4)
            elif op == 2 and lo == 6:
                r[n] -= 4
                self.write(r[n], r[m], 4)
            elif op == 6 and lo == 0: r[n] = self.signed(self.read(r[m], 1), 8)
            elif op == 6 and lo == 2: r[n] = self.read(r[m], 4)
            elif op == 6 and lo == 3: r[n] = r[m]
            elif op == 6 and lo == 4:
                v = self.signed(self.read(r[m], 1), 8)
                if n != m: r[m] += 1
                r[n] = v
            elif op == 6 and lo == 6:
                r[n] = self.read(r[m], 4)
                if n != m: r[m] += 4
            elif op == 6 and lo == 12: r[n] = r[m] & 255
            elif op == 7: r[n] += self.signed(w & 255, 8)
            elif op == 0 and lo == 7: self.macl = (r[n]*r[m]) & 0xFFFFFFFF
            elif op == 0 and (w & 255) == 0x1A: r[n] = self.macl
            elif op == 0 and lo == 2: r[n] = int(self.t)
            elif op == 0 and lo == 4: self.write(r[0]+r[n], r[m], 1)
            elif op == 0 and lo == 12: r[n] = self.signed(self.read(r[0]+r[m], 1), 8)
            elif op == 3 and lo == 12: r[n] += r[m]
            elif op == 3 and lo == 7: self.t = self.signed(r[n], 32) > self.signed(r[m], 32)
            elif op == 3 and lo == 3: self.t = self.signed(r[n], 32) >= self.signed(r[m], 32)
            elif op == 4 and lo == 14: self.t = bool(r[n] & 1)
            elif op == 4 and (w & 255) == 0x2B: jump_target = r[n]
            elif (w >> 8) == 0x88:
                self.t = r[0] == self.signed(w & 255, 8)
            elif (w >> 8) == 0x89:
                if self.t: next_pc = pc + 4 + self.signed(w & 255, 8)*2
            elif (w >> 8) == 0x8B:
                if not self.t: next_pc = pc + 4 + self.signed(w & 255, 8)*2
            else: raise AssertionError(f'unsupported instruction {w:04x} at {pc:08x}')
            self.reg = [v & 0xFFFFFFFF for v in r]
            if was_returning: return
            if was_jump is not None: next_pc = was_jump
            pc = next_pc
        raise AssertionError('handler did not return')


class BugfixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (ROOT / 'original/LANG2.BIN').read_bytes()
        cls.fixed = B.patch_bin(cls.original)

    def machine(self, character, field, value, initial, code=None):
        vm = Machine(self.fixed if code is None else code)
        for i in range(20*40+256): vm.write(0x0609C9C8+i, initial, 1)
        vm.write(0x0609FEB0, 0x06120000, 4)
        vm.write(0x0609CD94, 0x06121000, 4)
        vm.write(0x06121047, character, 1)
        vm.write(0x06120000, field, 1)
        vm.write(0x06120001, value, 1)
        return vm

    def test_every_other_add_is_identical_to_original(self):
        self.assertEqual(self.fixed[B.START:B.END], self.original[B.START:B.END])
        for character in (0, 1, 5, 19):
            for field in (0, 2, 4, 5, 6, 7, 8, 10, 39, 128, 255):
                for increment in (0, 1, 2, 255):
                    if (field, increment) == (6, 2): continue
                    for old in (0, 2, 6, 127):
                        fixed = self.machine(character, field, increment, old)
                        original = self.machine(character, field, increment, old, self.original)
                        fixed.t = original.t = bool(character % 2)
                        fixed.run(B.CAVE_START)
                        original.run(0x178EC)
                        self.assertEqual(fixed.mem, original.mem)
                        self.assertEqual(fixed.reg, original.reg)
                        self.assertEqual(fixed.t, original.t)

    def test_hire_plus_two_targets_current_character(self):
        for character in (0, 1, 5, 16, 17, 18, 19):
            for old in (0, 2, 3, 6, 127):
                vm = self.machine(character, 6, 2, old)
                before = dict(vm.mem)
                preserved = vm.reg[4:]
                vm.run(B.CAVE_START)
                address = 0x0609C9C8 + character*40 + 6
                self.assertEqual(vm.read(address, 1), (max(old, 3) + 2) & 255)
                self.assertEqual(vm.read(0x0609FEB4, 4), 3)
                self.assertEqual(vm.reg[4:], preserved)
                allowed = {address, *range(0x0609FEB4, 0x0609FEB8),
                           *range(preserved[-1]-4, preserved[-1])}
                self.assertTrue(all(a in allowed or v == before.get(a) for a, v in vm.mem.items()))

    def test_original_assign_semantics_preserved(self):
        for character in (0, 8, 19):
            for field in (0, 6, 7, 8, 39, 128, 255):
                vm = self.machine(character, field, 213, 7)
                vm.run(B.START)
                self.assertEqual(vm.read(0x0609C9F0+field, 1), 213)
                self.assertEqual(vm.read(0x0609FEB4, 4), 3)

    def test_character_creation_a_d_modifiers_keep_original_values(self):
        # The goddess quiz adds +2 A and +4 D. Warlock's separate
        # class base is 2/0, so the intended result is 4/4, not 7/7.
        # A zero current-character slot reproduces the dangerous context in
        # which the partial hire rewrite lost the quiz bonuses entirely.
        vm = self.machine(0, 7, 1, 0)
        for field, additions in ((7, 2), (8, 4)):
            address = 0x0609C9C8 + 40 + field
            vm.write(0x06120000, field, 1)
            for _ in range(additions):
                vm.run(B.CAVE_START)
            self.assertEqual(vm.read(address, 1), additions)

    def test_character_creation_script_never_enters_hire_exception(self):
        tree = scen_tool.parse((ROOT / 'original/LANG2_SCEN.DAT').read_bytes())
        event = decompress(tree.children[98].children[0].raw)
        self.assertIn(bytes.fromhex('4a0701'), event)
        self.assertIn(bytes.fromhex('4a0801'), event)
        self.assertNotIn(bytes.fromhex('4a0602'), event)

    def test_rejects_conflicts(self):
        changed = bytearray(self.original)
        changed[B.CAVE_START] ^= 1
        before = bytes(changed)
        with self.assertRaises(ValueError): B.patch_bin(changed)
        self.assertEqual(bytes(changed), before)
        B.verify_bin(self.fixed)
        with self.assertRaises(ValueError): B.verify_bin(self.original)

    def test_scenario_changes_only_voice_and_padding(self):
        raw = (ROOT / 'original/LANG2_SCEN.DAT').read_bytes()
        tree = scen_tool.parse(raw)
        event = decompress(tree.children[9].children[0].raw)
        B.patch_scenario(tree)
        out = bytes(scen_tool.serialize(tree))
        new = scen_tool.parse(out)
        old = scen_tool.parse(raw)
        self.assertEqual(len(out), len(raw))
        self.assertEqual([(n.start, n.end) for n in old.children], [(n.start, n.end) for n in new.children])
        self.assertEqual(decompress(new.children[9].children[0].raw), event[:0x577]+bytes.fromhex('7609')+event[0x579:])
        for i, (a, b) in enumerate(zip(old.children, new.children)):
            if i != 9: self.assertEqual(raw[a.start:a.end], out[b.start:b.end])
        for i, (a, b) in enumerate(zip(old.children[9].children, new.children[9].children)):
            if i == 0: continue
            x, y = raw[a.start:a.end], out[b.start:b.end]
            if any(x): self.assertEqual(x, y)
            else: self.assertFalse(any(y))


if __name__ == '__main__': unittest.main()
