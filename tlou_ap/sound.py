"""Rotate horn recordings without changing native trap timing or enemy hearing."""
import hashlib
import json
import logging
from pathlib import Path
from array import array
import random
import tempfile
import wave

DATA = Path(__file__).with_name('data')
LOG = logging.getLogger('tlou-ap')


class HornPlayer:
    """A shuffled bag: use every available recording before starting another bag."""

    def __init__(self, directory=DATA / 'airhorns', fallback=DATA / 'airhorn.wav', *, rng=None):
        self.directory, self.fallback = Path(directory), Path(fallback)
        self.rng = rng or random.Random()
        self.pool, self.remaining, self.last = (), [], None
        self.cache = None
        self.warned = set()

    def warning(self, path, error):
        key = str(path), str(error)
        if key not in self.warned:
            self.warned.add(key)
            LOG.warning('Airhorn recording unavailable (%s): %s', path, error)

    def recordings(self):
        manifest = self.directory / 'manifest.json'
        try:
            entries = json.loads(manifest.read_text(encoding='utf-8'))['recordings']
            paths = []
            for entry in entries:
                name = entry['file']
                if not isinstance(name, str) or Path(name).name != name or not name.endswith('.wav'):
                    raise ValueError('Invalid horn filename')
                path = self.directory / name
                if path.is_file() and path not in paths:
                    paths.append(path)
            return tuple(paths)
        except FileNotFoundError:
            return ()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.warning(manifest, error)
            return ()

    def choose(self, paths):
        if paths != self.pool:
            self.pool, self.remaining = paths, []
        if not self.remaining:
            self.remaining = list(paths)
            self.rng.shuffle(self.remaining)
            # The next pop must differ from the final sound in the previous bag.
            if len(self.remaining) > 1 and self.remaining[-1] == self.last:
                self.remaining[0], self.remaining[-1] = self.remaining[-1], self.remaining[0]
        return self.remaining.pop()

    def play(self, volume=100):
        if type(volume) is not int or not 0 <= volume <= 100:
            raise ValueError('Volume must be 0–100')
        try:
            import winsound
            if volume == 0:
                winsound.PlaySound(None, 0)
                return None  # Muting must not spend a choice from the sound pool.
            paths = self.recordings() or (self.fallback,)
            while paths:
                source = self.choose(paths)
                try:
                    if self.cache is None:
                        self.cache = tempfile.TemporaryDirectory(prefix='tlou-airhorn-audio-')
                    # Include the recording bytes so different sounds/updated files
                    # never reuse a cached WAV for the previous sound at this volume.
                    digest = hashlib.sha256(source.read_bytes()).hexdigest()
                    target = Path(self.cache.name) / f'{digest}-{volume}.wav'
                    if not target.exists():
                        scaled_wav(source, target, volume)
                    winsound.PlaySound(str(target),
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                    self.last = source
                    LOG.debug('Airhorn recording: %s', source.name)
                    return source
                except (OSError, ValueError, RuntimeError, EOFError, wave.Error) as error:
                    self.warning(source, error)
                    paths = tuple(p for p in paths if p != source)
                    if not paths and source != self.fallback:
                        paths = (self.fallback,)
        except (ImportError, OSError, RuntimeError) as error:
            self.warning('audio output', error)
        return None

    def close(self):
        if self.cache is not None:
            self.cache.cleanup()
            self.cache = None


def scaled_wav(source, target, volume):
    """Scale PCM samples; never change the Windows/game mixer."""
    if type(volume) is not int or not 0 <= volume <= 100:
        raise ValueError('Volume must be 0–100')
    with wave.open(str(source), 'rb') as stream:
        params = stream.getparams()
        if params.sampwidth != 2 or params.comptype != 'NONE':
            raise ValueError('Airhorn must be 16-bit PCM')
        if params.nchannels not in (1, 2) or not 8000 <= params.framerate <= 96000:
            raise ValueError('Airhorn must be mono/stereo PCM at 8–96 kHz')
        if not 0 < params.nframes / params.framerate <= 4.5:
            raise ValueError('Airhorn must be 0–4.5 seconds to fit the five-second blast interval')
        samples = array('h', stream.readframes(params.nframes))
        if len(samples) != params.nframes * params.nchannels:
            raise ValueError('Truncated Airhorn recording')
    samples = array('h', (round(value * volume / 100) for value in samples))
    with wave.open(str(target), 'wb') as stream:
        stream.setparams(params)
        stream.writeframes(samples.tobytes())


_player = HornPlayer()


def play_airhorn(volume=100):
    return _player.play(volume)
