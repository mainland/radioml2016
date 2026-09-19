#!/usr/bin/env python2.7
"""Measure exact window duplication and shared ancestry in attributed HDF5."""
from __future__ import print_function

import argparse
import hashlib
import json
import os

import h5py
import numpy as np


def file_sha256(path):
    """Return a file's SHA-256 without loading it into memory."""
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def count_duplicate_windows(iq, modulation, snr, numbers, offsets, names):
    """Count excess bit-identical windows within each modulation/SNR key.

    Args:
        iq: Float32 I/Q array with shape ``(N, 2, 128)``.
        modulation: Length-N modulation IDs indexing ``names``.
        snr: Length-N requested SNR labels.
        numbers: Length-N file-local transmission IDs.
        offsets: Length-N post-channel sample offsets.
        names: Modulation vocabulary in ID order.

    Returns:
        Counts by modulation and one duplicate group, or None when absent.
        A group of k identical windows contributes k-1 to the count.

    Raises:
        ValueError: If the arrays have incompatible shapes or modulation IDs.
    """
    if iq.ndim != 3 or iq.shape[1:] != (2, 128) or iq.dtype != np.float32:
        raise ValueError('expected float32 I/Q with shape (N, 2, 128)')
    if any(values.shape != (len(iq),)
           for values in (modulation, snr, numbers, offsets)):
        raise ValueError('window attributes must align with I/Q rows')
    if np.any(modulation < 0) or np.any(modulation >= len(names)):
        raise ValueError('modulation ID is outside the vocabulary')
    counts_by_modulation = {}
    example = None
    for identifier, name in enumerate(names):
        excess = 0
        for label in np.unique(snr[modulation == identifier]):
            rows = np.where((modulation == identifier) & (snr == label))[0]
            batch = np.ascontiguousarray(iq[rows])
            # Compare complete stored rows, without rounding, gain fitting,
            # or treating distinct signed-zero representations as equal.
            packed = batch.reshape((len(rows), -1)).view(
                np.dtype((np.void, batch[0].nbytes))).ravel()
            _, inverse, counts = np.unique(
                packed, return_inverse=True, return_counts=True)
            excess += int(np.sum(counts - 1))
            if example is None and np.any(counts > 1):
                group = np.where(counts > 1)[0][0]
                repeated = rows[inverse == group]
                example = {
                    'modulation': name, 'snr': int(label),
                    'rows': repeated.tolist(),
                    'transmissions': numbers[repeated].tolist(),
                    'offsets': offsets[repeated].tolist(),
                }
        counts_by_modulation[name] = excess
    return counts_by_modulation, example


def audit_file(path):
    """Return duplication, ancestry, and stored SNR summaries for one artifact.

    Args:
        path: Attributed HDF5 file to read without modification.

    Returns:
        JSON-compatible measurements and the input's complete-file SHA-256.
        SNR summaries are None when required stored measurements are absent.

    Raises:
        ValueError: If the file has an unsupported schema or invalid I/Q shape.
    """
    with h5py.File(path, 'r') as source:
        if (source.attrs.get('schema') != 'radioml2016-attributed' or
                source.attrs.get('schema_version') != 1):
            raise ValueError('unsupported attributed HDF5 schema')
        names = json.loads(source.attrs['modulation_names_json'])
        windows = source['windows']
        transmissions = source['transmissions']
        modulation = windows['modulation_id'][:]
        snr = windows['snr_db'][:]
        duplicates, example = count_duplicate_windows(
            windows['iq'][:], modulation, snr,
            windows['transmission_number'][:], windows['offset'][:], names)
        valid = windows['snr_measurement_valid'][:].astype(bool)
        measured = windows['measured_snr_db'][:]
        medians = {}
        for identifier, name in enumerate(names):
            selected = (modulation == identifier) & (snr == 18) & valid
            medians[name] = (float(np.median(measured[selected]))
                             if np.any(selected) else None)
        valid_transmissions = transmissions[
            'snr_measurement_valid'][:].astype(bool)
        errors = np.abs(
            transmissions['measured_snr_db'][:][valid_transmissions] -
            transmissions['snr_db'][:][valid_transmissions])
        analog = transmissions['analog_source_valid'][:].astype(bool)
        report = {
            'file': os.path.basename(path),
            'sha256': file_sha256(path),
            'transmissions': len(transmissions['channel_seed']),
            'unique_channel_seeds': np.unique(
                transmissions['channel_seed'][:]).tolist(),
            'unique_analog_segments': int(np.unique(
                transmissions['analog_source_offset'][:][analog]).size),
            'duplicate_windows': duplicates,
            'duplicate_example': example,
            'label_18_measured_snr_median_db': medians,
            'max_transmission_label_error_db': (
                float(np.max(errors)) if errors.size else None),
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', nargs='+', help='attributed HDF5 inputs')
    parser.add_argument('--output', required=True, help='new JSON report path')
    args = parser.parse_args()
    if os.path.exists(args.output):
        parser.error('refusing to overwrite ' + args.output)
    report = {
        'schema': 'radioml2016-quality-audit',
        'schema_version': 1,
        'scope': ('Exact duplication within each modulation/SNR key, shared '
                  'ancestry, and stored paired SNR measurements. This does '
                  'not test near-duplicates or statistical independence.'),
        'script_sha256': file_sha256(__file__),
        'numpy_version': np.__version__,
        'h5py_version': h5py.__version__,
        'artifacts': [audit_file(path) for path in sorted(args.artifacts)],
    }
    descriptor = os.open(
        args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    with os.fdopen(descriptor, 'w') as destination:
        json.dump(report, destination, sort_keys=True, indent=2,
                  allow_nan=False)
        destination.write('\n')
    print('Wrote ' + args.output)


if __name__ == '__main__':
    main()
