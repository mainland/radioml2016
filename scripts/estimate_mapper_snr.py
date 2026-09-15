#!/usr/bin/env python2.7
"""Estimate actual SNR under three historical mapper hypotheses.

Only load pickle files from trusted sources. Pickle deserialization executes
instructions embedded in the input. The estimator uses out-of-band spectral
power, so neither the historical noise RNG state nor the window's absolute
scale is required.
"""
from __future__ import print_function

import argparse
import cPickle
import hashlib
import json
import math
import os
import sys

import numpy as np

DEFAULT_MODULATIONS = ('BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64')
DEFAULT_SNRS = tuple(range(-20, 20, 2))


DEFAULT_OOB_CUTOFF = 0.15
DEFAULT_FIT_MIN_SNR = -8.0
DEFAULT_FIT_MAX_SNR = 25.0
EXPECTED_LABEL_SLOPE = 2.0
PERCENTILES = (10, 25, 50, 75, 90)
MAPPER_MODEL_REVISIONS = {
    'no_normalization': '463f9e94f5ea45e5be64bae06291423ead3b70f2',
    'pre_fix': '52383e2832a86feb452ddd80928bce69147f01c0',
    'post_fix': '15e71bf01be68d427ed9f37966b83efc1180a1d5',
}


def sha256(path):
    """Return the SHA-256 digest of a file.

    Args:
        path: File-system path.

    Returns:
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path):
    """Load and validate a trusted RadioML pickle.

    Args:
        path: Trusted Python 2 pickle with RadioML dictionary keys.

    Returns:
        Dictionary mapping ``(modulation, snr)`` to float32 window arrays.

    Raises:
        ValueError: If a key or array does not have the expected form.
    """
    with open(path, 'rb') as source:
        dataset = cPickle.load(source)
    if not isinstance(dataset, dict) or not dataset:
        raise ValueError('%s is not a nonempty dataset dictionary' % path)
    for key, values in dataset.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise ValueError('%s contains an invalid key: %r' % (path, key))
        values = np.asarray(values)
        if (values.dtype != np.float32 or values.ndim != 3 or
                values.shape[1:] != (2, 128)):
            raise ValueError(
                '%s key %r must be float32[N, 2, 128]' % (path, key))
        if values.shape[0] < 4 or not np.isfinite(values).all():
            raise ValueError('%s key %r has too few or nonfinite windows' %
                             (path, key))
    return dataset


def select_windows(values, maximum):
    """Select at most ``maximum`` windows at deterministic, even intervals."""
    if maximum < 4:
        raise ValueError('--max-windows must be at least 4')
    if len(values) <= maximum:
        return values
    indices = np.asarray(
        np.linspace(0, len(values) - 1, maximum), dtype=np.intp)
    return values[indices]


def complex_windows(values):
    """Convert ``float32[N, 2, 128]`` I/Q arrays to complex128 windows."""
    values = np.asarray(values)
    if (values.dtype != np.float32 or values.ndim != 3 or
            values.shape[1:] != (2, 128) or not np.isfinite(values).all()):
        raise ValueError(
            'expected finite float32 windows with shape [N, 2, 128]')
    result = values[:, 0, :].astype(np.complex128)
    result += 1j * values[:, 1, :]
    energy = np.sum(np.abs(result) ** 2, axis=1)
    if np.any(energy <= 0):
        raise ValueError('windows must have nonzero energy')
    return result


def constellation_points():
    """Return gr-mapper's raw constellation points in source order."""
    square_16 = [complex(real, imaginary)
                 for imaginary in (3, 1, -1, -3)
                 for real in (-3, -1, 1, 3)]
    square_64 = [complex(real, imaginary)
                 for imaginary in (7, 5, 3, 1, -1, -3, -5, -7)
                 for real in (-7, -5, -3, -1, 1, 3, 5, 7)]
    return {
        'BPSK': (1, -1),
        'QPSK': (np.exp(1j * np.pi / 4.0),
                 np.exp(3j * np.pi / 4.0),
                 np.exp(5j * np.pi / 4.0),
                 np.exp(7j * np.pi / 4.0)),
        '8PSK': tuple(np.exp(2j * np.pi * index / 8.0)
                      for index in range(8)),
        'PAM4': (-3, -1, 3, 1),
        'QAM16': square_16,
        'QAM64': square_64,
    }


def mapper_gain_ratios():
    """Return pre-fix/post-fix mapper amplitude ratios by modulation.

    The buggy accumulator kept only the final constellation magnitude instead
    of their sum. Both versions multiply by the same constellation size, so
    their ratio is ``sum(abs(points)) / abs(points[-1])``.
    """
    points = constellation_points()
    return dict(
        (name, float(sum(abs(point) for point in constellation) /
                     abs(constellation[-1])))
        for name, constellation in points.items())


def normalization_model_powers_db():
    """Return theoretical mean symbol power for three mapper histories.

    ``no_normalization`` is the behavior before commit 943277c (February 1,
    2016). ``pre_fix`` is that commit's last-point accumulator bug.
    ``post_fix`` is the corrected average-magnitude normalization from commit
    15e71bf (October 11, 2016).
    """
    models = dict((name, {}) for name in
                  ('no_normalization', 'pre_fix', 'post_fix'))
    for modulation, constellation in constellation_points().items():
        values = np.asarray(constellation, dtype=np.complex128)
        size = float(len(values))
        scales = {
            'no_normalization': 1.0,
            'pre_fix': size / abs(values[-1]),
            'post_fix': size / np.sum(np.abs(values)),
        }
        for name, scale in scales.items():
            power = np.mean(np.abs(values * scale) ** 2)
            models[name][modulation] = float(10.0 * np.log10(power))
    return models


def estimate_window_powers(values, oob_cutoff=DEFAULT_OOB_CUTOFF):
    """Estimate total, noise, and signal-to-noise powers for each window.

    Digital signals use an RRC pulse with nominal one-sided band edge 0.084375
    cycles/sample at eight samples/symbol and excess bandwidth 0.35. The
    historical carrier offset is at most 0.0025 cycles/sample. Frequencies at
    or beyond the default 0.15 cutoff therefore provide a conservative noise
    region. For complex Gaussian noise, FFT-bin power is exponential, whose
    median is its mean times ``log(2)``.

    Args:
        values: ``float32[N, 2, 128]`` I/Q windows.
        oob_cutoff: Absolute normalized frequency at which noise bins begin.

    Returns:
        Dictionary of one-dimensional arrays, one entry per input window.
    """
    if not 0.1 <= oob_cutoff < 0.5:
        raise ValueError('out-of-band cutoff must be in [0.1, 0.5)')
    windows = complex_windows(values)
    sample_count = windows.shape[1]
    taper = np.hanning(sample_count)
    taper_energy = float(np.sum(taper ** 2))
    frequencies = np.fft.fftshift(np.fft.fftfreq(sample_count))
    noise_bins = np.abs(frequencies) >= oob_cutoff
    if np.sum(noise_bins) < 8:
        raise ValueError('out-of-band cutoff leaves fewer than eight bins')
    spectrum = np.fft.fftshift(
        np.fft.fft(windows * taper[None, :], axis=1), axes=1)
    bin_power = np.abs(spectrum[:, noise_bins]) ** 2
    noise_power = (np.median(bin_power, axis=1) /
                   (math.log(2.0) * taper_energy))
    total_power = np.mean(np.abs(windows) ** 2, axis=1)
    signal_to_noise = total_power / noise_power - 1.0
    if (not np.isfinite(noise_power).all() or
            not np.isfinite(signal_to_noise).all() or
            np.any(noise_power <= 0)):
        raise ValueError('spectral power estimation produced invalid values')
    return {
        'total_power': total_power,
        'noise_power': noise_power,
        'signal_to_noise_linear': signal_to_noise,
        'noise_to_total': noise_power / total_power,
    }


def percentile_dict(values):
    """Return selected percentiles as a JSON-ready dictionary."""
    quantiles = np.percentile(values, PERCENTILES)
    return dict((str(percentile), float(quantiles[index]))
                for index, percentile in enumerate(PERCENTILES))


def summarize_powers(estimates):
    """Summarize per-window estimates without discarding negative residuals."""
    ratio = estimates['signal_to_noise_linear']
    median_ratio = float(np.median(ratio))
    snr_db = None
    if median_ratio > 0:
        snr_db = float(10.0 * np.log10(median_ratio))
    return {
        'window_count': int(len(ratio)),
        'median_snr_db': snr_db,
        'median_signal_to_noise_linear': median_ratio,
        'positive_signal_fraction': float(np.mean(ratio > 0)),
        'noise_to_total_percentiles': percentile_dict(
            estimates['noise_to_total']),
        'signal_to_noise_linear_percentiles': percentile_dict(ratio),
    }


def fit_snr_curve(rows, minimum=DEFAULT_FIT_MIN_SNR,
                  maximum=DEFAULT_FIT_MAX_SNR):
    """Fit the label-to-estimated-SNR curve in the usable dynamic range.

    The generator's noise amplitude is ``10**(-label/10)``, so noise power
    changes by two dB for every one-dB label step. The fixed-slope intercept is
    the primary comparison; an unconstrained slope is a diagnostic.
    """
    usable = [row for row in rows
              if row['median_snr_db'] is not None and
              minimum <= row['median_snr_db'] <= maximum]
    if not usable:
        return {
            'point_count': 0,
            'snr_labels_db': [],
            'fixed_slope_db_per_label_db': EXPECTED_LABEL_SLOPE,
            'fixed_slope_intercept_db': None,
            'fitted_slope_db_per_label_db': None,
            'fitted_intercept_db': None,
        }
    labels = np.asarray([row['snr_db'] for row in usable], dtype=np.float64)
    estimates = np.asarray(
        [row['median_snr_db'] for row in usable], dtype=np.float64)
    fixed_intercept = float(np.median(
        estimates - EXPECTED_LABEL_SLOPE * labels))
    fitted_slope = None
    fitted_intercept = None
    if len(usable) >= 2:
        fitted_slope, fitted_intercept = np.polyfit(labels, estimates, 1)
        fitted_slope = float(fitted_slope)
        fitted_intercept = float(fitted_intercept)
    return {
        'point_count': len(usable),
        'snr_labels_db': [int(value) for value in labels],
        'fixed_slope_db_per_label_db': EXPECTED_LABEL_SLOPE,
        'fixed_slope_intercept_db': fixed_intercept,
        'fitted_slope_db_per_label_db': fitted_slope,
        'fitted_intercept_db': fitted_intercept,
    }


def compare_intercepts(curves, expected_gain_db):
    """Compare original and candidate fixed-slope curve intercepts."""
    intercepts = dict(
        (name, curve['fixed_slope_intercept_db'])
        for name, curve in curves.items())
    required = ('original', 'pre_fix', 'post_fix')
    if any(intercepts[name] is None for name in required):
        return {
            'candidate_intercept_shift_db': None,
            'expected_candidate_shift_db': expected_gain_db,
            'candidate_shift_error_db': None,
            'original_to_pre_fix_db': None,
            'original_to_post_fix_db': None,
            'closer_candidate': 'insufficient_dynamic_range',
        }
    candidate_shift = intercepts['pre_fix'] - intercepts['post_fix']
    pre_distance = abs(intercepts['original'] - intercepts['pre_fix'])
    post_distance = abs(intercepts['original'] - intercepts['post_fix'])
    if pre_distance < post_distance:
        closer = 'pre_fix'
    elif post_distance < pre_distance:
        closer = 'post_fix'
    else:
        closer = 'tie'
    result = {
        'candidate_intercept_shift_db': float(candidate_shift),
        'expected_candidate_shift_db': float(expected_gain_db),
        'candidate_shift_error_db': float(candidate_shift - expected_gain_db),
        'original_to_pre_fix_db': float(pre_distance),
        'original_to_post_fix_db': float(post_distance),
        'closer_candidate': closer,
    }
    if 'no_normalization' in intercepts:
        direct = intercepts['no_normalization']
        result['original_to_no_normalization_db'] = None
        result['original_minus_no_normalization_db'] = None
        if direct is not None:
            result['original_to_no_normalization_db'] = float(
                abs(intercepts['original'] - direct))
            result['original_minus_no_normalization_db'] = float(
                intercepts['original'] - direct)
    return result


def fit_normalization_models(modulations):
    """Fit mapper-normalization power patterns with one global offset.

    A common signal/noise scale mismatch moves every modulation intercept by
    the same amount. Fitting and removing that offset lets the relative raw
    constellation powers distinguish no normalization from the two later
    implementations.
    """
    theoretical = normalization_model_powers_db()
    result = {}
    dataset_names = ['original', 'pre_fix', 'post_fix']
    if modulations and 'no_normalization' in modulations[0]['curves']:
        dataset_names.insert(1, 'no_normalization')
    for dataset_name in dataset_names:
        observed = dict(
            (row['modulation'],
             row['curves'][dataset_name]['fixed_slope_intercept_db'])
            for row in modulations
            if row['curves'][dataset_name][
                'fixed_slope_intercept_db'] is not None)
        fits = {}
        for model_name, expected in theoretical.items():
            names = [name for name in DEFAULT_MODULATIONS
                     if name in observed and name in expected]
            differences = np.asarray(
                [observed[name] - expected[name] for name in names])
            offset = float(np.median(differences))
            residuals = dict(
                (name, float(observed[name] -
                             (expected[name] + offset)))
                for name in names)
            rmse = float(np.sqrt(np.mean(
                np.asarray(list(residuals.values())) ** 2)))
            fits[model_name] = {
                'global_offset_db': offset,
                'residuals_db': residuals,
                'rmse_db': rmse,
                'modulation_count': len(names),
            }
        best = min(fits, key=lambda name: fits[name]['rmse_db'])
        result[dataset_name] = {
            'best_model_by_rmse': best,
            'fits': fits,
        }
    return {
        'theoretical_mean_symbol_power_db': theoretical,
        'datasets': result,
        'method': (
            'For each normalization model, fit one median global intercept '
            'offset across modulations and compute the RMS residual. This '
            'uses relative modulation powers, so a common channel or noise '
            'scale mismatch does not select the model.'),
    }


def compare_direct_candidate(modulations):
    """Compare original and direct no-normalization curve intercepts.

    Returns:
        JSON-ready common difference and per-modulation residuals, or ``None``
        when no direct candidate was supplied.
    """
    if not modulations or 'no_normalization' not in modulations[0]['curves']:
        return None
    differences = {}
    for row in modulations:
        original = row['curves']['original']['fixed_slope_intercept_db']
        candidate = row['curves']['no_normalization'][
            'fixed_slope_intercept_db']
        if original is not None and candidate is not None:
            differences[row['modulation']] = float(original - candidate)
    if not differences:
        return {
            'modulation_count': 0,
            'original_minus_candidate_offset_db': None,
            'residuals_db': {},
            'rmse_db': None,
        }
    offset = float(np.median(list(differences.values())))
    residuals = dict((name, float(value - offset))
                     for name, value in differences.items())
    rmse = float(np.sqrt(np.mean(
        np.asarray(list(residuals.values())) ** 2)))
    return {
        'modulation_count': len(differences),
        'original_minus_candidate_offset_db': offset,
        'residuals_db': residuals,
        'rmse_db': rmse,
        'method': (
            'Median original-minus-candidate fixed-slope intercept across '
            'modulations; RMS residual is computed after removing that '
            'common difference.'),
    }


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', help='trusted distributed dataset pickle')
    parser.add_argument('pre_fix', help='generated pre-fix mapper pickle')
    parser.add_argument('post_fix', help='generated post-fix mapper pickle')
    parser.add_argument('--no-normalization',
                        help='generated direct no-normalization mapper pickle')
    parser.add_argument('--output', required=True, help='JSON report path')
    parser.add_argument('--expected-original-sha256',
                        help='reject an unexpected distributed dataset file')
    parser.add_argument('--modulations', nargs='+',
                        choices=DEFAULT_MODULATIONS,
                        default=list(DEFAULT_MODULATIONS))
    parser.add_argument('--snrs', nargs='+', type=int,
                        default=list(DEFAULT_SNRS))
    parser.add_argument('--max-windows', type=int, default=1000,
                        help='maximum evenly selected windows per key')
    parser.add_argument('--oob-cutoff', type=float, default=DEFAULT_OOB_CUTOFF,
                        help='absolute normalized frequency for noise bins')
    parser.add_argument('--fit-min-snr', type=float,
                        default=DEFAULT_FIT_MIN_SNR)
    parser.add_argument('--fit-max-snr', type=float,
                        default=DEFAULT_FIT_MAX_SNR)
    return parser.parse_args()


def main():
    """Estimate SNR curves and write a provenance-bearing comparison."""
    args = parse_args()
    if args.fit_min_snr >= args.fit_max_snr:
        raise ValueError('--fit-min-snr must be less than --fit-max-snr')
    paths = {
        'original': args.original,
        'pre_fix': args.pre_fix,
        'post_fix': args.post_fix,
    }
    if args.no_normalization is not None:
        paths['no_normalization'] = args.no_normalization
    output_path = os.path.realpath(args.output)
    if output_path in [os.path.realpath(path) for path in paths.values()]:
        raise ValueError('--output must not overwrite an input pickle')
    digests = dict((name, sha256(path)) for name, path in paths.items())
    if (args.expected_original_sha256 is not None and
            digests['original'] != args.expected_original_sha256.lower()):
        raise ValueError(
            'original SHA-256 is %s, expected %s' %
            (digests['original'], args.expected_original_sha256.lower()))
    datasets = dict((name, load_dataset(path)) for name, path in paths.items())
    labels = sorted(set(args.snrs))
    gain_ratios = mapper_gain_ratios()
    modulations = []
    for modulation in args.modulations:
        rows = dict((name, []) for name in paths)
        for snr in labels:
            key = (modulation, snr)
            missing = [name for name, dataset in datasets.items()
                       if key not in dataset]
            if missing:
                raise ValueError('key %r is missing from %s' %
                                 (key, ', '.join(missing)))
            for name, dataset in datasets.items():
                estimates = estimate_window_powers(
                    select_windows(dataset[key], args.max_windows),
                    args.oob_cutoff)
                summary = summarize_powers(estimates)
                summary['snr_db'] = snr
                rows[name].append(summary)
        curves = dict(
            (name, fit_snr_curve(values, args.fit_min_snr,
                                 args.fit_max_snr))
            for name, values in rows.items())
        expected_gain_db = 20.0 * math.log10(gain_ratios[modulation])
        modulations.append({
            'modulation': modulation,
            'expected_pre_to_post_amplitude_ratio': gain_ratios[modulation],
            'expected_pre_to_post_snr_shift_db': expected_gain_db,
            'keys': rows,
            'curves': curves,
            'comparison': compare_intercepts(curves, expected_gain_db),
        })

    noise_controls = {}
    noise_key = ('AM-SSB', -20)
    for name, dataset in datasets.items():
        if noise_key in dataset:
            estimates = estimate_window_powers(
                select_windows(dataset[noise_key], args.max_windows),
                args.oob_cutoff)
            noise_controls[name] = summarize_powers(estimates)

    preferences = [row['comparison']['closer_candidate']
                   for row in modulations]
    aggregate = {
        'modulations_closer_to_pre_fix': preferences.count('pre_fix'),
        'modulations_closer_to_post_fix': preferences.count('post_fix'),
        'modulations_tied': preferences.count('tie'),
        'modulations_with_insufficient_dynamic_range':
            preferences.count('insufficient_dynamic_range'),
    }
    normalization_fits = fit_normalization_models(modulations)
    report = {
        'schema': 'radioml2016-mapper-snr-comparison',
        'schema_version': 1,
        'inputs': dict(
            (name, {'path': os.path.realpath(path), 'sha256': digests[name]})
            for name, path in paths.items()),
        'selection': {
            'modulations': args.modulations,
            'snrs_db': labels,
            'max_windows_per_key': args.max_windows,
        },
        'method': {
            'samples_per_symbol': 8,
            'excess_bandwidth': 0.35,
            'nominal_one_sided_signal_band_edge_cycles_per_sample': 0.084375,
            'maximum_carrier_offset_cycles_per_sample': 0.0025,
            'out_of_band_cutoff_cycles_per_sample': args.oob_cutoff,
            'taper': 'Hann',
            'noise_estimator': (
                'Median out-of-band FFT-bin power divided by log(2) and '
                'the taper energy.'),
            'snr_estimator': (
                'Median across windows of total_power/noise_power - 1, '
                'converted to dB when positive.'),
            'label_slope': (
                'Fixed at 2 dB of estimated SNR per 1 dB label because the '
                'generator applies 10**(-label/10) to noise amplitude.'),
            'curve_fit_range_db': [args.fit_min_snr, args.fit_max_snr],
            'mapper_model_revisions': MAPPER_MODEL_REVISIONS,
        },
        'aggregate': aggregate,
        'noise_control_am_ssb_minus_20': noise_controls,
        'modulations': modulations,
        'normalization_model_fits': normalization_fits,
        'direct_no_normalization_comparison':
            compare_direct_candidate(modulations),
        'interpretation_limit': (
            'Candidate pre/post separation calibrates the estimator without '
            'recovering the historical noise RNG state. Treat an original '
            'preference as mapper evidence only when the measured candidate '
            'shift is close to the theoretical mapper shift and the fitted '
            'curves contain enough in-range labels. Spectral leakage, channel '
            'model differences, and shared transmissions remain possible '
            'sources of bias. A common original/direct-candidate difference '
            'does not by itself identify whether signal gain or noise scaling '
            'caused that difference.'),
        'runtime': {
            'python': sys.version,
            'numpy': np.__version__,
            'command': [sys.executable] + sys.argv,
            'script_sha256': sha256(__file__),
        },
    }
    with open(output_path, 'w') as destination:
        json.dump(report, destination, indent=2, sort_keys=True)
        destination.write('\n')
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    for row in modulations:
        comparison = row['comparison']
        print('%-5s %-26s candidate shift %s dB (expected %.2f dB)' %
              (row['modulation'], comparison['closer_candidate'],
               comparison['candidate_intercept_shift_db'],
               comparison['expected_candidate_shift_db']))
    original_fits = normalization_fits['datasets']['original']
    print('Original relative-power model: %s (%s)' %
          (original_fits['best_model_by_rmse'], ', '.join(
              '%s %.3f dB RMS' % (name, fit['rmse_db'])
              for name, fit in sorted(original_fits['fits'].items()))))
    direct = report['direct_no_normalization_comparison']
    if direct is not None:
        if direct['original_minus_candidate_offset_db'] is None:
            print('Direct no-normalization comparison: insufficient '
                  'dynamic range')
        else:
            print('Original minus direct no-normalization candidate: %s dB '
                  '(%.3f dB RMS after common offset)' %
                  (direct['original_minus_candidate_offset_db'],
                   direct['rmse_db']))


if __name__ == '__main__':
    main()
