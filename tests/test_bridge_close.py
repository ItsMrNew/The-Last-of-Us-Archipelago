import ctypes
import gc
import mmap
import unittest
import weakref
from types import SimpleNamespace
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory

from tlou_ap.native.bridge import Bridge, Shared


class BridgeCloseTests(unittest.TestCase):
    def test_missing_manifest_closes_process_and_preserves_error(self):
        memory = SimpleNamespace(close=Mock())
        with TemporaryDirectory() as directory:
            with patch('tlou_ap.native.bridge.ProcessReader', return_value=memory):
                with self.assertRaises(FileNotFoundError):
                    Bridge(123, directory)
        memory.close.assert_called_once()

    def fixture(self):
        bridge = Bridge.__new__(Bridge)
        bridge.mapping = mmap.mmap(-1, ctypes.sizeof(Shared))
        bridge.shared = Shared.from_buffer(bridge.mapping)
        bridge.memory = SimpleNamespace(close=Mock())
        return bridge

    def test_close_releases_mapping_and_process(self):
        bridge = self.fixture(); mapping = bridge.mapping
        bridge.close(); bridge.close()
        self.assertTrue(mapping.closed)
        self.assertIsNone(bridge.shared)
        bridge.memory.close.assert_called()

    def test_rejected_attach_preserves_original_error_and_releases_after_traceback(self):
        bridge = self.fixture()
        ref = weakref.ref(bridge.mapping)
        bridge.manifest = {'build_id': 123}
        bridge.shared.magic = 1  # Incompatible live bridge, before any process access.
        try:
            bridge.attach()
        except ValueError as error:
            self.assertIn('incompatible bridge', str(error))
            bridge.close()  # attach's local ctypes view is held by this traceback.
            bridge.memory.close.assert_called_once()
            self.assertIsNone(bridge.mapping)
        gc.collect()
        self.assertIsNone(ref())

    def test_external_view_remains_valid_until_released(self):
        bridge = self.fixture()
        view = bridge.shared; view.error = 7
        ref = weakref.ref(bridge.mapping)
        bridge.close()
        self.assertEqual(view.error, 7)
        del view
        gc.collect()
        self.assertIsNone(ref())
