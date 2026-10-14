import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tlou_ap.save_affinity import SaveEntry
from tlou_ap.save_guide_ui import SaveGuide
from tlou_ap.theme import Appearance, PALETTES


class SaveGuideUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk(); self.root.withdraw(); self.addCleanup(self.root.destroy)
        self.app = SimpleNamespace(root=self.root, run_name='fixture', appearance=Appearance(self.root, 'dark'))
        self.api = Mock()
        self.api.focused_rect.return_value = None
        self.api.user.GetAsyncKeyState.return_value = 0
        with patch('tlou_ap.save_guide_ui.GameWindow', return_value=self.api):
            self.guide = SaveGuide(self.app, Path(self.temp.name), lambda: 123)
        self.guide.request_scan = Mock()
        self.guide.tick()

    def test_table_status_colours_survive_theme_switch(self):
        self.guide.entries = [SaveEntry('SAVEFILE01', 'Current', 'Suburbs', status='current'),
                              SaveEntry('SAVEFILE02', 'Other', 'Hotel', status='other'),
                              SaveEntry('SAVEFILE03', 'Unknown', 'Slums'),
                              SaveEntry('SAVEFILE04', 'Compatible', 'Suburbs', status='compatible'),
                              SaveEntry('SAVEFILE05', 'Incompatible', 'Hospital', status='incompatible')]
        self.guide.show()
        for mode in ('light', 'dark'):
            self.app.appearance.choice.set(mode.title()); self.app.appearance.apply()
            for slot, tag, colour in [('SAVEFILE01', 'confirmed', 'complete'),
                                     ('SAVEFILE02', 'locked', 'locked'), ('SAVEFILE03', 'waiting', 'available'),
                                     ('SAVEFILE04', 'confirmed', 'complete'), ('SAVEFILE05', 'locked', 'locked')]:
                self.assertEqual(self.guide.table.item(slot, 'tags'), (tag,))
                self.assertEqual(self.guide.table.tag_configure(tag)['foreground'], PALETTES[mode][colour])

    def test_short_f9_press_toggles_once_and_only_in_foreground(self):
        # Low bit reports a tap between polls; held high bit must not flicker.
        self.api.focused_rect.return_value = (0, 0, 1920, 1080, 1)
        self.api.user.GetAsyncKeyState.return_value = 0x8001
        self.guide.tick(); self.assertTrue(self.guide.enabled.get())
        self.api.user.GetAsyncKeyState.return_value = 0x8000
        self.guide.tick(); self.assertTrue(self.guide.enabled.get())
        self.api.user.GetAsyncKeyState.return_value = 0
        self.guide.tick()
        self.api.user.GetAsyncKeyState.return_value = 1
        self.guide.tick(); self.assertFalse(self.guide.enabled.get())
        self.api.focused_rect.return_value = None
        self.guide.tick(); self.assertFalse(self.guide.enabled.get())

    def test_run_change_clears_old_green_labels_and_overlay_reuses_widgets(self):
        self.guide.entries = [SaveEntry('SAVEFILE01', 'My save', 'Suburbs', status='current')]
        self.guide.enabled.set(True)
        self.api.focused_rect.return_value = (0, 0, 1920, 1080, 1)
        self.guide.tick()
        labels = tuple(self.guide.labels)
        self.guide.message = 'Updated snapshot'
        self.guide.tick(); self.assertEqual(tuple(self.guide.labels), labels)
        self.app.run_name = 'new-run'
        self.guide.tick(); self.assertFalse(self.guide.entries)
        self.assertIsNone(self.guide.identity)


if __name__ == '__main__': unittest.main()
