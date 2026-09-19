"""Extract normalized RadioML windows from post-channel transmissions."""
from __future__ import print_function

import numpy as np


def normalized_complex_window(transmission, offset, length):
    """Select and normalize one complex window.

    Args:
        transmission: One-dimensional post-channel complex samples.
        offset: Zero-based sample index into ``transmission``.
        length: Number of consecutive samples to select.

    Returns:
        A complex64 window whose L1 magnitude sum is one.

    Raises:
        ValueError: If the requested interval is invalid or has zero energy.
    """
    samples = np.asarray(transmission)
    if samples.ndim != 1:
        raise ValueError('transmission must be one-dimensional')
    if offset < 0 or length < 1 or offset + length > samples.size:
        raise ValueError('window interval is outside the transmission')
    window = samples[offset:offset + length]
    energy = np.sum(np.abs(window))
    if not np.isfinite(energy) or energy <= 0:
        raise ValueError('window must have finite, nonzero energy')
    return np.asarray(window / energy, dtype=np.complex64)
