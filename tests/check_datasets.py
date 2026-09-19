#!/usr/bin/env python2.7
"""Regenerate the named datasets and check their recorded SHA-256 hashes.

Run inside Dockerfile.reproducible. The direct interface preserves all four
artifacts and their logs, while pytest uses a temporary output directory.
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import subprocess
import sys
from multiprocessing.pool import ThreadPool

import pytest


COMMON_ARGUMENTS = [
    '--seed', '201610', '--python-seed', '201610', '--numpy-seed', '201610',
    '--analog-source-seed', '201610', '--channel-seed', '0x1337',
    '--channel-seed-policy', 'restart',
    '--scheduler', 'sts', '--frames-per-key', '1000',
    '--snrs', '-20', '-18', '-16', '-14', '-12', '-10', '-8', '-6', '-4', '-2',
    '0', '2', '4', '6', '8', '10', '12', '14', '16', '18',
    '--modulations', 'BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64', 'GFSK',
    'CPFSK', 'WBFM', 'AM-DSB', 'AM-SSB',
]
CALIBRATED_ARGUMENTS = [
    '--fixed-am-ssb', '--fixed-wbfm', '--settled-windows',
    '--snr-mode', 'calibrated',
]
HDF5_ARGUMENTS = ['--output-format', 'hdf5', '--measure-snr']
PREFIX = 'RML2016.10a-Reproducible-'

# These are complete-file hashes, including HDF5 metadata. Update them only
# after reviewing a deliberate change to the documented dataset definition.
ARTIFACTS = (
    (PREFIX + 'Baseline.dat',
     ['--snr-mode', 'historical', '--output-format', 'pickle'],
     'af5d4a17ac2d1699e5e0c67198bacbdcc20caaa8988519bb33c6af5d208d8ec6'),
    (PREFIX + 'Baseline.h5',
     ['--snr-mode', 'historical'] + HDF5_ARGUMENTS,
     'f5ce285c62b5c099ce0f0bc89057ff17298313f0ceab9260bbd4d40d9bdc7eaa'),
    (PREFIX + 'Calibrated.h5', CALIBRATED_ARGUMENTS + HDF5_ARGUMENTS,
     'caeb06bdb9791d8f86df52922ae70297d33795d694813b7a98e6ac17445423c5'),
    (PREFIX + 'Calibrated-VariedAudio.h5',
     CALIBRATED_ARGUMENTS + ['--vary-analog-source'] + HDF5_ARGUMENTS,
     'df92c6ec10d9aab7dca7edb502ed156be893cb3e868b12154e8c4fab5eeffa64'),
)


def file_sha256(path):
    """Compute the SHA-256 of a file without loading it all into memory."""
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run_checks(output_dir):
    """Check full dataset hashes and compare Baseline I/Q.

    Args:
        output_dir: Directory for new artifacts, subprocess logs, and the report.

    Raises:
        ValueError: A destination artifact or log already exists.
        AssertionError: Generation, a reference hash, or I/Q comparison fails.
    """
    output_dir = os.path.abspath(output_dir)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    report_path = os.path.join(output_dir, 'datasets.json')
    destinations = [report_path]
    for filename, _, _ in ARTIFACTS:
        path = os.path.join(output_dir, filename)
        destinations.extend([path, path + '.log'])
    for path in destinations:
        if os.path.exists(path):
            raise ValueError('refusing to overwrite ' + path)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    def generate(artifact):
        filename, extra, expected = artifact
        path = os.path.join(output_dir, filename)
        arguments = COMMON_ARGUMENTS + extra
        print('Generating ' + filename)
        sys.stdout.flush()
        with open(path + '.log', 'wb') as log:
            status = subprocess.call(
                [sys.executable, 'generate_RML2016.10a.py'] + arguments +
                ['--output', path], cwd=repo, stdout=log,
                stderr=subprocess.STDOUT)
        assert status == 0, 'generation failed: see ' + path + '.log'
        actual = file_sha256(path)
        assert actual == expected, (
            '%s: expected SHA-256 %s, got %s' % (filename, expected, actual))
        print('%s  %s' % (actual, filename))
        sys.stdout.flush()
        return {
            'filename': filename,
            'arguments': arguments,
            'size_bytes': os.path.getsize(path),
            'sha256': actual,
        }

    # Each generator has its own process and RNG state. Run concurrently to
    # avoid serializing four full dataset generations.
    pool = ThreadPool(len(ARTIFACTS))
    try:
        artifacts = pool.map(generate, ARTIFACTS)
    finally:
        pool.close()
        pool.join()

    comparison = json.loads(subprocess.check_output([
        sys.executable, 'scripts/compare_pickle_hdf5.py',
        os.path.join(output_dir, PREFIX + 'Baseline.dat'),
        os.path.join(output_dir, PREFIX + 'Baseline.h5'),
    ], cwd=repo))
    assert comparison['equal']
    assert comparison['key_count'] == 220
    assert comparison['window_count'] == 220000
    with open(report_path, 'w') as destination:
        json.dump({'artifacts': artifacts, 'baseline_comparison': comparison},
                  destination, sort_keys=True, indent=2)
        destination.write('\n')
    print('All dataset hashes and Baseline I/Q match.')


@pytest.mark.slow
def test_dataset_hashes(tmpdir):
    """Require byte identity with the documented full datasets."""
    run_checks(str(tmpdir))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True,
                        help='directory for new artifacts and validation logs')
    args = parser.parse_args()
    run_checks(args.output)


if __name__ == '__main__':
    main()
