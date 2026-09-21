#!/usr/bin/env python2.7
"""Test transmitter and channel startup-delay analysis."""
from __future__ import print_function

import os
import sys

import numpy as np


REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPOSITORY, 'scripts'))
sys.path.insert(0, REPOSITORY)

import analyze_filter_delay as delay
import window_policy


def test_response_metrics_and_sampler_boundary():
    """Check response coordinates and the inclusive sampler distribution."""
    metrics = delay.response_metrics(np.asarray([0.0, 1.0, 0.0]),
                                     coordinate_offset=7)
    assert metrics['peak_sample'] == 8
    assert metrics['energy_centroid_sample'] == 8.0
    assert metrics['operational_end_sample'] == 8
    assert delay.early_offset_count(50) == 0
    assert delay.early_offset_count(51) == 1
    assert delay.early_offset_count(501) == 451


def test_settled_window_policy():
    """Check finite-response guards and historical sampling compatibility."""
    historical = window_policy.first_window_offset_bounds('BPSK', 8)
    settled = window_policy.first_window_offset_bounds(
        'BPSK', 8, settled_windows=True)
    assert historical == (50, 500)
    assert settled == (710, 1160)
    assert window_policy.settled_window_guard('GFSK', 8) == 50
    assert window_policy.settled_window_guard('CPFSK', 8) == 50
    assert window_policy.settled_window_guard('AM-DSB', 0) == 50
    assert window_policy.settled_window_guard('AM-SSB', 0) == 50
    assert window_policy.settled_window_guard(
        'AM-SSB', 0, fixed_am_ssb=True) == 409
    assert window_policy.settled_window_guard('WBFM', 0) == 318
    assert window_policy.settled_window_guard(
        'WBFM', 0, fixed_wbfm=True) == 260


def test_filter_delay_analysis():
    """Require the measured matrix and established delay invariants."""
    report = delay.run_analysis()
    assert report['runtime']['script_sha256'] == delay.sha256(
        os.path.join(REPOSITORY, 'scripts', 'analyze_filter_delay.py'))
    rows = dict((row['modulation'], row) for row in report['transmitters'])
    assert set(rows) == {
        'BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64', 'GFSK',
        'CPFSK', 'WBFM', 'AM-DSB', 'AM-SSB', 'WBFM-fixed'}
    for name in ('BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64'):
        response = rows[name]['response']
        assert response['peak_sample'] == 352, (name, response)
        assert response['operational_end_sample'] > 500, (name, response)
        assert (rows[name]['sampler_without_channel']
                ['too_early_probability'] == 1.0)
    assert rows['GFSK']['response']['peak_sample'] < 50
    assert rows['CPFSK']['response']['operational_end_sample'] < 50
    assert rows['AM-SSB']['response']['peak_sample'] > 150

    sweep = report['digital_parameter_sweep']
    linear = [row for row in sweep if row['modulation'] == 'BPSK']
    assert len(linear) == 6
    for row in linear:
        expected = int(5.5 * row['samples_per_symbol']**2)
        assert row['response']['peak_sample'] == expected, row
    assert any(row['samples_per_symbol'] == 2 and
               row['sampler_without_channel']['too_early_probability'] == 0.0
               for row in linear)
    assert all(row['sampler_without_channel']['too_early_probability'] == 1.0
               for row in linear if row['samples_per_symbol'] == 12)

    controls = report['channel_controls']
    assert set(controls) == {
        'baseline', 'awgn', 'cfo', 'sro', 'fading', 'combined'}
    assert controls['awgn']['timing_equivalent_to'] == 'baseline'
    assert len(report['cascade_sampler_assessments']) == 12 * 6
    policy = dict((row['modulation'], row['settling_guard_samples'])
                  for row in report['optional_repair_policy']['guards'])
    assert policy['BPSK'] == 710
    assert policy['AM-SSB'] == 409
    assert policy['WBFM'] == 318
    assert policy['WBFM-fixed'] == 260
    combined = [row for row in report['cascade_sampler_assessments']
                if row['channel_control'] == 'combined']
    for row in combined:
        assert policy[row['modulation']] >= row['earliest_operational_offset']
