#!/usr/bin/env python2.7
"""Characterize deterministic channel controls and RadioML SNR labels."""
from __future__ import print_function

import argparse
import hashlib
import json
import math
import os
import sys

os.environ['GR_SCHEDULER'] = 'STS'

import numpy as np
from gnuradio import blocks, channels, gr


SAMPLE_RATE_HZ = 200000.0
CHANNEL_SEED = 0x1337
BIT_SEED = 201610


def make_channel(control, noise_amplitude=0.0):
    """Construct one controlled form of the dataset channel."""
    sro_std_dev = .01 if control in ('sro', 'combined') else 0.0
    sro_max_dev = 50 if control in ('sro', 'combined') else 0.0
    cfo_std_dev = .01 if control in ('cfo', 'combined') else 0.0
    cfo_max_dev = .5e3 if control in ('cfo', 'combined') else 0.0
    if control in ('fading', 'combined'):
        doppler_frequency = 1
        k_factor = 4
        delays = [0.0, 0.9, 1.7]
        magnitudes = [1, .8, .3]
    else:
        doppler_frequency = 0
        k_factor = 1e6
        delays = [0.0]
        magnitudes = [1.0]
    return channels.dynamic_channel_model(
        SAMPLE_RATE_HZ, sro_std_dev, sro_max_dev, cfo_std_dev,
        cfo_max_dev, 8, doppler_frequency, True, k_factor, delays,
        magnitudes, 8, noise_amplitude, CHANNEL_SEED)


def transmit(bits, control, noise_amplitude=0.0):
    """Pass deterministic BPSK through one controlled channel."""
    import transmitters

    flowgraph = gr.top_block()
    source = blocks.vector_source_b(bits.tolist(), False)
    modulator = transmitters.transmitter_bpsk(8, .35)
    channel = make_channel(control, noise_amplitude)
    sink = blocks.vector_sink_c()
    flowgraph.connect(source, modulator, channel, sink)
    flowgraph.run()
    output = np.asarray(sink.data(), dtype=np.complex64)
    assert output.size > 4096 and np.isfinite(output).all()
    return output


def best_complex_alignment(reference, observed, maximum_lag=256):
    """Fit lag and one complex gain between two finite waveforms."""
    best = None
    for lag in range(-maximum_lag, maximum_lag + 1):
        reference_start = max(0, lag)
        observed_start = max(0, -lag)
        count = min(reference.size - reference_start,
                    observed.size - observed_start, 20000)
        if count < 4096:
            continue
        expected = reference[reference_start:reference_start + count]
        actual = observed[observed_start:observed_start + count]
        gain = np.vdot(expected, actual) / np.vdot(expected, expected)
        residual = actual - gain * expected
        nrmse = np.sqrt(
            np.mean(np.abs(residual)**2) / np.mean(np.abs(actual)**2))
        candidate = (float(nrmse), lag, gain)
        if best is None or candidate[0] < best[0]:
            best = candidate
    assert best is not None
    return {
        'nrmse': best[0],
        'lag': int(best[1]),
        'gain_real': float(best[2].real),
        'gain_imag': float(best[2].imag),
    }


def describe(reference, output):
    """Return deterministic waveform and known-reference measurements."""
    return {
        'sample_count': int(output.size),
        'sha256': hashlib.sha256(output.tostring()).hexdigest(),
        'mean_power': float(np.mean(np.abs(output)**2)),
        'reference_alignment': best_complex_alignment(reference, output),
    }


def measure_snr_labels(bits):
    """Measure signal and additive-noise power under the combined channel."""
    signal = transmit(bits, 'combined', 0.0)
    rows = []
    for label in (-20, 0, 18):
        amplitude = 10**(-label / 10.0)
        noisy = transmit(bits, 'combined', amplitude)
        assert noisy.shape == signal.shape
        noise = noisy - signal
        signal_power = float(np.mean(np.abs(signal)**2))
        noise_power = float(np.mean(np.abs(noise)**2))
        rows.append({
            'label_db': label,
            'noise_amplitude': amplitude,
            'signal_power': signal_power,
            'noise_power': noise_power,
            'measured_snr_db': 10 * math.log10(signal_power / noise_power),
        })
    for left, right in zip(rows, rows[1:]):
        measured_change = right['measured_snr_db'] - left['measured_snr_db']
        expected_change = 2 * (right['label_db'] - left['label_db'])
        assert abs(measured_change - expected_change) < 1e-4
    return rows


def check_post_channel_offsets(transmission):
    """Reconstruct normalized windows from real post-channel coordinates."""
    from dataset_window import normalized_complex_window

    offsets = (73, 2048, 8191, 16384)
    windows = [normalized_complex_window(transmission, offset, 128)
               for offset in offsets]
    for offset, window in zip(offsets, windows):
        selected = transmission[offset:offset + 128]
        expected = selected / np.sum(np.abs(selected))
        assert np.array_equal(window, expected.astype(np.complex64))
    values = np.asarray(windows, dtype=np.complex64)
    return {
        'coordinate': 'zero-based post-channel sample offset',
        'offsets': list(offsets),
        'window_length': 128,
        'sha256': hashlib.sha256(values.tostring()).hexdigest(),
    }


def run_checks():
    """Run the channel-control checks and return their report."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, 'tests'))
    import check_modulators

    rng = np.random.RandomState(BIT_SEED)
    bits = rng.randint(0, 2, 8192).astype(np.uint8)
    reference = transmit(bits, 'baseline')
    repeated = transmit(bits, 'baseline')
    assert np.array_equal(reference, repeated)
    baseline_receiver = check_modulators.demodulate_linear(
        reference, bits, check_modulators.linear_constellations()['BPSK'],
        8, .35)
    assert baseline_receiver['symbol_errors'] == 0, baseline_receiver

    controls = {}
    control_outputs = {}
    constellation = check_modulators.linear_constellations()['BPSK']
    for name, noise_amplitude in (
            ('baseline', 0.0), ('awgn', .1), ('cfo', 0.0), ('sro', 0.0),
            ('fading', 0.0), ('combined', 10**(-18 / 10.0))):
        output = transmit(bits, name, noise_amplitude)
        control_outputs[name] = output
        assert np.array_equal(output, transmit(bits, name, noise_amplitude))
        controls[name] = describe(reference, output)
        controls[name]['receiver'] = check_modulators.demodulate_linear(
            output, bits, constellation, 8, .35)
    assert controls['baseline']['reference_alignment']['nrmse'] < 1e-7
    for name in ('awgn', 'cfo', 'sro', 'fading', 'combined'):
        assert controls[name]['sha256'] != controls['baseline']['sha256']
    evm_limits = {
        'baseline': .005,
        'awgn': .05,
        'cfo': .01,
        'sro': .005,
        'fading': .15,
        'combined': .15,
    }
    for name, limit in evm_limits.items():
        receiver = controls[name]['receiver']
        assert receiver['symbol_errors'] == 0, (name, receiver)
        assert receiver['evm_rms'] < limit, (name, receiver)

    report = {
        'schema': 1,
        'scope': 'deterministic BPSK channel controls',
        'sample_rate_hz': int(SAMPLE_RATE_HZ),
        'channel_seed': CHANNEL_SEED,
        'bit_seed': BIT_SEED,
        'baseline_receiver': baseline_receiver,
        'controls': controls,
        'offset_control': check_post_channel_offsets(
            control_outputs['combined']),
        'snr_labels': measure_snr_labels(bits),
        'snr_conclusion': (
            'The label controls noise amplitude as 10**(-label/10); '
            'noise power therefore changes by twice the label in dB.'),
    }
    return report


def test_channel_controls():
    """Expose the deterministic channel-control checks to pytest."""
    run_checks()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='write the JSON report to this path')
    args = parser.parse_args()
    report = run_checks()
    content = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.output:
        with open(args.output, 'w') as destination:
            destination.write(content)
        print('Wrote ' + args.output, file=sys.stderr)
    else:
        print(content, end='')
    print('All channel controls passed.', file=sys.stderr)


if __name__ == '__main__':
    main()
