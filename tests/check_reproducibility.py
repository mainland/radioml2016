#!/usr/bin/env python2.7
"""Run in Dockerfile.reproducible: python2.7 tests/check_reproducibility.py --output /out."""
from __future__ import print_function

import argparse
import cPickle
import ctypes
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
from gnuradio import analog, blocks, gr


# Reference bytes for the January mapper under both channel seed policies.
# evidence/baseline.json records the advancing-policy mapper comparison.
COMPATIBILITY_PICKLE_SHA256 = (
    'a1dfcf6d9d5a5e574ad5538ce069a90c7b6b0b0348bc81b9910b640c6c2e928f')
ADVANCING_PICKLE_SHA256 = (
    'bf8183edabea8e3c608ec5cde7cfa6818187ce999d82dbb7ab3a6ed1def2f697')
CANONICAL_ANALOG_SHA256 = (
    'dfa1cdf1d11950f099f685c9c0d2a1197019415ffcf50c8d8f1988dc532a8325')
HISTORICAL_ANALOG_PREFIX_SHA256 = (
    '95aa6c9f2aa1ff9cf37df432d6ee47170859cfdef2050ffcc684e5487580e1fa')


def check_runtime():
    # Interleaving another instance and reseeding libc must not change a stream.
    first = analog.fastnoise_source_f(analog.GR_GAUSSIAN, .01, 4920, 16384)
    repeated = analog.fastnoise_source_f(analog.GR_GAUSSIAN, .01, 4920, 16384)
    other = analog.fastnoise_source_f(analog.GR_GAUSSIAN, .01, 4921, 16384)
    libc = ctypes.CDLL(None)
    libc.srand48.argtypes = [ctypes.c_long]
    libc.srand48.restype = None
    a, b = [], []
    for index in range(16384):
        a.append(first.sample_unbiased())
        libc.srand48(index)
        b.append(other.sample_unbiased())
        assert repeated.sample_unbiased() == a[-1], 'Shared RNG state'
    assert abs(np.corrcoef(a, b)[0, 1]) < .05, 'Correlated drift streams'


def check_canonical_analog_source():
    """Require exact compatibility bytes from the canonical source."""
    from source_alphabet import source_alphabet

    flowgraph = gr.top_block()
    source = source_alphabet('continuous', 10000, True)
    sink = blocks.vector_sink_f()
    flowgraph.connect(source, sink)
    flowgraph.run()
    prefix = np.asarray(sink.data(), dtype=np.float32)
    assert hashlib.sha256(prefix.tostring()).hexdigest() == (
        HISTORICAL_ANALOG_PREFIX_SHA256)


def check_baseline_defaults():
    """Require an invocation without flags to select the complete Baseline."""
    options = json.loads(subprocess.check_output([
        sys.executable, '-c',
        'import json; from generator_options import configure; '
        'print(json.dumps(vars(configure())))']))
    expected = {
        'seed': 201610, 'python_seed': 201610, 'numpy_seed': 201610,
        'channel_seed': 0x1337,
        'channel_seed_policy': 'restart', 'scheduler': 'sts',
        'frames_per_key': 1000, 'snrs': list(range(-20, 20, 2)),
        'modulations': ['BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64',
                        'GFSK', 'CPFSK', 'WBFM', 'AM-DSB', 'AM-SSB'],
        'output': 'RML2016.10a_dict.dat',
    }
    assert options == expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output_dir = os.path.abspath(args.output)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo)
    sys.path.insert(0, repo)
    check_baseline_defaults()
    check_runtime()
    check_canonical_analog_source()
    command = [sys.executable, 'generate_RML2016.10a.py', '--frames-per-key', '80',
               '--snrs', '-20', '18']

    def run(name, extra=(), failure=False, env=None):
        path = os.path.join(output_dir, name + '.dat')
        with open(path + '.log', 'wb') as log:
            status = subprocess.call(command + list(extra) + ['--output', path],
                                     stdout=log, stderr=subprocess.STDOUT, env=env)
        if failure:
            assert status != 0, name + ' should fail'
            return
        assert status == 0, 'See ' + path + '.log'
        with open(path, 'rb') as source:
            content = source.read()
        data = cPickle.loads(content)
        assert len(data) == 22
        for key, values in data.items():
            assert values.shape == (80, 2, 128) and values.dtype == np.float32, key
            assert np.isfinite(values).all(), key
            iq = values[:, 0] + 1j * values[:, 1]
            assert np.allclose(np.abs(iq).sum(axis=1), 1, rtol=1e-6, atol=1e-7), key
        digest = hashlib.sha256(content).hexdigest()
        print(name, digest)
        sys.stdout.flush()
        return digest

    reference = run('repeat-0')
    assert reference == COMPATIBILITY_PICKLE_SHA256
    assert run('repeat-1') == reference
    assert run('repeat-2') == reference
    stable_args = ['--scheduler', 'sts']
    stable_reference = run('stable-repeat-0', stable_args)
    assert stable_reference == reference
    assert run('stable-repeat-1', stable_args) == stable_reference
    assert run('explicit-restart', stable_args + [
        '--channel-seed-policy', 'restart']) == stable_reference
    advancing_args = stable_args + ['--channel-seed-policy', 'advance']
    advancing = run('advance-policy-0', advancing_args)
    assert advancing == ADVANCING_PICKLE_SHA256
    assert advancing != stable_reference
    assert run('advance-policy-1', advancing_args) == advancing
    # TPB remains available for comparison, but its schedule is not repeatable.
    run('historical-tpb', ['--scheduler', 'tpb'])
    for seed in ('python', 'numpy', 'channel'):
        seed_args = stable_args + ['--' + seed + '-seed', '123']
        changed = run(seed + '-0', seed_args)
        assert changed != stable_reference
        assert run(seed + '-1', seed_args) == changed
    for name, extra in (
            ('zero-channel', ['--channel-seed', '0']),
            ('unknown-channel-policy', ['--channel-seed-policy', 'random']),
            ('large-channel', ['--channel-seed', '2147483645']),
            ('large-numpy', ['--numpy-seed', '4294967296']),
            ('zero-frames', ['--frames-per-key', '0'])):
        run(name, extra, failure=True)
    run('wrong-environment', failure=True, env=dict(os.environ, VOLK_GENERIC='0'))
    analog_source = os.environ['RADIOML_ANALOG_SOURCE']
    assert os.path.getsize(analog_source) == 280227552
    with open(analog_source, 'rb') as source:
        assert hashlib.sha256(source.read()).hexdigest() == (
            CANONICAL_ANALOG_SHA256)
    for name in ('analog-source-decode.txt', 'analog-source.sha256',
                 'analog-source.json'):
        path = os.path.join('/opt/replay-provenance', name)
        with open(path) as source:
            assert source.read().strip(), 'Empty runtime provenance: ' + name
    print('All reproducibility checks passed.')


if __name__ == '__main__':
    main()
