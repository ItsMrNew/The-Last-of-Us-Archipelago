"""Create original, short horn audio; no game or third-party sound assets."""
import math
from pathlib import Path
import struct
import wave

path = Path(__file__).resolve().parents[1] / 'tlou_ap/data/airhorn.wav'
rate, seconds = 22050, .55
samples = bytearray()
for i in range(round(rate * seconds)):
    t = i / rate
    envelope = min(1, t / .018, (seconds - t) / .07)
    value = sum(math.sin(2 * math.pi * frequency * harmonic * t) / harmonic
                for frequency in (220, 277.18) for harmonic in (1, 2, 3, 4, 5))
    samples.extend(struct.pack('<h', round(32767 * .105 * envelope * value)))
with wave.open(str(path), 'wb') as out:
    out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
    out.writeframes(samples)
print(path)
