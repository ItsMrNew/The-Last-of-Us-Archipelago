from array import array
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import test_airhorn
from tlou_ap.notifications import ToastQueue
from tlou_ap.overlay import NotificationOverlay
from tlou_ap.sound import HornPlayer, scaled_wav


def wav(path, amplitude=1000, seconds=.1):
    samples = array('h', [amplitude, -amplitude] * round(8000 * seconds / 2))
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        stream.writeframes(samples.tobytes())


class HornSoundTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.files = [self.root / f'horn-{i}.wav' for i in range(5)]
        for i, path in enumerate(self.files):
            wav(path, (i + 1) * 1000)
        (self.root / 'manifest.json').write_text(json.dumps({
            'recordings': [{'file': p.name} for p in self.files]}))
        self.fallback = self.root / 'fallback.wav'
        wav(self.fallback, 9000)
        self.player = HornPlayer(self.root, self.fallback, rng=random.Random(42))
        self.addCleanup(self.player.close)
        self.played = []
        def play(path, flags):
            if path is None:
                self.played.append(None)
                return
            with wave.open(path, 'rb') as stream:
                self.played.append((path, max(array('h', stream.readframes(stream.getnframes())))))
        fake = SimpleNamespace(PlaySound=play, SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4)
        patcher = patch.dict('sys.modules', winsound=fake)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_every_bag_uses_all_five_and_never_repeats_across_boundaries(self):
        selected = [self.player.play(50) for _ in range(100)]
        self.assertTrue(all(a != b for a, b in zip(selected, selected[1:])))
        for start in range(0, 100, 5):
            self.assertEqual(set(selected[start:start+5]), set(self.files))
        self.assertGreater(len({tuple(selected[i:i+5]) for i in range(0,100,5)}), 1)
        self.assertEqual({sample[1] for sample in self.played}, {500,1000,1500,2000,2500})
        self.assertEqual(len({sample[0] for sample in self.played}), 5)

    def test_mute_does_not_spend_sound_choice_or_change_last(self):
        self.player.play(50)
        before = self.player.last, list(self.player.remaining)
        self.assertIsNone(self.player.play(0))
        self.assertEqual((self.player.last, self.player.remaining), before)
        self.assertIsNone(self.played[-1])
        for volume in (-1,101,True,1.5):
            with self.assertRaises(ValueError): self.player.play(volume)

    def test_missing_bank_uses_original_and_new_files_are_detected(self):
        originals = {path:path.read_bytes() for path in self.files}
        for path in self.files: path.unlink()
        self.assertEqual(self.player.play(), self.fallback)
        for path,payload in originals.items(): path.write_bytes(payload)
        self.assertEqual({self.player.play() for _ in range(5)}, set(self.files))

    def test_bad_or_long_recordings_do_not_stop_playback(self):
        for path in self.files: path.write_bytes(b'bad wav')
        wav(self.files[0], seconds=5.1)
        with self.assertLogs('tlou-ap', level='WARNING'):
            self.assertEqual(self.player.play(), self.fallback)
        self.assertEqual(len(self.played), 1)

    def test_audio_device_failure_does_not_escape_into_client(self):
        with patch('winsound.PlaySound', side_effect=RuntimeError('Device unavailable')):
            with self.assertLogs('tlou-ap', level='WARNING'):
                self.assertIsNone(self.player.play())

    def test_cache_uses_recording_content_and_volume(self):
        for path in self.files[1:]: path.unlink()
        original = self.files[0].read_bytes()
        self.player.play(50); self.player.play(100)
        self.assertEqual([p[1] for p in self.played], [500,1000])
        self.assertEqual(self.files[0].read_bytes(), original)
        wav(self.files[0], 7000)
        self.player.play(50)
        self.assertEqual(self.played[-1][1],3500)
        self.assertEqual(len({p[0] for p in self.played}),3)

    def test_path_outside_manifest_directory_is_rejected(self):
        (self.root/'manifest.json').write_text(json.dumps({'recordings':[{'file':'../outside.wav'}]}))
        with self.assertLogs('tlou-ap', level='WARNING'):
            self.assertEqual(self.player.play(),self.fallback)

    def test_truncated_wav_does_not_create_a_cached_output(self):
        path = self.files[0]
        path.write_bytes(path.read_bytes()[:-20])
        target = self.root/'scaled.wav'
        with self.assertRaises(ValueError): scaled_wav(path,target,50)
        self.assertFalse(target.exists())

    def test_timed_and_single_traps_rotate_via_overlay_only_after_confirmed_pulses(self):
        overlay = NotificationOverlay.__new__(NotificationOverlay)
        overlay.queue = ToastQueue()
        with patch('tlou_ap.sound._player', self.player):
            for count in (1,3):
                before = len(self.played)
                horn, _, adapter, _ = test_airhorn.AirhornTests.setup(self,self.root/f'run{count}',count=count)
                horn.notify = overlay.add
                adapter.ready = False
                for _ in range(20): horn.poll(adapter)
                self.assertEqual(len(self.played),before)
                adapter.ready = True
                for clock in range(0, count*30000+1, 500):
                    adapter.clock = clock
                    horn.poll(adapter)
                    if clock == 15000:
                        n = len(self.played)
                        adapter.ready = False
                        for _ in range(20): horn.poll(adapter)
                        self.assertEqual(len(self.played), n)
                        adapter.ready = True
                self.assertEqual(horn.queued,0)
                self.assertEqual(len(self.played)-before,count*6)
                sounds = [p[0] for p in self.played[before:]]
                self.assertTrue(all(a != b for a,b in zip(sounds,sounds[1:])))
            # The bag continues across traps, so a new trap can start mid-bag.
            for start in range(0,20,5):
                self.assertEqual(len({p[0] for p in self.played[start:start+5]}),5)
            before = len(self.played)
            horn, session, adapter, _ = test_airhorn.AirhornTests.setup(self,self.root/'single',timed=False,count=1)
            horn.notify = overlay.add
            adapter.result = 'not_applied'; horn.poll(adapter)
            self.assertEqual(len(self.played),before)
            adapter.result = 'applied'; horn.poll(adapter)
            horn.bind(session); horn.poll(adapter)
            self.assertEqual(len(self.played)-before,1)


if __name__ == '__main__': unittest.main()
