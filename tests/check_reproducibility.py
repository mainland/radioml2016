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


def check_am_ssb_transmitters():
    from transmitters import transmitter_amssb, transmitter_amssb_fixed

    def generate(transmitter, samples):
        tb = gr.top_block()
        source = blocks.vector_source_f(samples.tolist(), False)
        modulator = transmitter()
        sink = blocks.vector_sink_c()
        tb.connect(source, modulator, sink)
        tb.run()
        return np.asarray(sink.data(), dtype=np.complex64)

    time = np.arange(4096, dtype=np.float64) / 44100.0
    message = np.sin(2 * np.pi * 1000 * time).astype(np.float32)
    silence = np.zeros(message.shape, dtype=np.float32)

    def transferred_message(transmitter):
        modulated = generate(transmitter, message)
        carrier = generate(transmitter, silence)
        size = min(modulated.size, carrier.size)
        difference = modulated[:size] - carrier[:size]
        return difference[512:-512]

    historical = transferred_message(transmitter_amssb)
    fixed = transferred_message(transmitter_amssb_fixed)
    assert historical.size > 0 and fixed.size > 0
    historical_rms = np.sqrt(np.mean(np.abs(historical)**2))
    fixed_rms = np.sqrt(np.mean(np.abs(fixed)**2))
    assert historical_rms < 1e-6, 'Historical AM-SSB transferred its message'
    assert fixed_rms > .1, 'Fixed AM-SSB did not transfer its message'


def check_canonical_analog_source():
    """Require exact compatibility bytes and item-based random access."""
    from source_alphabet import source_alphabet

    def generate(offset, count):
        flowgraph = gr.top_block()
        source = source_alphabet(
            'continuous', count, True, source_offset=offset)
        sink = blocks.vector_sink_f()
        flowgraph.connect(source, sink)
        flowgraph.run()
        return np.asarray(sink.data(), dtype=np.float32)

    prefix = generate(0, 10000)
    assert hashlib.sha256(prefix.tostring()).hexdigest() == (
        HISTORICAL_ANALOG_PREFIX_SHA256)
    offset = 1234567
    count = 4096
    with open(os.environ['RADIOML_ANALOG_SOURCE'], 'rb') as source_file:
        source_file.seek(offset * np.dtype('<f4').itemsize)
        expected = np.fromfile(source_file, dtype='<f4', count=count)
    assert np.array_equal(generate(offset, count), expected)


def check_baseline_defaults():
    """Require an invocation without flags to select the complete Baseline."""
    options = json.loads(subprocess.check_output([
        sys.executable, '-c',
        'import json; from generator_options import configure; '
        'print(json.dumps(vars(configure())))']))
    expected = {
        'seed': 201610, 'python_seed': 201610, 'numpy_seed': 201610,
        'analog_source_seed': 201610, 'channel_seed': 0x1337,
        'channel_seed_policy': 'restart', 'scheduler': 'sts',
        'frames_per_key': 1000, 'snrs': list(range(-20, 20, 2)),
        'modulations': ['BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64',
                        'GFSK', 'CPFSK', 'WBFM', 'AM-DSB', 'AM-SSB'],
        'sps': None, 'ebw': None, 'fixed_am_ssb': False,
        'vary_analog_source': False,
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
    check_am_ssb_transmitters()
    check_canonical_analog_source()
    command = [sys.executable, 'generate_RML2016.10a.py', '--frames-per-key', '80',
               '--snrs', '-20', '18']

    def run(name, extra=(), failure=False, env=None, expected_keys=22):
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
        assert len(data) == expected_keys
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
    historical_wbfm = run(
        'historical-wbfm', stable_args + [
            '--modulations', 'WBFM', '--snrs', '18'],
        expected_keys=1)
    varied_analog_args = stable_args + [
        '--vary-analog-source', '--modulations', 'WBFM', '--snrs', '18']
    varied_analog = run(
        'vary-analog-source-0', varied_analog_args, expected_keys=1)
    assert varied_analog != historical_wbfm
    assert run('vary-analog-source-1', varied_analog_args,
               expected_keys=1) == varied_analog
    other_analog = run(
        'vary-analog-source-seed',
        varied_analog_args + ['--analog-source-seed', '123'],
        expected_keys=1)
    assert other_analog != varied_analog
    fixed_args = [
        '--fixed-am-ssb', '--modulations', 'AM-SSB', '--snrs', '18']
    fixed = run('fixed-am-ssb-0', fixed_args, expected_keys=1)
    assert run('fixed-am-ssb-1', fixed_args, expected_keys=1) == fixed
    digital_args = ['--modulations', 'BPSK', 'GFSK', 'CPFSK', '--snrs', '18']
    digital = run('digital-default', digital_args, expected_keys=3)
    varied_sps = run('vary-sps', ['--sps', '2', '12'] + digital_args,
                     expected_keys=3)
    varied_ebw = run('vary-ebw', ['--ebw', '.1', '.5'] + digital_args,
                     expected_keys=3)
    varied_args = ['--sps', '2', '12', '--ebw', '.1', '.5'] + digital_args
    varied = run('vary-sps-ebw-0', varied_args, expected_keys=3)
    assert len({digital, varied_sps, varied_ebw, varied}) == 4
    assert run('vary-sps-ebw-1', varied_args, expected_keys=3) == varied
    for name, extra in (
            ('zero-channel', ['--channel-seed', '0']),
            ('unknown-channel-policy', ['--channel-seed-policy', 'random']),
            ('large-channel', ['--channel-seed', '2147483645']),
            ('large-numpy', ['--numpy-seed', '4294967296']),
            ('large-analog-source', [
                '--analog-source-seed', '4294967296']),
            ('zero-frames', ['--frames-per-key', '0']),
            ('reversed-sps', ['--sps', '8', '2']),
            ('gfsk-sps-one', ['--sps', '1', '1', '--modulations', 'GFSK']),
            ('zero-ebw', ['--ebw', '0', '1'])):
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
