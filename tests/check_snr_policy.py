#!/usr/bin/env python2.7
"""Validate historical, slope-corrected, and calibrated SNR policies."""
from __future__ import print_function

import math
import os

os.environ['GR_SCHEDULER'] = 'STS'

import numpy as np
import pytest

from dataset_channel import run_dynamic_channel
from snr_policy import (calibrated_noise_amplitude, measure_snr,
                        nominal_noise_amplitude)


def test_nominal_noise_amplitude_slopes():
    """Distinguish the historical two-for-one slope from amplitude scaling."""
    historical_ratio = (nominal_noise_amplitude(0, 'historical') /
                        nominal_noise_amplitude(10, 'historical'))
    scaled_ratio = (nominal_noise_amplitude(0, 'scaled') /
                    nominal_noise_amplitude(10, 'scaled'))
    assert abs(20.0 * math.log10(historical_ratio) - 20.0) < 1e-12
    assert abs(20.0 * math.log10(scaled_ratio) - 10.0) < 1e-12
    with pytest.raises(ValueError):
        nominal_noise_amplitude(0, 'calibrated')


def test_calibration_targets_actual_post_channel_signal_power():
    """Calibrate a carrier-bearing waveform over the exported windows."""
    count = 16384
    time = np.arange(count, dtype=np.float64)
    channel_input = (3.0 + .25 * np.exp(2j * np.pi * time / 37.0))
    channel_input = channel_input.astype(np.complex64)
    seed = 0x1337
    offsets = [2048, 4096, 8192, 12288]
    length = 128
    target_db = 7.0

    clean = run_dynamic_channel(channel_input, 0.0, seed)
    unit_noisy = run_dynamic_channel(channel_input, 1.0, seed)
    amplitude = calibrated_noise_amplitude(
        target_db, clean, unit_noisy, offsets, length)
    noisy = run_dynamic_channel(channel_input, amplitude, seed)
    measurement = measure_snr(clean, noisy, offsets, length)

    assert amplitude > 0
    assert abs(measurement['snr_db'] - target_db) < .001
    assert measurement['signal_power'] > 1.0
    assert np.array_equal(
        clean, run_dynamic_channel(channel_input, 0.0, seed))
    assert np.array_equal(
        noisy, run_dynamic_channel(channel_input, amplitude, seed))


def test_measure_snr_rejects_mismatched_runs():
    """Do not report a measurement for non-paired channel outputs."""
    clean = np.ones(256, dtype=np.complex64)
    with pytest.raises(ValueError):
        measure_snr(clean, clean[:-1], [0], 128)
