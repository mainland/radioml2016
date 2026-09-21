#!/usr/bin/env python2.7
"""Measure transmitter startup responses and channel sample displacement.

The report separates message-alignment delay from an operational cold-start
guard. The guard is the end of the first-input-item response after discarding a
specified fraction of response energy in the tail. It is a reproducible
numerical criterion, not an assertion that an IIR has finite support.
"""
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
AUDIO_RATE_HZ = 44100.0
WBFM_RATE_HZ = 220500.0
SAMPLES_PER_SYMBOL = 8
EXCESS_BANDWIDTH = .35
CHANNEL_SEED = 0x1337
WINDOW_LENGTH = 128
FIRST_OFFSET_MIN = 50
FIRST_OFFSET_MAX = 500
# Float32 phase accumulation leaves a measured GFSK numerical tail containing
# about 4e-8 of response energy after the 39-tap shaping pulse. A 1e-7 cutoff
# retains the physical response without calling that arithmetic floor memory.
TAIL_ENERGY_FRACTION = 1e-7
CHANNEL_IMPULSE_POSITIONS = (64, 256, 512, 2048, 8192)


def sha256(path):
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def stream_bytes(transmitter, values):
    """Run a byte-input transmitter and return complex output samples."""
    flowgraph = gr.top_block()
    source = blocks.vector_source_b(values.tolist(), False)
    sink = blocks.vector_sink_c()
    flowgraph.connect(source, transmitter, sink)
    flowgraph.run()
    output = np.asarray(sink.data(), dtype=np.complex64)
    assert output.size and np.isfinite(output).all()
    return output


def stream_floats(transmitter, values):
    """Run a float-input transmitter and return complex output samples."""
    flowgraph = gr.top_block()
    source = blocks.vector_source_f(values.tolist(), False)
    sink = blocks.vector_sink_c()
    flowgraph.connect(source, transmitter, sink)
    flowgraph.run()
    output = np.asarray(sink.data(), dtype=np.complex64)
    assert output.size and np.isfinite(output).all()
    return output


def stream_complex(block, values):
    """Run a complex-input block and return complex output samples."""
    flowgraph = gr.top_block()
    source = blocks.vector_source_c(values.tolist(), False)
    sink = blocks.vector_sink_c()
    flowgraph.connect(source, block, sink)
    flowgraph.run()
    output = np.asarray(sink.data(), dtype=np.complex64)
    assert output.size and np.isfinite(output).all()
    return output


def response_metrics(values, coordinate_offset=0,
                     tail_energy_fraction=TAIL_ENERGY_FRACTION):
    """Summarize the delay and operational support of one response.

    Args:
        values: One-dimensional real or complex response samples.
        coordinate_offset: Coordinate assigned to ``values[0]``.
        tail_energy_fraction: Maximum energy omitted after the reported end.

    Returns:
        JSON-compatible delay and energy-support measurements.

    Raises:
        ValueError: If the response or tolerance is invalid.
    """
    values = np.asarray(values)
    if values.ndim != 1 or not values.size or not np.isfinite(values).all():
        raise ValueError('response must be a finite, nonempty vector')
    if not 0 < tail_energy_fraction < 1:
        raise ValueError('tail energy fraction must lie strictly between 0 and 1')
    power = np.abs(values.astype(np.complex128))**2
    total = float(power.sum())
    if not total > 0:
        raise ValueError('response has zero energy')
    cumulative = np.cumsum(power)
    peak_index = int(np.argmax(power))
    end_index = int(np.searchsorted(
        cumulative, (1.0 - tail_energy_fraction) * total))
    coordinates = np.arange(values.size, dtype=np.float64) + coordinate_offset
    centroid = float(np.dot(coordinates, power) / total)
    return {
        'sample_count': int(values.size),
        'peak_sample': int(peak_index + coordinate_offset),
        'energy_centroid_sample': centroid,
        'operational_end_sample': int(end_index + coordinate_offset),
        'tail_energy_fraction': float(tail_energy_fraction),
        'total_energy': total,
        'peak_power': float(power[peak_index]),
    }


def early_offset_count(guard, minimum=FIRST_OFFSET_MIN,
                       maximum=FIRST_OFFSET_MAX):
    """Count inclusive uniform offsets strictly before ``guard``."""
    if minimum > maximum:
        raise ValueError('minimum offset exceeds maximum offset')
    return max(0, min(maximum + 1, int(math.ceil(guard))) - minimum)


def sampler_assessment(guard):
    """Describe how a startup guard intersects the historical first offset."""
    count = early_offset_count(guard)
    total = FIRST_OFFSET_MAX - FIRST_OFFSET_MIN + 1
    return {
        'earliest_operational_offset': int(math.ceil(guard)),
        'too_early_offset_count': int(count),
        'possible_offset_count': int(total),
        'too_early_probability': float(count) / total,
    }


def changed_first_symbol(width, count=4096):
    """Return two bit streams that differ only in their first symbol."""
    baseline = np.zeros(count, dtype=np.uint8)
    changed = baseline.copy()
    changed[width - 1] = 1
    return baseline, changed


def differentiated_phase(output, sensitivity):
    """Recover the real frequency-control stream from complex FM samples."""
    return (np.angle(output[1:] * np.conj(output[:-1])) /
            float(sensitivity))


def analyze_linear_transmitter(name, transmitter_class, width,
                               samples_per_symbol=SAMPLES_PER_SYMBOL,
                               excess_bandwidth=EXCESS_BANDWIDTH):
    """Measure a mapper/RRC transmitter with a one-symbol difference."""
    baseline, changed = changed_first_symbol(width)
    reference = stream_bytes(transmitter_class(
        samples_per_symbol, excess_bandwidth), baseline)
    observed = stream_bytes(transmitter_class(
        samples_per_symbol, excess_bandwidth), changed)
    count = min(reference.size, observed.size)
    response = observed[:count] - reference[:count]
    metrics = response_metrics(response)
    metrics['nominal_rrc_group_delay_samples'] = float(
        5.5 * samples_per_symbol**2)
    return {
        'modulation': name,
        'response_quantity': 'complex output difference for first symbol',
        'samples_per_symbol': int(samples_per_symbol),
        'excess_bandwidth': float(excess_bandwidth),
        'input_item_period_output_samples': int(samples_per_symbol),
        'response': metrics,
        'sampler_without_channel': sampler_assessment(
            metrics['operational_end_sample']),
    }


def analyze_fsk_transmitter(name, transmitter_class,
                            samples_per_symbol=SAMPLES_PER_SYMBOL,
                            excess_bandwidth=EXCESS_BANDWIDTH):
    """Measure an FSK transmitter through its differentiated phase."""
    baseline, changed = changed_first_symbol(1)
    if name == 'GFSK':
        reference_modulator = transmitter_class(
            samples_per_symbol, excess_bandwidth)
        observed_modulator = transmitter_class(
            samples_per_symbol, excess_bandwidth)
    else:
        reference_modulator = transmitter_class(samples_per_symbol)
        observed_modulator = transmitter_class(samples_per_symbol)
    reference = stream_bytes(reference_modulator, baseline)
    observed = stream_bytes(observed_modulator, changed)
    count = min(reference.size, observed.size)
    reference_frequency = differentiated_phase(reference[:count], 1.0)
    observed_frequency = differentiated_phase(observed[:count], 1.0)
    response = observed_frequency - reference_frequency
    if name == 'GFSK':
        # GNU Radio convolves 4*SPS Gaussian taps with an SPS-sample
        # rectangle. The resulting 5*SPS-1 taps are the complete physical
        # frequency-pulse response. Later differences are float phase-
        # accumulator and lookup-table noise, not filter memory.
        physical_response_length = 5 * samples_per_symbol - 1
    else:
        physical_response_length = samples_per_symbol
    response = response[:physical_response_length]
    metrics = response_metrics(response, coordinate_offset=1)
    metrics['source_response_length_samples'] = physical_response_length
    return {
        'modulation': name,
        'response_quantity': 'phase-increment difference for first bit',
        'samples_per_symbol': int(samples_per_symbol),
        'excess_bandwidth': (float(excess_bandwidth)
                             if name == 'GFSK' else None),
        'input_item_period_output_samples': int(samples_per_symbol),
        'response': metrics,
        'sampler_without_channel': sampler_assessment(
            metrics['operational_end_sample']),
    }


def analyze_am_transmitter(name, transmitter_class):
    """Measure the linear message response of an AM transmitter."""
    baseline = np.zeros(4096, dtype=np.float32)
    changed = baseline.copy()
    changed[0] = .1
    reference = stream_floats(transmitter_class(), baseline)
    observed = stream_floats(transmitter_class(), changed)
    count = min(reference.size, observed.size)
    response = (observed[:count] - reference[:count]) / .1
    metrics = response_metrics(response)
    return {
        'modulation': name,
        'response_quantity': 'complex message-path impulse response',
        'input_item_period_output_samples': SAMPLE_RATE_HZ / AUDIO_RATE_HZ,
        'response': metrics,
        'sampler_without_channel': sampler_assessment(
            metrics['operational_end_sample']),
    }


def analyze_wbfm_transmitter(name, transmitter_class, output_rate_hz):
    """Measure the message filter response before FM phase integration."""
    baseline = np.zeros(4096, dtype=np.float32)
    changed = baseline.copy()
    changed[0] = .01
    reference = stream_floats(transmitter_class(), baseline)
    observed = stream_floats(transmitter_class(), changed)
    count = min(reference.size, observed.size)
    sensitivity = 2 * math.pi * 75000.0 / output_rate_hz
    response = (differentiated_phase(observed[:count], sensitivity) -
                differentiated_phase(reference[:count], sensitivity)) / .01
    metrics = response_metrics(response, coordinate_offset=1)
    return {
        'modulation': name,
        'response_quantity': 'demodulated frequency response to first audio item',
        'input_item_period_output_samples': output_rate_hz / AUDIO_RATE_HZ,
        'output_rate_hz': int(output_rate_hz),
        'response': metrics,
        'sampler_without_channel': sampler_assessment(
            metrics['operational_end_sample']),
    }


def make_channel(control):
    """Construct a noise-free channel control with dataset parameters."""
    sro_std_dev = .01 if control in ('sro', 'combined') else 0.0
    sro_max_dev = 50 if control in ('sro', 'combined') else 0.0
    cfo_std_dev = .01 if control in ('cfo', 'combined') else 0.0
    cfo_max_dev = .5e3 if control in ('cfo', 'combined') else 0.0
    if control in ('fading', 'combined'):
        doppler_frequency = 1
        k_factor = 4
        delays = [0.0, .9, 1.7]
        magnitudes = [1.0, .8, .3]
    else:
        doppler_frequency = 0
        k_factor = 1e6
        delays = [0.0]
        magnitudes = [1.0]
    return channels.dynamic_channel_model(
        SAMPLE_RATE_HZ, sro_std_dev, sro_max_dev, cfo_std_dev,
        cfo_max_dev, 8, doppler_frequency, True, k_factor, delays,
        magnitudes, 8, 0.0, CHANNEL_SEED)


def analyze_channel_impulse(control, input_index):
    """Measure one local channel impulse response at a specified sample age."""
    values = np.zeros(input_index + 1024, dtype=np.complex64)
    values[input_index] = 1.0
    output = stream_complex(make_channel(control), values)
    metrics = response_metrics(output)
    denominator = output.astype(np.complex128).sum()
    if abs(denominator) > 1e-12:
        coordinates = np.arange(output.size, dtype=np.float64) - input_index
        dc_delay = float(np.real(np.dot(coordinates, output) / denominator))
    else:
        dc_delay = None
    return {
        'input_index': int(input_index),
        'output_sample_count': int(output.size),
        'peak_delay_samples': int(metrics['peak_sample'] - input_index),
        'energy_centroid_delay_samples': float(
            metrics['energy_centroid_sample'] - input_index),
        'operational_end_delay_samples': int(
            metrics['operational_end_sample'] - input_index),
        'local_dc_phase_slope_delay_samples': dc_delay,
        'response_energy': metrics['total_energy'],
    }


def analyze_channels():
    """Measure deterministic local responses for all channel controls."""
    result = {}
    for control in ('baseline', 'cfo', 'sro', 'fading', 'combined'):
        measurements = [analyze_channel_impulse(control, position)
                        for position in CHANNEL_IMPULSE_POSITIONS]
        result[control] = {
            'noise_amplitude': 0.0,
            'measurements': measurements,
            'maximum_peak_delay_samples': max(
                row['peak_delay_samples'] for row in measurements),
            'minimum_peak_delay_samples': min(
                row['peak_delay_samples'] for row in measurements),
            'maximum_operational_end_delay_samples': max(
                row['operational_end_delay_samples'] for row in measurements),
            'minimum_operational_end_delay_samples': min(
                row['operational_end_delay_samples'] for row in measurements),
        }
    # Additive noise is memoryless. Its deterministic timing path is the same
    # as the baseline control, so an impulse measured with nonzero noise would
    # obscure rather than identify delay.
    result['awgn'] = {
        'noise_amplitude': 'memoryless; omitted from impulse measurement',
        'timing_equivalent_to': 'baseline',
        'measurements': result['baseline']['measurements'],
        'maximum_peak_delay_samples':
            result['baseline']['maximum_peak_delay_samples'],
        'minimum_peak_delay_samples':
            result['baseline']['minimum_peak_delay_samples'],
        'maximum_operational_end_delay_samples':
            result['baseline']['maximum_operational_end_delay_samples'],
        'minimum_operational_end_delay_samples':
            result['baseline']['minimum_operational_end_delay_samples'],
    }
    return result


def cascade_assessments(transmitters, channel_controls):
    """Combine operational transmitter and channel response-end measurements."""
    rows = []
    for transmitter in transmitters:
        transmitter_peak = transmitter['response']['peak_sample']
        transmitter_end = transmitter['response']['operational_end_sample']
        for control in ('baseline', 'awgn', 'cfo', 'sro', 'fading', 'combined'):
            channel_peak = channel_controls[control][
                'maximum_peak_delay_samples']
            channel_end = channel_controls[control][
                'maximum_operational_end_delay_samples']
            latest_peak = transmitter_peak + channel_peak
            guard = transmitter_end + channel_end
            peak_count = early_offset_count(latest_peak)
            total = FIRST_OFFSET_MAX - FIRST_OFFSET_MIN + 1
            row = {
                'modulation': transmitter['modulation'],
                'channel_control': control,
                'transmitter_peak_sample': int(transmitter_peak),
                'channel_maximum_peak_delay_samples': int(channel_peak),
                'latest_measured_peak_offset': int(latest_peak),
                'starts_before_peak_offset_count': int(peak_count),
                'starts_before_peak_probability': float(peak_count) / total,
                'transmitter_operational_end_sample': int(transmitter_end),
                'channel_maximum_operational_end_delay_samples': int(channel_end),
            }
            row.update(sampler_assessment(guard))
            rows.append(row)
    return rows


def settled_window_policy(transmitters):
    """Compare the optional repair guard with measured combined responses."""
    from window_policy import settled_window_guard

    rows = []
    for transmitter in transmitters:
        report_name = transmitter['modulation']
        modulation = 'WBFM' if report_name == 'WBFM-fixed' else report_name
        fixed_wbfm = report_name == 'WBFM-fixed'
        fixed_am_ssb = report_name == 'AM-SSB'
        guard = settled_window_guard(
            modulation, transmitter.get('samples_per_symbol', 0),
            fixed_am_ssb, fixed_wbfm)
        rows.append({
            'modulation': report_name,
            'settling_guard_samples': int(guard),
            'fixed_am_ssb': bool(fixed_am_ssb),
            'fixed_wbfm': bool(fixed_wbfm),
        })
    return rows


def analyze_transmitters():
    """Measure all dataset transmitter response delays."""
    import transmitters

    linear = (
        ('BPSK', transmitters.transmitter_bpsk, 1),
        ('QPSK', transmitters.transmitter_qpsk, 2),
        ('8PSK', transmitters.transmitter_8psk, 3),
        ('PAM4', transmitters.transmitter_pam4, 2),
        ('QAM16', transmitters.transmitter_qam16, 4),
        ('QAM64', transmitters.transmitter_qam64, 6),
    )
    results = [analyze_linear_transmitter(name, cls, width)
               for name, cls, width in linear]
    results.append(analyze_fsk_transmitter(
        'GFSK', transmitters.transmitter_gfsk))
    results.append(analyze_fsk_transmitter(
        'CPFSK', transmitters.transmitter_cpfsk))
    results.append(analyze_wbfm_transmitter(
        'WBFM', transmitters.transmitter_fm, WBFM_RATE_HZ))
    results.append(analyze_am_transmitter(
        'AM-DSB', transmitters.transmitter_am))
    am_ssb = analyze_am_transmitter(
        'AM-SSB', transmitters.transmitter_amssb_fixed)
    am_ssb['delay_basis'] = (
        'fixed-oscillator structural proxy; the historical zero-frequency '
        'sine suppresses the message before the shared Hilbert filter')
    results.append(am_ssb)
    results.append(analyze_wbfm_transmitter(
        'WBFM-fixed', transmitters.transmitter_fm_fixed,
        SAMPLE_RATE_HZ))
    return results


def analyze_parameter_sweep():
    """Measure digital delay at the supported SPS and EBW boundaries."""
    import transmitters

    linear = (
        ('BPSK', transmitters.transmitter_bpsk, 1),
        ('QPSK', transmitters.transmitter_qpsk, 2),
        ('8PSK', transmitters.transmitter_8psk, 3),
        ('PAM4', transmitters.transmitter_pam4, 2),
        ('QAM16', transmitters.transmitter_qam16, 4),
        ('QAM64', transmitters.transmitter_qam64, 6),
    )
    rows = []
    for samples_per_symbol in (2, 8, 12):
        for excess_bandwidth in (.1, .5):
            rows.extend(analyze_linear_transmitter(
                name, cls, width, samples_per_symbol, excess_bandwidth)
                        for name, cls, width in linear)
            rows.append(analyze_fsk_transmitter(
                'GFSK', transmitters.transmitter_gfsk,
                samples_per_symbol, excess_bandwidth))
        rows.append(analyze_fsk_transmitter(
            'CPFSK', transmitters.transmitter_cpfsk,
            samples_per_symbol, EXCESS_BANDWIDTH))
    return rows


def run_analysis():
    """Run the complete deterministic delay analysis and return its report."""
    script_path = os.path.abspath(__file__)
    repository = os.path.dirname(os.path.dirname(script_path))
    os.chdir(repository)
    sys.path.insert(0, repository)
    transmitters = analyze_transmitters()
    channel_controls = analyze_channels()
    return {
        'schema': 'radioml2016-filter-delay-analysis',
        'schema_version': 1,
        'runtime': {
            'python_version': sys.version,
            'numpy_version': np.__version__,
            'gnuradio_version': gr.version(),
            'script_sha256': sha256(script_path),
        },
        'sample_coordinate': 'zero-based post-block output samples',
        'sample_rate_hz': int(SAMPLE_RATE_HZ),
        'window_length': WINDOW_LENGTH,
        'historical_first_offset': {
            'minimum': FIRST_OFFSET_MIN,
            'maximum': FIRST_OFFSET_MAX,
            'distribution': 'inclusive discrete uniform from random.randint',
        },
        'operational_support_definition': {
            'tail_energy_fraction': TAIL_ENERGY_FRACTION,
            'meaning': (
                'The operational end is the first response index whose '
                'cumulative energy reaches 1-tail_energy_fraction. It is a '
                'numerical startup criterion, not exact support for an IIR.'),
        },
        'transmitters': transmitters,
        'digital_parameter_sweep': analyze_parameter_sweep(),
        'channel_controls': channel_controls,
        'cascade_sampler_assessments': cascade_assessments(
            transmitters, channel_controls),
        'optional_repair_policy': {
            'name': 'settled windows',
            'first_offset_distribution': (
                'inclusive discrete uniform from guard through guard+450'),
            'guards': settled_window_policy(transmitters),
        },
        'interpretation_limit': (
            'Pulse peak, energy centroid, and startup guard are different '
            'quantities. Channel impulse responses are local measurements in '
            'a time-varying system. Adding operational response ends is a '
            'conservative diagnostic, not an exact group-delay law for every '
            'signal or channel realization.'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='write the JSON report to this path')
    args = parser.parse_args()
    report = run_analysis()
    content = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.output:
        with open(args.output, 'w') as destination:
            destination.write(content)
        print('Wrote ' + args.output, file=sys.stderr)
    else:
        print(content, end='')


if __name__ == '__main__':
    main()
