#!/usr/bin/env python2.7
"""Validate clean RadioML transmitter outputs with reference demodulators."""
from __future__ import print_function

import argparse
import json
import math
import os
import sys

os.environ['GR_SCHEDULER'] = 'STS'

import numpy as np
from gnuradio import blocks, gr
from scipy import signal


SAMPLES_PER_SYMBOL = 8
EXCESS_BANDWIDTH = 0.35
BIT_SEED = 201610
AUDIO_RATE_HZ = 44100.0
AM_RATE_HZ = 200000.0
WBFM_RATE_HZ = 220500.0
FIXED_WBFM_RATE_HZ = 200000.0


def stream_bytes(transmitter, values):
    """Run a byte-input transmitter and return its complex output."""
    tb = gr.top_block()
    source = blocks.vector_source_b(values.tolist(), False)
    sink = blocks.vector_sink_c()
    tb.connect(source, transmitter, sink)
    tb.run()
    output = np.asarray(sink.data(), dtype=np.complex64)
    assert output.size > 0 and np.isfinite(output).all()
    return output


def stream_floats(transmitter, values):
    """Run a float-input transmitter and return its complex output."""
    tb = gr.top_block()
    source = blocks.vector_source_f(values.tolist(), False)
    sink = blocks.vector_sink_c()
    tb.connect(source, transmitter, sink)
    tb.run()
    output = np.asarray(sink.data(), dtype=np.complex64)
    assert output.size > 0 and np.isfinite(output).all()
    return output


def grouped_integers(bits, width):
    """Convert MSB-first bit groups to integer symbol indices."""
    groups = bits[:bits.size - bits.size % width].reshape((-1, width))
    weights = 1 << np.arange(width - 1, -1, -1)
    return np.dot(groups, weights).astype(np.int64)


def normalized(points):
    """Apply gr-mapper's average-magnitude normalization."""
    points = np.asarray(points, dtype=np.complex128)
    return points * (points.size / np.abs(points).sum())


def gray_decode(label):
    """Convert a binary-reflected Gray label to its natural index."""
    result = 0
    while label:
        result ^= label
        label >>= 1
    return result


def gray_labeled(natural_points):
    """Index natural-order constellation points by their Gray input labels."""
    points = normalized(natural_points)
    indices = [gray_decode(label) for label in range(points.size)]
    return points[np.asarray(indices, dtype=np.int64)]


def labeled_square_qam(label_rows):
    """Construct square QAM from rows of input bit labels."""
    rows = [row.split() for row in label_rows]
    side = len(rows)
    assert all(len(row) == side for row in rows)
    levels = np.arange(-(side - 1), side, 2, dtype=np.float64)
    points = np.empty(side * side, dtype=np.complex128)
    labels = []
    for row_index, row in enumerate(rows):
        for column_index, bits in enumerate(row):
            label = int(bits, 2)
            labels.append(label)
            points[label] = complex(levels[column_index],
                                    levels[side - row_index - 1])
    assert sorted(labels) == list(range(side * side))
    return normalized(points)


def root_raised_cosine(samples_per_symbol, excess_bw, span_symbols=12):
    """Construct an independent unit-energy root-raised-cosine filter."""
    half = span_symbols * samples_per_symbol // 2
    times = np.arange(-half, half + 1, dtype=np.float64) / samples_per_symbol
    taps = np.empty(times.shape, dtype=np.float64)
    for index, value in enumerate(times):
        if abs(value) < 1e-12:
            taps[index] = 1 + excess_bw * (4 / math.pi - 1)
        elif abs(abs(4 * excess_bw * value) - 1) < 1e-12:
            angle = math.pi / (4 * excess_bw)
            taps[index] = excess_bw / math.sqrt(2) * (
                (1 + 2 / math.pi) * math.sin(angle) +
                (1 - 2 / math.pi) * math.cos(angle))
        else:
            numerator = (math.sin(math.pi * value * (1 - excess_bw)) +
                         4 * excess_bw * value *
                         math.cos(math.pi * value * (1 + excess_bw)))
            denominator = (math.pi * value *
                           (1 - (4 * excess_bw * value)**2))
            taps[index] = numerator / denominator
    return taps / np.sqrt(np.sum(taps**2))


def linear_constellations():
    """Return exact input-label-to-point maps for the pinned gr-mapper."""
    root_half = math.sqrt(.5)
    qpsk = np.asarray([1, 1j, -1, -1j]) * complex(root_half, root_half)
    psk8 = np.exp(1j * np.arange(8) * math.pi / 4)
    # QAM rows run from positive to negative Q. Columns run from negative to
    # positive I. The spatial form exposes which neighboring labels are Gray.
    qam16_labels = (
        '1100 1000 0000 0100',
        '1101 1001 0001 0101',
        '1111 1011 0011 0111',
        '1110 1010 0010 0110',
    )
    qam64_labels = (
        '000000 100100 100000 000100 010010 110110 110010 010110',
        '000010 100110 100010 000110 010000 110100 110000 010100',
        '001001 101101 101001 001101 011011 111111 111011 011111',
        '001011 101111 101011 001111 011001 111101 111001 011101',
        '000001 100101 100001 000101 010011 110111 110011 010111',
        '000011 100111 100011 000111 010001 110101 110001 010101',
        '001000 101100 101000 001100 011010 111110 111010 011110',
        '001010 101110 101010 001110 011000 111100 111000 011100',
    )
    # Provenance: gr-mapper revision
    # 15e71bf01be68d427ed9f37966b83efc1180a1d5 calls every permutation a
    # "greymap," but its emitted PAM4 and QAM64 labelings are not fully Gray.
    return {
        'BPSK': normalized([1, -1]),
        'QPSK': gray_labeled(qpsk),
        '8PSK': gray_labeled(psk8),
        'PAM4': normalized([-3, -1, 1, 3]),
        'QAM16': labeled_square_qam(qam16_labels),
        'QAM64': labeled_square_qam(qam64_labels),
    }


def demodulate_linear(output, bits, constellation, samples_per_symbol,
                      excess_bandwidth):
    """Recover pulse-shaped symbols by timing search and nearest neighbors."""
    width = int(round(math.log(constellation.size, 2)))
    expected_indices = grouped_integers(bits, width)
    expected = constellation[expected_indices]
    matched = np.convolve(output, root_raised_cosine(
        samples_per_symbol, excess_bandwidth), mode='full')
    guard = 80
    count = min(512, expected.size - 2 * guard)
    assert count > 128
    best = None
    for start in range(samples_per_symbol):
        symbols = matched[start::samples_per_symbol]
        for symbol_lag in range(-80, 81):
            observed_start = guard + max(0, -symbol_lag)
            expected_start = guard + max(0, symbol_lag)
            observed = symbols[observed_start:observed_start + count]
            reference = expected[expected_start:expected_start + count]
            if observed.size != count or reference.size != count:
                continue
            gain = np.vdot(reference, observed) / np.vdot(reference, reference)
            error = np.sqrt(np.mean(np.abs(observed - gain * reference)**2))
            error /= np.sqrt(np.mean(np.abs(gain * reference)**2))
            candidate = (float(error), start, symbol_lag, gain, observed)
            if best is None or candidate[0] < best[0]:
                best = candidate
    assert best is not None
    error, start, symbol_lag, gain, observed = best
    recovered = observed / gain
    distances = np.abs(recovered[:, None] - constellation[None, :])
    decisions = np.argmin(distances, axis=1)
    expected_start = guard + max(0, symbol_lag)
    expected_slice = expected_indices[expected_start:expected_start + count]
    symbol_errors = int(np.count_nonzero(decisions != expected_slice))
    return {
        'samples': int(output.size),
        'timing_offset': int(start),
        'symbol_lag': int(symbol_lag),
        'symbols_checked': int(count),
        'symbol_errors': symbol_errors,
        'evm_rms': error,
    }


def demodulate_binary_fsk(output, bits, samples_per_symbol):
    """Recover binary FSK data from the sign of average phase increments."""
    phase_step = np.angle(output[1:] * np.conj(output[:-1]))
    best = None
    count = min(1024, bits.size - 64)
    for start in range(20 * samples_per_symbol):
        stop = start + count * samples_per_symbol
        if stop > phase_step.size:
            break
        soft = phase_step[start:stop].reshape(
            (-1, samples_per_symbol)).mean(axis=1)
        for bit_lag in range(16):
            expected = bits[bit_lag:bit_lag + count]
            if expected.size != count:
                continue
            for polarity in (1, -1):
                decisions = (polarity * soft > 0).astype(np.uint8)
                errors = int(np.count_nonzero(decisions != expected))
                key = (errors, start, bit_lag, polarity)
                if best is None or key < best[0]:
                    best = (key, soft)
    (errors, start, bit_lag, polarity), soft = best
    level_soft = soft
    level_bits = bits[bit_lag:bit_lag + count]
    detector = 'symbol_mean'
    if errors:
        available = min((phase_step.size - start) // samples_per_symbol,
                        bits.size - bit_lag)
        full_soft = phase_step[
            start:start + available * samples_per_symbol].reshape(
                (-1, samples_per_symbol)).mean(axis=1)
        radius = 32
        centers = np.arange(radius, available - radius)
        features = np.column_stack(
            [full_soft[centers + offset]
             for offset in range(-radius, radius + 1)] +
            [np.ones(centers.size)])
        targets = 2 * bits[bit_lag + centers].astype(np.float64) - 1
        split = min(2048, centers.size // 2)
        assert split >= 512 and centers.size - split >= 512
        coefficients = np.linalg.lstsq(
            features[:split], targets[:split])[0]
        heldout = np.dot(features[split:], coefficients)
        heldout_bits = bits[bit_lag + centers[split:]]
        decisions = (heldout > 0).astype(np.uint8)
        errors = int(np.count_nonzero(decisions != heldout_bits))
        count = int(heldout_bits.size)
        soft = full_soft
        detector = 'trained-linear-equalizer'
    magnitude = np.abs(output)
    return {
        'samples': int(output.size),
        'timing_offset': int(start),
        'bit_lag': int(bit_lag),
        'polarity': int(polarity),
        'bits_checked': int(count),
        'bit_errors': int(errors),
        'detector': detector,
        'mean_frequency_separation': float(abs(
            level_soft[level_bits == 1].mean() -
            level_soft[level_bits == 0].mean())),
        'envelope_relative_stddev': float(magnitude.std() / magnitude.mean()),
    }


def multitone(sample_rate, count):
    """Return the deterministic audio-band test message."""
    time = np.arange(count, dtype=np.float64) / sample_rate
    return (.12 * np.sin(2 * math.pi * 1000 * time) +
            .08 * np.sin(2 * math.pi * 3000 * time + .2) +
            .05 * np.cos(2 * math.pi * 5000 * time - .3)).astype(np.float32)


def best_real_alignment(reference, observed, maximum_lag):
    """Align real sequences and report scale-independent recovery error."""
    best = None
    for lag in range(-maximum_lag, maximum_lag + 1):
        reference_start = max(0, lag)
        observed_start = max(0, -lag)
        count = min(reference.size - reference_start,
                    observed.size - observed_start)
        if count < 1024:
            continue
        reference_slice = reference[reference_start:reference_start + count]
        observed_slice = observed[observed_start:observed_start + count]
        reference_slice = reference_slice - reference_slice.mean()
        observed_slice = observed_slice - observed_slice.mean()
        gain = np.dot(reference_slice, observed_slice) / np.dot(reference_slice,
                                                                 reference_slice)
        residual = observed_slice - gain * reference_slice
        nrmse = np.sqrt(np.mean(residual**2) / np.mean(observed_slice**2))
        correlation = abs(np.dot(reference_slice, observed_slice))
        correlation /= np.linalg.norm(reference_slice) * np.linalg.norm(observed_slice)
        candidate = (float(nrmse), -float(correlation), lag, float(gain))
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    nrmse, negative_correlation, lag, gain = best
    return {
        'lag': int(lag),
        'gain': gain,
        'correlation': -negative_correlation,
        'nrmse': nrmse,
    }


def sideband_metrics(output, sample_rate, frequencies):
    """Measure carrier and the two signed-frequency tone groups."""
    start = 2000
    count = min(20000, output.size - start)
    values = output[start:start + count].astype(np.complex128)
    carrier = abs(values.mean())
    values = values - values.mean()
    time = np.arange(count, dtype=np.float64) / sample_rate
    powers = []
    for sign in (1, -1):
        power = 0.0
        for frequency in frequencies:
            basis = np.exp(-1j * sign * 2 * math.pi * frequency * time)
            power += abs(np.dot(values, basis))**2
        powers.append(power)
    ratio_db = 10 * math.log10(max(powers) / min(powers))
    selected_sign = 1 if powers[0] > powers[1] else -1
    return {
        'carrier_amplitude': float(carrier),
        'sideband_suppression_db': float(ratio_db),
        'selected_frequency_sign': selected_sign,
    }


def demodulate_am(transmitter, audio):
    """Recover an AM message coherently and measure its sidebands."""
    output = stream_floats(transmitter, audio)
    expected = multitone(AM_RATE_HZ, output.size + 1000)
    recovered = output.real.astype(np.float64)
    alignment = best_real_alignment(expected, recovered, 500)
    result = {
        'samples': int(output.size),
        'output_rate_hz': int(AM_RATE_HZ),
        'recovery': alignment,
    }
    result.update(sideband_metrics(output, AM_RATE_HZ, (1000, 3000, 5000)))
    return result


def inverse_preemphasis(values, sample_rate, tau=75e-6):
    """Invert GNU Radio's documented bilinear pre-emphasis transfer function."""
    high_frequency = .925 * sample_rate / 2.0
    low_analog = 2 * sample_rate * math.tan((1.0 / tau) / (2 * sample_rate))
    high_analog = 2 * sample_rate * math.tan(
        (2 * math.pi * high_frequency) / (2 * sample_rate))
    low_k = -low_analog / (2 * sample_rate)
    high_k = -high_analog / (2 * sample_rate)
    zero = (1 + low_k) / (1 - low_k)
    pole = (1 + high_k) / (1 - high_k)
    b0 = (1 - low_k) / (1 - high_k)
    gain = abs(1 - pole) / (b0 * abs(1 - zero))
    numerator = np.asarray([gain * b0, -gain * b0 * zero])
    denominator = np.asarray([1.0, -pole])
    return signal.lfilter(denominator, numerator, values)


def demodulate_wbfm(transmitter, audio, sample_rate):
    """Recover WBFM audio with offline quadrature and de-emphasis filters."""
    output = stream_floats(transmitter, audio)
    sensitivity = 2 * math.pi * 75000.0 / sample_rate
    phase_step = np.angle(output[1:] * np.conj(output[:-1])) / sensitivity
    recovered_quad = inverse_preemphasis(phase_step.astype(np.float64),
                                         sample_rate)
    best = None
    if sample_rate == WBFM_RATE_HZ:
        candidates = (recovered_quad[phase::5] for phase in range(5))
    else:
        # The repaired rate is not an integer multiple of 44.1 kHz. Linear
        # interpolation is adequate for this independent 5 kHz-band test
        # message and does not reuse GNU Radio's rational-resampler taps.
        output_count = int(math.floor(
            recovered_quad.size * AUDIO_RATE_HZ / sample_rate))
        positions = (np.arange(output_count, dtype=np.float64) *
                     sample_rate / AUDIO_RATE_HZ)
        candidates = (np.interp(positions,
                                np.arange(recovered_quad.size),
                                recovered_quad),)
    for recovered in candidates:
        alignment = best_real_alignment(
            audio.astype(np.float64), recovered, 300)
        candidate = (alignment['nrmse'], alignment)
        if best is None or candidate[0] < best[0]:
            best = candidate
    alignment = best[1]
    guard = min(512, output.size // 10)
    magnitude = np.abs(output[guard:-guard])
    return {
        'samples': int(output.size),
        'output_rate_hz': int(sample_rate),
        'recovery': alignment,
        'envelope_relative_stddev': float(magnitude.std() / magnitude.mean()),
    }


def validate(report):
    """Enforce the clean-channel conformance thresholds."""
    for name in ('BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64'):
        result = report[name]
        assert result['symbol_errors'] == 0, (name, result)
        assert result['evm_rms'] < .005, (name, result)
    for name in ('GFSK', 'CPFSK'):
        result = report[name]
        assert result['bit_errors'] == 0, (name, result)
        assert result['mean_frequency_separation'] > .05, (name, result)
        assert result['envelope_relative_stddev'] < 1e-4, (name, result)
    wbfm = report['WBFM']
    assert wbfm['samples'] == 8192 * 5, wbfm
    assert wbfm['recovery']['correlation'] > .999, wbfm
    assert wbfm['recovery']['nrmse'] < .01, wbfm
    assert wbfm['envelope_relative_stddev'] < 1e-4, wbfm
    fixed_wbfm = report['WBFM-fixed']
    expected_samples = 8192 * FIXED_WBFM_RATE_HZ / AUDIO_RATE_HZ
    assert abs(fixed_wbfm['samples'] - expected_samples) < 64, fixed_wbfm
    assert fixed_wbfm['output_rate_hz'] == int(FIXED_WBFM_RATE_HZ), fixed_wbfm
    assert fixed_wbfm['recovery']['correlation'] > .999, fixed_wbfm
    assert fixed_wbfm['recovery']['nrmse'] < .02, fixed_wbfm
    # Band-limiting a wideband constant-envelope waveform before decimation
    # introduces bounded envelope ripple even though message recovery remains
    # accurate. This threshold retains margin around the measured 0.0475.
    assert fixed_wbfm['envelope_relative_stddev'] < .06, fixed_wbfm
    for name in ('AM-DSB', 'AM-SSB'):
        result = report[name]
        assert result['recovery']['correlation'] > .999, (name, result)
        assert result['recovery']['nrmse'] < .05, (name, result)
        assert .95 < result['carrier_amplitude'] < 1.05, (name, result)
    assert report['AM-DSB']['sideband_suppression_db'] < .1, report['AM-DSB']
    assert report['AM-SSB']['sideband_suppression_db'] > 40, report['AM-SSB']
    assert report['AM-SSB']['selected_frequency_sign'] == 1, report['AM-SSB']


def validate_parameter_sweep(transmitters, classes, constellations, bits):
    """Exercise digital transmitters at boundary and seeded interior settings."""
    rng = np.random.RandomState(BIT_SEED + 1)
    settings = [(2, .35), (8, .1), (8, .35), (8, .5), (12, .35)]
    settings.extend((int(rng.randint(4, 13)), float(rng.uniform(.2, .5)))
                    for unused in range(2))
    records = []
    for samples_per_symbol, excess_bandwidth in settings:
        for name in ('BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64'):
            output = stream_bytes(classes[name](
                samples_per_symbol, excess_bandwidth), bits)
            result = demodulate_linear(
                output, bits, constellations[name], samples_per_symbol,
                excess_bandwidth)
            assert result['symbol_errors'] == 0, (name, result)
            assert result['evm_rms'] < .05, (name, result)
            records.append({
                'modulation': name,
                'samples_per_symbol': samples_per_symbol,
                'excess_bandwidth': excess_bandwidth,
                'result': result,
            })

        output = stream_bytes(transmitters.transmitter_gfsk(
            samples_per_symbol, excess_bandwidth), bits)
        result = demodulate_binary_fsk(output, bits, samples_per_symbol)
        assert result['bit_errors'] == 0, (
            'GFSK', samples_per_symbol, excess_bandwidth, result)
        assert result['mean_frequency_separation'] > .05, (
            'GFSK', samples_per_symbol, excess_bandwidth, result)
        records.append({
            'modulation': 'GFSK',
            'samples_per_symbol': samples_per_symbol,
            'excess_bandwidth': excess_bandwidth,
            'result': result,
        })

    for samples_per_symbol in sorted(set(setting[0] for setting in settings)):
        output = stream_bytes(
            transmitters.transmitter_cpfsk(samples_per_symbol), bits)
        result = demodulate_binary_fsk(output, bits, samples_per_symbol)
        assert result['bit_errors'] == 0, ('CPFSK', result)
        assert result['mean_frequency_separation'] > .05, ('CPFSK', result)
        records.append({
            'modulation': 'CPFSK',
            'samples_per_symbol': samples_per_symbol,
            'excess_bandwidth': None,
            'result': result,
        })
    return records


def run_checks():
    """Run the clean-modulator checks and return their report."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo)
    sys.path.insert(0, repo)
    import transmitters

    rng = np.random.RandomState(BIT_SEED)
    bits = rng.randint(0, 2, 8192).astype(np.uint8)
    constellations = linear_constellations()
    classes = {
        'BPSK': transmitters.transmitter_bpsk,
        'QPSK': transmitters.transmitter_qpsk,
        '8PSK': transmitters.transmitter_8psk,
        'PAM4': transmitters.transmitter_pam4,
        'QAM16': transmitters.transmitter_qam16,
        'QAM64': transmitters.transmitter_qam64,
    }
    results = {}
    for name in ('BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64'):
        output = stream_bytes(classes[name](SAMPLES_PER_SYMBOL, EXCESS_BANDWIDTH), bits)
        results[name] = demodulate_linear(
            output, bits, constellations[name], SAMPLES_PER_SYMBOL,
            EXCESS_BANDWIDTH)

    for name, cls in (('GFSK', transmitters.transmitter_gfsk),
                      ('CPFSK', transmitters.transmitter_cpfsk)):
        output = stream_bytes(cls(SAMPLES_PER_SYMBOL), bits)
        results[name] = demodulate_binary_fsk(
            output, bits, SAMPLES_PER_SYMBOL)

    audio = multitone(AUDIO_RATE_HZ, 8192)
    results['WBFM'] = demodulate_wbfm(
        transmitters.transmitter_fm(), audio, WBFM_RATE_HZ)
    results['WBFM-fixed'] = demodulate_wbfm(
        transmitters.transmitter_fm_fixed(), audio, FIXED_WBFM_RATE_HZ)
    results['AM-DSB'] = demodulate_am(transmitters.transmitter_am(), audio)
    results['AM-SSB'] = demodulate_am(
        transmitters.transmitter_amssb_fixed(), audio)

    assert set(results) == {'BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16',
                            'QAM64', 'GFSK', 'CPFSK', 'WBFM', 'AM-DSB',
                            'AM-SSB', 'WBFM-fixed'}
    validate(results)
    parameter_sweep = validate_parameter_sweep(
        transmitters, classes, constellations, bits)
    report = {
        'schema': 2,
        'scope': 'clean transmitters without channel impairments',
        'bit_seed': BIT_SEED,
        'samples_per_symbol': SAMPLES_PER_SYMBOL,
        'excess_bandwidth': EXCESS_BANDWIDTH,
        'results': results,
        'parameter_sweep_seed': BIT_SEED + 1,
        'parameter_sweep': parameter_sweep,
    }
    return report


def test_clean_modulators():
    """Expose the clean-modulator conformance checks to pytest."""
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
    print('All clean-modulator conformance checks passed.', file=sys.stderr)


if __name__ == '__main__':
    main()
