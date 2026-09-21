"""Define historical, slope-corrected, and calibrated SNR policies."""
from __future__ import print_function

import math

import numpy as np


SNR_MODES = ('historical', 'scaled', 'calibrated')


def nominal_noise_amplitude(label_db, mode):
    """Return the uncalibrated complex-noise amplitude for an SNR label.

    Args:
        label_db: Requested SNR label in decibels.
        mode: Either ``historical`` or ``scaled``.

    Returns:
        The requested RMS amplitude of the complex Gaussian noise source.

    Raises:
        ValueError: If mode does not define an uncalibrated amplitude.
    """
    if mode == 'historical':
        return 10.0 ** (-label_db / 10.0)
    if mode == 'scaled':
        return 10.0 ** (-label_db / 20.0)
    raise ValueError('nominal noise amplitude is undefined for mode %r' % mode)


def _selected_power(samples, offsets, length):
    """Measure mean complex-sample power over disjoint selected windows."""
    samples = np.asarray(samples)
    if samples.ndim != 1 or length < 1 or not offsets:
        raise ValueError('power measurement requires samples and windows')
    total = 0.0
    count = 0
    for offset in offsets:
        if offset < 0 or offset + length > samples.size:
            raise ValueError('measurement window is outside the transmission')
        window = np.asarray(
            samples[offset:offset + length], dtype=np.complex128)
        total += float(np.vdot(window, window).real)
        count += length
    power = total / count
    if not np.isfinite(power) or power < 0:
        raise ValueError('measured power must be finite and nonnegative')
    return power


def measure_snr(clean, noisy, offsets, length):
    """Measure aggregate signal and residual-noise power over selected windows.

    Args:
        clean: Post-impairment waveform with zero additive noise.
        noisy: Matching waveform with additive noise.
        offsets: Zero-based window offsets shared by both waveforms.
        length: Window length in samples.

    Returns:
        A mapping containing signal power, noise power, and SNR in decibels.

    Raises:
        ValueError: If the waveforms cannot define a finite positive SNR.
    """
    clean = np.asarray(clean)
    noisy = np.asarray(noisy)
    if clean.shape != noisy.shape:
        raise ValueError('clean and noisy transmissions must have equal shape')
    signal_power = _selected_power(clean, offsets, length)
    noise_power = _selected_power(noisy - clean, offsets, length)
    if signal_power <= 0 or noise_power <= 0:
        raise ValueError('SNR measurement requires positive signal and noise')
    return {
        'signal_power': signal_power,
        'noise_power': noise_power,
        'snr_db': 10.0 * math.log10(signal_power / noise_power),
    }


def calibrated_noise_amplitude(label_db, clean, unit_noisy, offsets, length):
    """Calibrate noise amplitude against actual selected signal samples.

    ``unit_noisy`` must use the same channel input and seed as ``clean`` with a
    requested noise amplitude of one. The calculation uses float64 power sums.

    Args:
        label_db: Target aggregate SNR in decibels.
        clean: Post-impairment waveform with zero additive noise.
        unit_noisy: Matching waveform with unit-amplitude additive noise.
        offsets: Zero-based output-window offsets used for calibration.
        length: Window length in samples.

    Returns:
        The complex-noise RMS amplitude that targets the requested SNR.

    Raises:
        ValueError: If signal or unit-noise power is not positive and finite.
    """
    measurement = measure_snr(clean, unit_noisy, offsets, length)
    target_ratio = 10.0 ** (label_db / 10.0)
    amplitude = math.sqrt(
        measurement['signal_power'] /
        (measurement['noise_power'] * target_ratio))
    if not np.isfinite(amplitude) or amplitude <= 0:
        raise ValueError('calibrated noise amplitude must be positive and finite')
    return amplitude
