# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Two checks every envelope capture should pass, and one of them REFUSES.

1. THE A-PRIORI PITCH CHECK.  A played note's pitch is fixed by its note number
   before anything is measured, so one FFT validates sample rate, wav header,
   analysis scaling and tuning against a value nobody measured.  Every other
   check compares one measurement to another, where a common-mode error in the
   analysis is invisible to all of them.  s3ked's hardcoded 44100 against a
   48000 rig survived nine eliminations and five write-ups and was caught by the
   probe note's own frequency, sitting in the same file the whole time.  Here it
   caught a preset tuned an octave below its note numbers, which nobody was
   looking for.

2. THE CARRIER-CYCLE CHECK, WHICH REFUSES.  An envelope detector's window must
   span a fixed number of CARRIER CYCLES, not a fixed number of milliseconds.
   Below about one cycle the carrier leaks into the RMS envelope and its peaks
   cross a -3 dB threshold early -- so a ladder across notes, which changes the
   carrier period at every rung, acquires a note-dependent timing bias that is
   indistinguishable from a real note-effect.

   Measured on a SYNTHETIC PURE TONE with no modulation of any kind, so this is
   a property of the detector and not of any material:

       cycles/window   0.05   0.10   0.165   0.25   0.33   0.41   0.50   1.0   5.2
       swing (dB)     21.20  14.81  10.34    6.64   3.93   1.87   0.04  0.01  0.00

   A low PURE TONE is fully exposed -- 8.3 dB of swing at 41 Hz.  Purity is not
   what protects a subject; pitch is.  "Use a clean tone" is the wrong lesson.

WHY THIS REFUSES RATHER THAN REPORTS
====================================
s3ked, having read this project's table: "Mine would have read 0.165 and I would
still have taken the measurement, because nothing told me what the number
meant."  A recorded number with no verdict attached is a number that gets
recorded and ignored.  So `--strict` exits non-zero, and the threshold carries
the swing it implies rather than being a bare constant.
"""
from __future__ import annotations

import argparse
import math
import sys
import wave

import numpy as np

#: THE VERDICT IS MEASURED, NOT INFERRED FROM THE CYCLE COUNT.
#:
#: A first version of this tool thresholded on cycles-per-window (REFUSE below
#: 0.41). s3ked reproduced the curve independently and showed that cannot work:
#: the swing collapses to nothing at QUARTER-CYCLE ratios, because an RMS window
#: spanning a whole number of half-periods averages a sine exactly, and spikes
#: between them --
#:
#:   cycles/window  0.25  0.33  0.41  0.50  0.60  0.66  0.75  1.00
#:   swing (dB)     0.04  3.91  1.83  0.00  1.22  1.79  0.04  0.00
#:
#: So cleanliness is a property of the FRACTIONAL PART, and a cut on the count
#: ranks 0.41 (1.83 dB) as worse than 0.66 (1.79 dB) when 0.66 is the worse
#: ratio. The count is worth RECORDING and is the wrong thing to DECIDE on.
#:
#: Synthesising a tone at the measured f0 and running the actual window over it
#: costs three lines, needs no table, and stays correct when someone changes the
#: smoothing width. The two thresholds below are on the SWING, which is what the
#: -3 dB detector actually has to survive.
REFUSE_SWING_DB = 3.0
WARN_SWING_DB = 1.0
#: Whole cycles with margin is the design rule -- not "enough", and not "more
#: than half", which is what a coarse table leads you to write.


def equal_tempered(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def carrier_hz(path: str, t0: float, t1: float, floor_hz: float = 8.0):
    """Dominant partial in [t0, t1), with parabolic interpolation on the bin.

    `floor_hz` is deliberately low: a preset tuned an octave down puts its
    fundamental below a naive 20 Hz floor, and the peak then found is a
    HARMONIC -- which reads as a clean measurement of the wrong thing.
    """
    with wave.open(path, "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    x = raw.reshape(-1, ch).astype(float).mean(axis=1) / 32768.0
    seg = x[int(t0 * sr):int(t1 * sr)]
    if len(seg) < 4096:
        return None, sr
    seg = seg * np.hanning(len(seg))
    sp = np.abs(np.fft.rfft(seg))
    fr = np.fft.rfftfreq(len(seg), 1.0 / sr)
    lo = int(np.searchsorted(fr, floor_hz))
    k = lo + int(np.argmax(sp[lo:]))
    d = 0.0
    if 0 < k < len(sp) - 1:
        a, b, c = sp[k - 1], sp[k], sp[k + 1]
        den = a - 2 * b + c
        if den:
            d = 0.5 * (a - c) / den
    return float(fr[k] + d * (fr[1] - fr[0])), sr


def check(path, note, smoothing_ms, t0, t1, expect_octave=0):
    f, sr = carrier_hz(path, t0, t1)
    if f is None:
        return None
    expected = equal_tempered(note) * (2.0 ** expect_octave)
    harmonic = max(1, round(f / expected)) if expected > 0 else 1
    f0 = f / harmonic
    cents = 1200.0 * math.log2(f0 / expected) if expected > 0 else float("nan")
    cycles = f0 * smoothing_ms * 1e-3
    return dict(sr=sr, carrier_hz=f, f0_hz=f0, harmonic=harmonic,
                expected_hz=expected, cents=cents,
                cycles_per_smoothing_window=cycles)


def envelope_swing_db(f0, smoothing_ms, sr, seconds=4.0):
    """Swing a constant-amplitude tone at `f0` shows through this exact window.

    Synthetic and constant by construction, so whatever this returns is the
    DETECTOR's, not the material's.
    """
    t = np.arange(int(seconds * sr)) / sr
    x = np.sin(2 * np.pi * f0 * t)
    win = max(1, int(smoothing_ms * 1e-3 * sr))
    n = len(x) // win
    if n < 8:
        return float("nan")
    e = np.sqrt((x[:n * win].reshape(n, win) ** 2).mean(axis=1))
    return 20.0 * math.log10(float(e.max()) / max(float(e.min()), 1e-12))


def verdict(swing_db, cycles):
    tail = f"(swing measured on a synthetic tone at this f0 and window; {cycles:.3f} cycles/window)"
    if not swing_db == swing_db:                       # NaN
        return "UNKNOWN", f"could not synthesise a long enough window {tail}"
    if swing_db > REFUSE_SWING_DB:
        return "REFUSE", (f"{swing_db:.2f} dB of envelope swing on a CONSTANT tone. A -3 dB "
                          f"threshold can be crossed early by that, so any time measured here "
                          f"is biased. Use many whole cycles per window {tail}")
    if swing_db > WARN_SWING_DB:
        return "WARN", f"{swing_db:.2f} dB of swing on a constant tone. Usable, not safe {tail}"
    return "OK", f"{swing_db:.2f} dB of swing {tail}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("wav")
    ap.add_argument("note", type=int, help="MIDI note number that was played")
    ap.add_argument("--smoothing-ms", type=float, default=5.0)
    ap.add_argument("--window", type=float, nargs=2, default=(1.0, 3.0), metavar=("T0", "T1"),
                    help="seconds into the file to analyse (default 1.0 3.0)")
    ap.add_argument("--octave", type=int, default=0,
                    help="expected tuning offset in octaves (this bench's organ presets are -1)")
    ap.add_argument("--cents-tolerance", type=float, default=50.0)
    ap.add_argument("--strict", action="store_true", help="exit non-zero on REFUSE or a pitch miss")
    a = ap.parse_args(argv)

    r = check(a.wav, a.note, a.smoothing_ms, a.window[0], a.window[1], a.octave)
    if r is None:
        print("  too little audio in the analysis window")
        return 2
    print(f"  sample rate (header)      {r['sr']} Hz")
    print(f"  carrier measured          {r['carrier_hz']:.2f} Hz  (harmonic x{r['harmonic']})")
    print(f"  fundamental               {r['f0_hz']:.2f} Hz")
    print(f"  expected from note {a.note:<3d}    {r['expected_hz']:.2f} Hz")
    print(f"  error                     {r['cents']:+.1f} cents")
    swing = envelope_swing_db(r["f0_hz"], a.smoothing_ms, r["sr"])
    v, why = verdict(swing, r["cycles_per_smoothing_window"])
    print(f"  cycles per {a.smoothing_ms:g} ms window  {r['cycles_per_smoothing_window']:.3f}")
    print(f"  envelope swing (synthetic) {swing:.2f} dB")
    print(f"  VERDICT                   {v} -- {why}")
    off = abs(r["cents"]) > a.cents_tolerance
    if off:
        print(f"  PITCH MISS: {r['cents']:+.1f} cents is outside +/-{a.cents_tolerance:g}. "
              f"Check sample rate, wav header, analysis scaling and the preset's tuning "
              f"BEFORE trusting any time measured from this file.")
    if a.strict and (v == "REFUSE" or off):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
