"""Guard against corrupting newer translations while applying a mod."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rebuild import apply_delta

class DeltaTests(unittest.TestCase):
    def test_unmodified_fields_preserve_new_translation(self):
        target = bytearray(b'NEWabcTAIL')
        self.assertEqual(apply_delta(target, b'abc', b'aXc', 3, 'item'), 1)
        self.assertEqual(target, b'NEWaXcTAIL')

    def test_new_translation_changes_inside_unchanged_fields_survive(self):
        target = bytearray(b'Qbc')
        apply_delta(target, b'abc', b'aXc', 0, 'item')
        self.assertEqual(target, b'QXc')

    def test_collision_stops_before_any_write(self):
        target = bytearray(b'abZ')
        with self.assertRaisesRegex(ValueError, '충돌'):
            apply_delta(target, b'abc', b'XYQ', 0, 'item')
        self.assertEqual(target, b'abZ')

    def test_reject_size_and_outside_file(self):
        for old, new, start in [(b'a', b'xy', 0), (b'ab', b'xy', 2), (b'a', b'x', -1)]:
            with self.assertRaises(ValueError):
                apply_delta(bytearray(b'abc'), old, new, start, 'item')

if __name__ == '__main__':
    unittest.main()
