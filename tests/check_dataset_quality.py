"""Check exact duplicate counting without confusing keys or ancestry."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              'scripts'))
from audit_dataset_quality import count_duplicate_windows


def test_duplicate_counts_respect_keys_and_preserve_ancestry():
    """Count extra copies, excluding equal samples under different labels."""
    iq = np.ones((6, 2, 128), dtype=np.float32)
    iq[5, 1, -1] = np.nextafter(np.float32(1), np.float32(2))
    counts, example = count_duplicate_windows(
        iq, np.array([0, 0, 0, 0, 1, 0]), np.array([0, 0, 0, 2, 0, 0]),
        np.arange(11, 17), np.full(6, 7), ['BPSK', 'QPSK'])
    assert counts == {'BPSK': 2, 'QPSK': 0}
    assert example == {
        'modulation': 'BPSK', 'snr': 0, 'rows': [0, 1, 2],
        'transmissions': [11, 12, 13], 'offsets': [7, 7, 7],
    }


def test_duplicate_count_requires_identical_bits():
    """Numerically equal signed zeros are different stored representations."""
    iq = np.zeros((2, 2, 128), dtype=np.float32)
    iq[1, 1, -1] = np.float32(-0.0)
    counts, example = count_duplicate_windows(
        iq, np.zeros(2, dtype=int), np.zeros(2, dtype=int),
        np.arange(2), np.zeros(2, dtype=int), ['BPSK'])
    assert counts == {'BPSK': 0}
    assert example is None


def test_duplicate_count_rejects_misaligned_metadata():
    """A missing transmission ID must not produce a misleading example."""
    with pytest.raises(ValueError):
        count_duplicate_windows(
            np.zeros((2, 2, 128), dtype=np.float32), np.zeros(2, dtype=int),
            np.zeros(2, dtype=int), np.arange(1), np.zeros(2, dtype=int),
            ['BPSK'])
