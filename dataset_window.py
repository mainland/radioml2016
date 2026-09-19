"""Extract normalized RadioML windows from post-channel transmissions."""
from __future__ import print_function

import numpy as np


def normalized_complex_window_with_divisor(transmission, offset, length):
    """Select one complex window and return its L1 normalization divisor.

    Args:
        transmission: One-dimensional post-channel complex samples.
        offset: Zero-based sample index into ``transmission``.
        length: Number of consecutive samples to select.

    Returns:
        A pair containing a complex64 window whose L1 magnitude sum is one and
        the float32 divisor applied to the raw window.

    Raises:
        ValueError: If the requested interval is invalid or has zero energy.
    """
    samples = np.asarray(transmission)
    if samples.ndim != 1:
        raise ValueError('transmission must be one-dimensional')
    if offset < 0 or length < 1 or offset + length > samples.size:
        raise ValueError('window interval is outside the transmission')
    window = samples[offset:offset + length]
    divisor = np.float32(np.sum(np.abs(window)))
    if not np.isfinite(divisor) or divisor <= 0:
        raise ValueError('window must have finite, nonzero energy')
    normalized = np.asarray(window / divisor, dtype=np.complex64)
    return normalized, divisor


def normalized_complex_window(transmission, offset, length):
    """Select one complex window and normalize its L1 magnitude sum to one."""
    return normalized_complex_window_with_divisor(
        transmission, offset, length)[0]
