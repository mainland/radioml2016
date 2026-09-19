#!/usr/bin/env python2.7
"""Validate repeatable generation and optionally preserve its artifacts."""
from __future__ import print_function

import argparse
import cPickle
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys

os.environ['GR_SCHEDULER'] = 'STS'

import h5py
import numpy as np
import pytest
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


def check_window_offsets():
    """Verify that exported offsets use the post-channel sample coordinate."""
    from dataset_window import (normalized_complex_window,
                                normalized_complex_window_with_divisor)

    real = np.arange(300, dtype=np.float32)
    transmission = real + 1j * (1000 + real)
    transmission = transmission.astype(np.complex64)
    offset = 73
    length = 128
    window = normalized_complex_window(transmission, offset, length)
    paired_window, divisor = normalized_complex_window_with_divisor(
        transmission, offset, length)
    expected = transmission[offset:offset + length]
    expected_divisor = np.float32(np.sum(np.abs(expected)))
    expected = expected / expected_divisor
    assert np.array_equal(window, expected.astype(np.complex64))
    assert np.array_equal(paired_window, window)
    assert divisor == expected_divisor
    assert window[0] == expected[0] and window[-1] == expected[-1]
    for bad_offset, bad_length in ((-1, length), (0, 0), (200, length)):
        try:
            normalized_complex_window(transmission, bad_offset, bad_length)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid window interval succeeded')


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
        'sps': None, 'ebw': None, 'fixed_am_ssb': False, 'fixed_wbfm': False,
        'settled_windows': False, 'vary_analog_source': False,
        'snr_mode': 'historical', 'measure_snr': False,
        'output_format': 'pickle', 'output': 'RML2016.10a_dict.dat',
    }
    assert options == expected


def run_checks(output_dir):
    """Run the reproducibility matrix and write its artifacts to output_dir."""
    output_dir = os.path.abspath(output_dir)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo)
    sys.path.insert(0, repo)
    check_baseline_defaults()
    check_runtime()
    check_am_ssb_transmitters()
    check_window_offsets()
    check_canonical_analog_source()
    command = [sys.executable, 'generate_RML2016.10a.py', '--frames-per-key', '80',
               '--snrs', '-20', '18']
    artifacts = []
    interchange_contract = {}

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
        artifacts.append({
            'name': name,
            'format': 'pickle',
            'arguments': command[2:] + list(extra),
            'sha256': digest,
        })
        print(name, digest)
        sys.stdout.flush()
        return digest

    def run_hdf5(name, extra=(), expected_seed_policy='restart',
                 initial_channel_seed=0x1337):
        path = os.path.join(output_dir, name + '.h5')
        with open(path + '.log', 'wb') as log:
            status = subprocess.call(
                command + list(extra) +
                ['--output-format', 'hdf5', '--output', path],
                stdout=log, stderr=subprocess.STDOUT)
        assert status == 0, 'See ' + path + '.log'
        with h5py.File(path, 'r') as source:
            assert source.attrs['schema'] == 'radioml2016-attributed'
            assert source.attrs['schema_version'] == 1
            labels = json.loads(source.attrs['modulation_names_json'])
            options = json.loads(source.attrs['generation_options_json'])
            analog_source = json.loads(source.attrs['analog_source_json'])
            assert analog_source['sha256'] == CANONICAL_ANALOG_SHA256
            assert analog_source['dtype'] == '<f4'
            assert analog_source['sample_count'] == 70056888
            assert options['initial_channel_seed'] == initial_channel_seed
            assert options['channel_seed_policy'] == expected_seed_policy
            assert options['scheduler'] == 'sts'
            assert options['snr_mode'] == 'historical'
            assert options['measure_snr']
            assert options['settled_windows']
            assert options['vary_analog_source']
            assert options['analog_source_seed'] == 201610
            iq = source['windows/iq'][:]
            modulation = source['windows/modulation_id'][:]
            snr = source['windows/snr_db'][:]
            numbers = source['windows/transmission_number'][:]
            offsets = source['windows/offset'][:]
            normalization_l1 = source['windows/normalization_l1'][:]
            measurement_valid = source[
                'windows/snr_measurement_valid'][:].astype(bool)
            signal_power = source['windows/signal_power'][:]
            noise_power = source['windows/noise_power'][:]
            measured_snr_db = source['windows/measured_snr_db'][:]
            assert iq.shape == (240, 2, 128) and iq.dtype == np.float32
            assert np.isfinite(iq).all()
            assert numbers.shape == offsets.shape == (240,)
            assert normalization_l1.dtype == np.dtype('<f4')
            assert np.all(np.isfinite(normalization_l1))
            assert np.all(normalization_l1 > 0)
            assert measurement_valid.all()
            assert np.all(np.isfinite(signal_power))
            assert np.all(signal_power > 0)
            assert np.all(np.isfinite(noise_power))
            assert np.all(noise_power > 0)
            assert np.allclose(
                measured_snr_db,
                10.0 * np.log10(signal_power / noise_power),
                rtol=0, atol=1e-12)
            complex_iq = iq[:, 0] + 1j * iq[:, 1]
            reconstructed = complex_iq * normalization_l1[:, np.newaxis]
            assert np.allclose(
                np.abs(reconstructed).sum(axis=1), normalization_l1,
                rtol=2e-6, atol=1e-5)
            transmissions = source['transmissions']
            count = transmissions['sample_count'].shape[0]
            assert count > 2 and numbers.max() < count
            channel_seeds = transmissions['channel_seed'][:]
            if expected_seed_policy == 'restart':
                assert np.all(channel_seeds == initial_channel_seed)
            else:
                assert channel_seeds[0] == initial_channel_seed
                expected_steps = (
                    channel_seeds[1:].astype(np.int64) - channel_seeds[:-1])
                assert np.all(expected_steps % 2147483644 == 4)
                if initial_channel_seed == 2147483644:
                    assert channel_seeds[:3].tolist() == [2147483644, 4, 8]
            assert np.all(offsets + 128 < transmissions['sample_count'][:][numbers])
            assert np.array_equal(
                modulation, transmissions['modulation_id'][:][numbers])
            assert np.array_equal(snr, transmissions['snr_db'][:][numbers])
            for number in np.unique(numbers):
                group_offsets = offsets[numbers == number]
                assert np.all(np.diff(group_offsets) > 0)

            transmission_modulations = np.asarray(
                [labels[index] for index in transmissions['modulation_id'][:]])
            digital = transmission_modulations == 'BPSK'
            analog = np.logical_not(digital)
            assert digital.any() and analog.any()
            sps = transmissions['sps'][:]
            ebw = transmissions['ebw'][:]
            assert np.all(np.logical_and(sps[digital] >= 2, sps[digital] <= 12))
            assert np.all(np.logical_and(ebw[digital] >= .1, ebw[digital] <= .5))
            assert np.all(sps[analog] == 0) and np.isnan(ebw[analog]).all()
            source_valid = transmissions['analog_source_valid'][:].astype(bool)
            source_offsets = transmissions['analog_source_offset'][:]
            source_lengths = transmissions['analog_source_length'][:]
            assert np.array_equal(source_valid, analog)
            assert np.all(source_offsets[digital] == 0)
            assert np.all(source_lengths[digital] == 0)
            assert np.all(source_offsets[analog] % 10000 == 0)
            assert np.all(source_lengths[analog] == 10000)
            assert np.unique(source_offsets[analog]).size == analog.sum()
            assert np.all(source_offsets[analog] + source_lengths[analog] <=
                          analog_source['sample_count'])
            masks = transmissions['random_mask'][:]
            mask_valid = transmissions['random_mask_valid'][:].astype(bool)
            assert np.array_equal(mask_valid, digital)
            assert np.logical_or(masks[digital] == 0, masks[digital] == 1).all()
            assert np.all(masks[analog] == 0)
            modulator_rates = transmissions['modulator_sample_rate_hz'][:]
            input_rates = transmissions['channel_input_sample_rate_hz'][:]
            channel_rates = transmissions['channel_model_sample_rate_hz'][:]
            is_wbfm = transmission_modulations == 'WBFM'
            assert np.all(modulator_rates[is_wbfm] == 220500)
            assert np.all(modulator_rates[np.logical_not(is_wbfm)] == 200000)
            assert np.all(input_rates == 200000)
            assert np.all(channel_rates == 200000)
            fixed = transmissions['am_ssb_fixed'][:].astype(bool)
            assert np.array_equal(fixed, transmission_modulations == 'AM-SSB')
            fixed_wbfm = transmissions['wbfm_fixed'][:].astype(bool)
            assert np.array_equal(fixed_wbfm, is_wbfm)
            guards = transmissions['settling_guard_samples'][:]
            assert guards.dtype == np.dtype('<u4')
            assert np.all(offsets >= guards[numbers])
            amplitudes = transmissions['noise_amplitude'][:]
            assert amplitudes.dtype == np.dtype('<f8')
            assert np.allclose(
                amplitudes,
                10.0 ** (-transmissions['snr_db'][:] / 10.0))
            transmission_valid = transmissions[
                'snr_measurement_valid'][:].astype(bool)
            transmission_signal = transmissions['signal_power'][:]
            transmission_noise = transmissions['noise_power'][:]
            transmission_snr = transmissions['measured_snr_db'][:]
            transmission_windows = transmissions[
                'snr_measurement_window_count'][:]
            assert transmission_valid.all()
            assert np.all(transmission_windows > 0)
            assert np.all(np.isfinite(transmission_signal))
            assert np.all(np.isfinite(transmission_noise))
            assert np.allclose(
                transmission_snr,
                10.0 * np.log10(
                    transmission_signal / transmission_noise),
                rtol=0, atol=1e-12)
            for number in range(count):
                selected = numbers == number
                assert selected.sum() == transmission_windows[number]
                assert abs(signal_power[selected].mean() -
                           transmission_signal[number]) < 1e-12
                assert abs(noise_power[selected].mean() -
                           transmission_noise[number]) < 1e-12
            datasets = {}
            for group_name in ('windows', 'transmissions'):
                group = source[group_name]
                for dataset_name in sorted(group.keys()):
                    values = group[dataset_name][:]
                    datasets[group_name + '/' + dataset_name] = {
                        'dtype': values.dtype.str,
                        'shape': list(values.shape),
                        'sha256': hashlib.sha256(values.tostring()).hexdigest(),
                    }
            if name == 'attributed-0':
                interchange_contract.update({
                    'schema': source.attrs['schema'],
                    'schema_version': int(source.attrs['schema_version']),
                    'modulation_names': labels,
                    'datasets': datasets,
                })
        with open(path, 'rb') as source:
            digest = hashlib.sha256(source.read()).hexdigest()
        artifacts.append({
            'name': name,
            'format': 'hdf5',
            'arguments': command[2:] + list(extra) + ['--output-format', 'hdf5'],
            'sha256': digest,
        })
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
    fixed_args = stable_args + [
        '--fixed-am-ssb', '--modulations', 'AM-SSB', '--snrs', '18']
    fixed = run('fixed-am-ssb-0', fixed_args, expected_keys=1)
    assert run('fixed-am-ssb-1', fixed_args, expected_keys=1) == fixed
    scaled_args = fixed_args + ['--snr-mode', 'scaled']
    scaled = run('scaled-snr-0', scaled_args, expected_keys=1)
    assert scaled != fixed
    assert run('scaled-snr-1', scaled_args, expected_keys=1) == scaled
    calibrated_args = fixed_args + ['--snr-mode', 'calibrated']
    calibrated = run(
        'calibrated-snr-0', calibrated_args, expected_keys=1)
    assert calibrated != scaled
    assert run('calibrated-snr-1', calibrated_args,
               expected_keys=1) == calibrated
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
    fixed_wbfm_args = [
        '--scheduler', 'sts', '--fixed-wbfm', '--modulations', 'WBFM',
        '--snrs', '18']
    fixed_wbfm = run(
        'fixed-wbfm-0', fixed_wbfm_args, expected_keys=1)
    assert fixed_wbfm != historical_wbfm
    assert run('fixed-wbfm-1', fixed_wbfm_args, expected_keys=1) == fixed_wbfm
    digital_args = stable_args + [
        '--modulations', 'BPSK', 'GFSK', 'CPFSK', '--snrs', '18']
    digital = run('digital-default', digital_args, expected_keys=3)
    varied_sps = run('vary-sps', ['--sps', '2', '12'] + digital_args,
                     expected_keys=3)
    varied_ebw = run('vary-ebw', ['--ebw', '.1', '.5'] + digital_args,
                     expected_keys=3)
    varied_args = ['--sps', '2', '12', '--ebw', '.1', '.5'] + digital_args
    varied = run('vary-sps-ebw-0', varied_args, expected_keys=3)
    assert len({digital, varied_sps, varied_ebw, varied}) == 4
    assert run('vary-sps-ebw-1', varied_args, expected_keys=3) == varied
    settled_args = varied_args + ['--settled-windows']
    settled = run('settled-windows-0', settled_args, expected_keys=3)
    assert settled != varied
    assert run('settled-windows-1', settled_args, expected_keys=3) == settled
    hdf5_args = stable_args + [
        '--modulations', 'BPSK', 'WBFM', 'AM-SSB', '--snrs', '18',
        '--sps', '2', '12', '--ebw', '.1', '.5', '--fixed-am-ssb',
        '--fixed-wbfm', '--settled-windows', '--vary-analog-source']
    run('attributed-pickle', hdf5_args, expected_keys=3)
    attributed_pickle = os.path.join(output_dir, 'attributed-pickle.dat')
    measured_hdf5_args = hdf5_args + ['--measure-snr']
    attributed = run_hdf5('attributed-0', measured_hdf5_args)
    assert run_hdf5('attributed-1', measured_hdf5_args) == attributed
    wrapping_args = measured_hdf5_args + [
        '--channel-seed', '2147483644', '--channel-seed-policy', 'advance']
    wrapping = run_hdf5(
        'attributed-advance-wrap-0', wrapping_args, 'advance', 2147483644)
    assert run_hdf5(
        'attributed-advance-wrap-1', wrapping_args, 'advance',
        2147483644) == wrapping
    assert wrapping != attributed
    run_hdf5('attributed-restart-max', measured_hdf5_args + [
        '--channel-seed', '2147483644'], initial_channel_seed=2147483644)
    attributed_hdf5 = os.path.join(output_dir, 'attributed-0.h5')
    comparison = subprocess.check_output([
        sys.executable, 'scripts/compare_pickle_hdf5.py', attributed_pickle,
        attributed_hdf5])
    comparison = json.loads(comparison)
    assert comparison['equal'] and comparison['window_count'] == 240
    assert comparison['schema_version'] == 1
    unsupported_hdf5 = os.path.join(output_dir, 'unsupported-version.h5')
    shutil.copyfile(attributed_hdf5, unsupported_hdf5)
    with h5py.File(unsupported_hdf5, 'r+') as destination:
        destination.attrs['schema_version'] = np.uint16(2)
    status = subprocess.call([
        sys.executable, 'scripts/compare_pickle_hdf5.py', attributed_pickle,
        unsupported_hdf5])
    assert status != 0
    mismatched_pickle = os.path.join(output_dir, 'digital-default.dat')
    status = subprocess.call([
        sys.executable, 'scripts/compare_pickle_hdf5.py', mismatched_pickle,
        attributed_hdf5])
    assert status != 0
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
    run('measure-snr-pickle', ['--measure-snr'], failure=True)
    run('wrong-environment', failure=True, env=dict(os.environ, VOLK_GENERIC='0'))
    provenance = {}
    analog_source = os.environ['RADIOML_ANALOG_SOURCE']
    assert os.path.getsize(analog_source) == 280227552
    with open(analog_source, 'rb') as source:
        assert hashlib.sha256(source.read()).hexdigest() == CANONICAL_ANALOG_SHA256
    for name in ('deterministic-runtime.json', 'hdf5-packages.tsv', 'hdf5.txt',
                 'test-packages.tsv', 'pytest.txt', 'analog-source-decode.txt',
                 'analog-source.sha256', 'analog-source.json'):
        path = os.path.join('/opt/replay-provenance', name)
        with open(path) as source:
            content = source.read().strip()
        assert content, 'Empty runtime provenance: ' + name
        provenance[name] = content
    matrix = {
        'schema': 1,
        'scope': 'representative reproducibility and interchange matrix',
        'artifacts': artifacts,
        'interchange_contract': interchange_contract,
        'runtime_provenance': provenance,
    }
    matrix_path = os.path.join(output_dir, 'reproducibility-matrix.json')
    with open(matrix_path, 'w') as destination:
        destination.write(json.dumps(matrix, sort_keys=True, indent=2) + '\n')
    print('Wrote ' + matrix_path)
    print('All reproducibility checks passed.')
    return matrix


@pytest.mark.slow
def test_reproducibility(tmpdir):
    """Expose the complete dataset reproducibility matrix to pytest."""
    run_checks(str(tmpdir))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    run_checks(args.output)


if __name__ == '__main__':
    main()
