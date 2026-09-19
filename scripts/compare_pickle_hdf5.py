#!/usr/bin/env python2.7
"""Compare a trusted RadioML pickle with an attributed HDF5 artifact.

The comparison requires exact float32 I/Q equality. It also verifies that the
HDF5 modulation and SNR arrays align with the pickle's ``(modulation, SNR)``
batches. Only load a pickle from a trusted source.
"""
from __future__ import print_function

import argparse
import cPickle
import json
import os
import sys

import h5py
import numpy as np


SCHEMA = 'radioml2016-attributed'
SCHEMA_VERSION = 1


class ComparisonError(ValueError):
    """Report a structural or sample mismatch between the two artifacts."""


def _load_pickle(path):
    """Load and validate the pickle-compatible dataset mapping.

    Args:
        path: Path to a trusted RadioML pickle.

    Returns:
        The nonempty ``(modulation, SNR)`` to I/Q batch mapping.

    Raises:
        ComparisonError: The pickle does not contain the expected mapping.
    """
    with open(path, 'rb') as source:
        dataset = cPickle.load(source)
    if not isinstance(dataset, dict) or not dataset:
        raise ComparisonError('pickle must contain a nonempty dictionary')
    for key, batch in dataset.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise ComparisonError('invalid pickle key: %r' % (key,))
        if (not isinstance(batch, np.ndarray) or batch.ndim != 3 or
                batch.shape[0] < 1 or batch.shape[1:] != (2, 128) or
                batch.dtype != np.float32 or not np.isfinite(batch).all()):
            raise ComparisonError(
                'invalid or nonfinite pickle batch for %r: shape=%r dtype=%r' %
                (key, getattr(batch, 'shape', None),
                 getattr(batch, 'dtype', None)))
    return dataset


def compare_artifacts(pickle_path, hdf5_path):
    """Require exact per-key I/Q and label equality across two artifacts.

    Args:
        pickle_path: Path to a trusted RadioML compatibility pickle.
        hdf5_path: Path to an attributed RadioML HDF5 file.

    Returns:
        A JSON-serializable comparison summary.

    Raises:
        ComparisonError: A schema, label, shape, dtype, or sample differs.
    """
    dataset = _load_pickle(pickle_path)
    with h5py.File(hdf5_path, 'r') as source:
        if source.attrs.get('schema') != SCHEMA:
            raise ComparisonError('unexpected HDF5 schema: %r' %
                                  source.attrs.get('schema'))
        try:
            schema_version = int(source.attrs['schema_version'])
            labels = json.loads(source.attrs['modulation_names_json'])
            iq = source['windows/iq']
            modulation_ids = source['windows/modulation_id']
            snr_db = source['windows/snr_db']
        except (KeyError, TypeError, ValueError) as error:
            raise ComparisonError('invalid HDF5 metadata: %s' % error)
        if schema_version != SCHEMA_VERSION:
            raise ComparisonError(
                'unsupported HDF5 schema version: %r' % schema_version)
        if not isinstance(labels, list) or len(set(labels)) != len(labels):
            raise ComparisonError('invalid HDF5 modulation vocabulary')
        if iq.ndim != 3 or iq.shape[1:] != (2, 128):
            raise ComparisonError('invalid HDF5 I/Q shape: %r' % (iq.shape,))
        if iq.dtype != np.float32:
            raise ComparisonError('invalid HDF5 I/Q dtype: %r' % iq.dtype)
        if modulation_ids.shape != (iq.shape[0],):
            raise ComparisonError('HDF5 modulation IDs do not align with I/Q')
        if modulation_ids.dtype != np.int16:
            raise ComparisonError('invalid HDF5 modulation dtype: %r' %
                                  modulation_ids.dtype)
        if snr_db.shape != (iq.shape[0],):
            raise ComparisonError('HDF5 SNR labels do not align with I/Q')
        if snr_db.dtype != np.int16:
            raise ComparisonError('invalid HDF5 SNR dtype: %r' % snr_db.dtype)

        label_ids = dict((label, number)
                         for number, label in enumerate(labels))
        unknown = sorted(set(key[0] for key in dataset) - set(labels))
        if unknown:
            raise ComparisonError('pickle modulations absent from HDF5: %r' %
                                  unknown)
        snrs = sorted(set(key[1] for key in dataset))
        ordered_keys = [(label, snr) for snr in snrs for label in labels
                        if (label, snr) in dataset]
        if len(ordered_keys) != len(dataset):
            raise ComparisonError('pickle contains unsupported keys')

        position = 0
        for key in ordered_keys:
            label, snr = key
            batch = dataset[key]
            count = int(batch.shape[0])
            selection = slice(position, position + count)
            if position + count > iq.shape[0]:
                raise ComparisonError('HDF5 ends within pickle batch %r' %
                                      (key,))
            if not np.array_equal(iq[selection], batch):
                raise ComparisonError('I/Q mismatch for pickle batch %r' %
                                      (key,))
            if not np.all(modulation_ids[selection] == label_ids[label]):
                raise ComparisonError('modulation mismatch for pickle batch %r' %
                                      (key,))
            if not np.all(snr_db[selection] == snr):
                raise ComparisonError('SNR mismatch for pickle batch %r' %
                                      (key,))
            position += count
        if position != iq.shape[0]:
            raise ComparisonError(
                'HDF5 has %d windows, but the pickle has %d' %
                (iq.shape[0], position))

        return {
            'equal': True,
            'hdf5_path': os.path.realpath(hdf5_path),
            'key_count': len(ordered_keys),
            'pickle_path': os.path.realpath(pickle_path),
            'schema': source.attrs['schema'],
            'schema_version': schema_version,
            'window_count': position,
            'window_dtype': str(iq.dtype),
            'window_shape': list(iq.shape),
        }


def main():
    """Parse command-line paths and print the comparison summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pickle', help='trusted RadioML compatibility pickle')
    parser.add_argument('hdf5', help='attributed RadioML HDF5 artifact')
    args = parser.parse_args()
    try:
        report = compare_artifacts(args.pickle, args.hdf5)
    except (ComparisonError, IOError, OSError) as error:
        print('comparison failed: %s' % error, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
