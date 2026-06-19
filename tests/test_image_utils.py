from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard_tool.image_utils import create_blank_psd


class TestCreateBlankPsdAtomicWrite(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_create_blank_psd_creates_final_and_returns_final_path(self) -> None:
        target = Path(self._tmp) / "shot_001.notpsd"

        result = create_blank_psd(target, 16, 16, background_color="#112233")

        expected = target.with_suffix(".psd")
        self.assertEqual(result, expected)
        self.assertTrue(expected.is_file())
        self.assertFalse(expected.with_suffix(".tmp.psd").exists())

    def test_failed_save_preserves_existing_final_and_cleans_temp(self) -> None:
        target = Path(self._tmp) / "shot_001.psd"
        original = b"original psd bytes"
        target.write_bytes(original)
        tmp = target.with_suffix(".tmp.psd")

        class FailingPsd:
            def save(self, path: Path) -> None:
                path.write_bytes(b"partial psd bytes")
                raise RuntimeError("simulated save failure")

        with patch("psd_tools.PSDImage.new", return_value=FailingPsd()):
            with self.assertRaises(RuntimeError):
                create_blank_psd(target, 16, 16)

        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(tmp.exists())


if __name__ == "__main__":
    unittest.main()
