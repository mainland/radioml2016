#!/usr/bin/env python2.7
"""Test mapper evidence based on out-of-band noise power."""
from __future__ import print_function

import cPickle
import json
import os
import subprocess
import sys

import numpy as np
import pytest


REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPOSITORY, 'scripts'))

import estimate_mapper_snr as mapper_snr


def synthetic_windows(snr_db, seed=20260921, count=512):
    """Return normalized band-limited signal plus white-noise windows."""
    random_state = np.random.RandomState(seed)
    sample_count = 128
    frequencies = np.fft.fftfreq(sample_count)
    signal_bins = np.abs(frequencies) <= 0.06
    spectrum = np.zeros((count, sample_count), dtype=np.complex128)
    spectrum[:, signal_bins] = (
        random_state.normal(size=(count, np.sum(signal_bins))) +
        1j * random_state.normal(size=(count, np.sum(signal_bins))))
    signal = np.fft.ifft(spectrum, axis=1)
    signal /= np.sqrt(np.mean(np.abs(signal) ** 2, axis=1))[:, None]
    noise = (random_state.normal(size=signal.shape) +
             1j * random_state.normal(size=signal.shape)) / np.sqrt(2.0)
    raw = np.sqrt(10.0 ** (snr_db / 10.0)) * signal + noise
    raw /= np.sum(np.abs(raw), axis=1)[:, None]
    values = np.empty((count, 2, sample_count), dtype=np.float32)
    values[:, 0, :] = raw.real
    values[:, 1, :] = raw.imag
    return values


def test_estimator_is_invariant_to_window_scale():
    values = synthetic_windows(5.0)
    scaled = values * np.float32(7.0)
    original = mapper_snr.estimate_window_powers(values)
    changed = mapper_snr.estimate_window_powers(scaled)
    assert np.allclose(original['signal_to_noise_linear'],
                       changed['signal_to_noise_linear'], rtol=1e-6,
                       atol=1e-6)


def test_estimator_recovers_synthetic_snr():
    for expected in (-5.0, 5.0, 15.0):
        summary = mapper_snr.summarize_powers(
            mapper_snr.estimate_window_powers(
                synthetic_windows(expected)))
        assert abs(summary['median_snr_db'] - expected) < 1.5


def test_estimator_recovers_six_db_signal_gain():
    post = mapper_snr.summarize_powers(
        mapper_snr.estimate_window_powers(synthetic_windows(0.0)))
    pre = mapper_snr.summarize_powers(
        mapper_snr.estimate_window_powers(synthetic_windows(
            20.0 * np.log10(2.0))))
    assert abs((pre['median_snr_db'] - post['median_snr_db']) -
               20.0 * np.log10(2.0)) < 1.0


def test_curve_fit_uses_known_noise_amplitude_slope():
    rows = [
        {'snr_db': label, 'median_snr_db': 2.0 * label - 3.5}
        for label in (-4, 0, 4, 8)
    ]
    fit = mapper_snr.fit_snr_curve(rows, -20.0, 20.0)
    assert fit['point_count'] == 4
    assert abs(fit['fixed_slope_intercept_db'] + 3.5) < 1e-12
    assert abs(fit['fitted_slope_db_per_label_db'] - 2.0) < 1e-12


def test_mapper_gain_ratios_include_accumulator_bug():
    ratios = mapper_snr.mapper_gain_ratios()
    assert ratios['BPSK'] == 2.0
    assert ratios['QPSK'] == 4.0
    assert ratios['8PSK'] == 8.0
    assert ratios['PAM4'] == 8.0
    assert 11.0 < ratios['QAM16'] < 12.0
    assert 39.0 < ratios['QAM64'] < 40.0


def test_relative_constellation_power_distinguishes_normalization():
    powers = mapper_snr.normalization_model_powers_db()
    assert abs(powers['no_normalization']['BPSK']) < 1e-12
    assert abs(powers['no_normalization']['PAM4'] -
               10.0 * np.log10(5.0)) < 1e-12
    assert abs(powers['no_normalization']['QAM16'] - 10.0) < 1e-12
    assert abs(powers['no_normalization']['QAM64'] -
               10.0 * np.log10(42.0)) < 1e-12

    modulations = []
    for name in mapper_snr.DEFAULT_MODULATIONS:
        modulations.append({
            'modulation': name,
            'curves': dict(
                (dataset, {
                    'fixed_slope_intercept_db':
                        powers[model][name] + 3.0,
                })
                for dataset, model in (
                    ('original', 'no_normalization'),
                    ('no_normalization', 'no_normalization'),
                    ('pre_fix', 'pre_fix'),
                    ('post_fix', 'post_fix'))),
        })
    fits = mapper_snr.fit_normalization_models(modulations)['datasets']
    assert fits['original']['best_model_by_rmse'] == 'no_normalization'
    assert (fits['no_normalization']['best_model_by_rmse'] ==
            'no_normalization')
    assert fits['pre_fix']['best_model_by_rmse'] == 'pre_fix'
    assert fits['post_fix']['best_model_by_rmse'] == 'post_fix'
    assert fits['original']['fits']['no_normalization']['rmse_db'] < 1e-12
    direct = mapper_snr.compare_direct_candidate(modulations)
    assert direct['original_minus_candidate_offset_db'] == 0.0
    assert direct['rmse_db'] == 0.0


def test_command_writes_snr_provenance_report(tmpdir):
    labels = (-4, 0, 4)
    post = dict((('BPSK', label), synthetic_windows(2.0 * label - 3.0,
                                                   count=128))
                for label in labels)
    pre = dict((key, synthetic_windows(
        2.0 * key[1] - 3.0 + 20.0 * np.log10(2.0), count=128))
               for key in post)
    paths = {}
    for name, values in (('original', post), ('none', post),
                         ('pre', pre), ('post', post)):
        path = str(tmpdir.join(name + '.dat'))
        with open(path, 'wb') as destination:
            cPickle.dump(values, destination, protocol=0)
        paths[name] = path
    report_path = str(tmpdir.join('report.json'))
    command = [
        sys.executable,
        os.path.join(REPOSITORY, 'scripts', 'estimate_mapper_snr.py'),
        paths['original'], paths['pre'], paths['post'],
        '--no-normalization', paths['none'],
        '--modulations', 'BPSK', '--snrs', '-4', '0', '4',
        '--fit-min-snr', '-20', '--fit-max-snr', '20',
        '--output', report_path,
    ]
    assert subprocess.call(command) == 0
    with open(report_path) as source:
        report = json.load(source)
    comparison = report['modulations'][0]['comparison']
    assert report['schema'] == 'radioml2016-mapper-snr-comparison'
    assert comparison['closer_candidate'] == 'post_fix'
    assert comparison['original_to_post_fix_db'] == 0.0
    assert comparison['original_to_no_normalization_db'] == 0.0
    assert (report['direct_no_normalization_comparison']
            ['original_minus_candidate_offset_db'] == 0.0)
    assert ('no_normalization' in
            report['normalization_model_fits']['datasets'])
    assert (report['method']['mapper_model_revisions']['no_normalization'] ==
            '463f9e94f5ea45e5be64bae06291423ead3b70f2')
    assert report['runtime']['script_sha256'] == mapper_snr.sha256(
        os.path.join(REPOSITORY, 'scripts', 'estimate_mapper_snr.py'))


def test_estimator_rejects_wrong_iq_layout():
    with pytest.raises(ValueError) as error:
        mapper_snr.estimate_window_powers(
            np.ones((4, 128, 2), dtype=np.float32))
    assert 'shape [N, 2, 128]' in str(error.value)


def test_report_must_not_overwrite_input(tmpdir, monkeypatch):
    path = str(tmpdir.join('original.dat'))
    with open(path, 'wb') as destination:
        cPickle.dump({('BPSK', 18): synthetic_windows(5.0, count=4)},
                     destination, protocol=0)
    original_digest = mapper_snr.sha256(path)
    monkeypatch.setattr(
        sys, 'argv', ['estimate_mapper_snr.py', path, path, path,
                      '--output', path])
    with pytest.raises(ValueError) as error:
        mapper_snr.main()
    assert 'must not overwrite' in str(error.value)
    assert mapper_snr.sha256(path) == original_digest
