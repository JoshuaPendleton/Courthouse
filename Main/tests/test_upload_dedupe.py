"""Identical target uploads are stored once and survive a restart."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_engine as le  # noqa: E402

DATA_A = b'GGUF' + b'\x00' * 60 + b'model-a'
DATA_B = b'GGUF' + b'\x00' * 60 + b'model-b'


def upload(data, name='target.gguf'):
    return le.save_upload(io.BytesIO(data), len(data), name)


class UploadDedupeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (le.UPLOAD_DIR, le.DIR, dict(le.REGISTRY), dict(le._UPLOAD_BY_SHA), le._UPLOADS_INDEXED)
        le.UPLOAD_DIR = le.DIR = Path(self.tmp.name)
        self.restart()

    def tearDown(self):
        le.UPLOAD_DIR, le.DIR, reg, idx, le._UPLOADS_INDEXED = self.saved
        le.REGISTRY.clear(); le.REGISTRY.update(reg)
        le._UPLOAD_BY_SHA.clear(); le._UPLOAD_BY_SHA.update(idx)
        self.tmp.cleanup()

    def restart(self):
        for k in [k for k, v in le.REGISTRY.items() if v.get('source') == 'uploaded_target']:
            del le.REGISTRY[k]
        le._UPLOAD_BY_SHA.clear()
        le._UPLOADS_INDEXED = False

    def files(self):
        return sorted(p.name for p in Path(self.tmp.name).glob('*.gguf'))

    def test_same_weights_uploaded_twice_are_stored_once(self):
        first = upload(DATA_A, 'a.gguf')
        second = upload(DATA_A, 'a-again.gguf')
        self.assertEqual(first['model_id'], second['model_id'])
        self.assertTrue(second.get('reused'))
        self.assertEqual(second['name'], 'a-again.gguf')
        self.assertEqual(len(self.files()), 1)

    def test_different_weights_get_separate_files(self):
        self.assertNotEqual(upload(DATA_A)['model_id'], upload(DATA_B)['model_id'])
        self.assertEqual(len(self.files()), 2)

    def test_existing_upload_is_reused_after_restart(self):
        first = upload(DATA_A)
        self.restart()
        self.assertIsNotNone(le.get_model_info(first['model_id']))   # old id still resolves
        again = upload(DATA_A)
        self.assertEqual(again['model_id'], first['model_id'])
        self.assertEqual(len(self.files()), 1)


if __name__ == '__main__':
    unittest.main()
