"""Write attributed RadioML windows to a numeric HDF5 representation."""
from __future__ import print_function

import json

import h5py
import numpy as np

from generator_options import ANALOG_SOURCE_SAMPLES, ANALOG_SOURCE_SHA256


SCHEMA = 'radioml2016-attributed'
SCHEMA_VERSION = 1
WINDOW_LENGTH = 128
RANDOM_MASK_LENGTH = 256


def _create_dataset(group, name, shape, dtype):
    """Create a dataset without HDF5 object modification timestamps."""
    return group.create_dataset(name, shape=shape, dtype=np.dtype(dtype),
                                track_times=False)


def _write_transmissions(group, transmissions):
    """Write one row of shared attributes for every attempted transmission."""
    count = len(transmissions)
    for number, transmission in enumerate(transmissions):
        assert transmission['number'] == number

    columns = (
        ('modulation_id', '<i2'),
        ('snr_db', '<i2'),
        ('sps', '<u4'),
        # Field meaning depends on modulation: RRC roll-off or GFSK BT.
        ('ebw', '<f8'),
        ('modulator_sample_rate_hz', '<u4'),
        ('channel_input_sample_rate_hz', '<u4'),
        ('channel_model_sample_rate_hz', '<u4'),
        ('channel_seed', '<u4'),
        ('noise_amplitude', '<f8'),
        ('snr_measurement_valid', 'u1'),
        ('signal_power', '<f8'),
        ('noise_power', '<f8'),
        ('measured_snr_db', '<f8'),
        ('snr_measurement_window_count', '<u4'),
        ('sample_count', '<u8'),
        ('analog_source_valid', 'u1'),
        ('analog_source_offset', '<u8'),
        ('analog_source_length', '<u4'),
        ('random_mask_valid', 'u1'),
        ('am_ssb_fixed', 'u1'),
        ('wbfm_fixed', 'u1'),
        ('settling_guard_samples', '<u4'),
    )
    for name, dtype in columns:
        values = np.asarray([item[name] for item in transmissions], dtype=dtype)
        _create_dataset(group, name, values.shape, dtype)[:] = values
    group['analog_source_offset'].attrs['units'] = 'samples'
    group['analog_source_offset'].attrs['origin'] = np.uint8(0)
    group['analog_source_offset'].attrs['coordinate'] = (
        'canonical pre-modulator source')
    group['analog_source_length'].attrs['units'] = 'samples'
    group['noise_amplitude'].attrs['meaning'] = (
        'requested RMS amplitude of the complex Gaussian noise source')
    group['signal_power'].attrs['meaning'] = (
        'aggregate clean power over exported windows in this transmission')
    group['noise_power'].attrs['meaning'] = (
        'aggregate paired noisy-minus-clean power over exported windows')
    group['measured_snr_db'].attrs['meaning'] = (
        '10*log10(signal_power/noise_power) before window normalization')

    masks = np.zeros((count, RANDOM_MASK_LENGTH), dtype=np.uint8)
    for number, transmission in enumerate(transmissions):
        mask = transmission['random_mask']
        if mask is None:
            continue
        mask = np.asarray(mask, dtype=np.uint8)
        assert mask.shape == (RANDOM_MASK_LENGTH,)
        assert np.logical_or(mask == 0, mask == 1).all()
        masks[number] = mask
    _create_dataset(group, 'random_mask', masks.shape, 'u1')[:] = masks


def write_hdf5(path, dataset, window_attributes, transmissions, options,
               modulation_names, ordered_keys):
    """Write windows and their generation attributes to HDF5.

    Args:
        path: Destination file path.
        dataset: Pickle-compatible mapping from ``(modulation, SNR)`` to I/Q
            batches.
        window_attributes: Mapping with aligned transmission and offset arrays.
        transmissions: Shared attribute records indexed by transmission number.
        options: Parsed generator options recorded in the file metadata.
        modulation_names: Stable modulation-ID vocabulary.
        ordered_keys: Explicit order in which mapping batches become HDF5 rows.
    """
    item_count = sum(int(dataset[key].shape[0]) for key in ordered_keys)
    modulation_ids = dict((name, index)
                          for index, name in enumerate(modulation_names))
    generation = {
        'seed': options.seed,
        'python_seed': options.python_seed,
        'numpy_seed': options.numpy_seed,
        'initial_channel_seed': options.initial_channel_seed,
        'channel_seed_policy': options.channel_seed_policy,
        'frames_per_key': options.frames_per_key,
        'snrs': list(options.snrs),
        'modulations': list(options.modulations),
        'sps': options.sps,
        'ebw': options.ebw,
        'fixed_am_ssb': options.fixed_am_ssb,
        'fixed_wbfm': options.fixed_wbfm,
        'settled_windows': options.settled_windows,
        'snr_mode': options.snr_mode,
        'measure_snr': options.measure_snr,
        'vary_analog_source': options.vary_analog_source,
        'analog_source_seed': options.analog_source_seed,
        'scheduler': options.scheduler,
    }

    with h5py.File(path, 'w') as destination:
        destination.attrs['schema'] = SCHEMA
        destination.attrs['schema_version'] = np.uint16(SCHEMA_VERSION)
        destination.attrs['modulation_names_json'] = json.dumps(
            list(modulation_names), separators=(',', ':'))
        destination.attrs['generation_options_json'] = json.dumps(
            generation, sort_keys=True, separators=(',', ':'))
        destination.attrs['analog_source_json'] = json.dumps({
            'sha256': ANALOG_SOURCE_SHA256,
            'dtype': '<f4',
            'sample_count': ANALOG_SOURCE_SAMPLES,
            'coordinate': 'pre-modulator source item',
        }, sort_keys=True, separators=(',', ':'))

        windows = destination.create_group('windows')
        iq = _create_dataset(
            windows, 'iq', (item_count, 2, WINDOW_LENGTH), '<f4')
        modulation_id = _create_dataset(
            windows, 'modulation_id', (item_count,), '<i2')
        snr_db = _create_dataset(windows, 'snr_db', (item_count,), '<i2')
        transmission_number = _create_dataset(
            windows, 'transmission_number', (item_count,), '<u8')
        offset = _create_dataset(windows, 'offset', (item_count,), '<u8')
        normalization_l1 = _create_dataset(
            windows, 'normalization_l1', (item_count,), '<f4')
        measurement_valid = _create_dataset(
            windows, 'snr_measurement_valid', (item_count,), 'u1')
        signal_power = _create_dataset(
            windows, 'signal_power', (item_count,), '<f8')
        noise_power = _create_dataset(
            windows, 'noise_power', (item_count,), '<f8')
        measured_snr_db = _create_dataset(
            windows, 'measured_snr_db', (item_count,), '<f8')
        iq.attrs['axes'] = 'item,iq,time'
        snr_db.attrs['meaning'] = (
            'requested label interpreted according to generation snr_mode')
        transmission_number.attrs['reference'] = 'transmissions row'
        offset.attrs['units'] = 'samples'
        offset.attrs['origin'] = np.uint8(0)
        normalization_l1.attrs['meaning'] = (
            'sum(abs(raw complex64 window)) before normalization')
        signal_power.attrs['meaning'] = (
            'mean clean post-impairment complex-sample power')
        noise_power.attrs['meaning'] = (
            'mean paired noisy-minus-clean complex-sample power')
        measured_snr_db.attrs['meaning'] = (
            '10*log10(signal_power/noise_power) before normalization')

        position = 0
        for key in ordered_keys:
            mod_name, snr = key
            batch = np.asarray(dataset[key], dtype=np.float32)
            attributes = window_attributes[key]
            count = int(batch.shape[0])
            assert batch.shape == (count, 2, WINDOW_LENGTH)
            assert attributes['transmission_number'].shape == (count,)
            assert attributes['offset'].shape == (count,)
            assert attributes['normalization_l1'].shape == (count,)
            selection = slice(position, position + count)
            iq[selection] = batch
            modulation_id[selection] = modulation_ids[mod_name]
            snr_db[selection] = snr
            transmission_number[selection] = attributes['transmission_number']
            offset[selection] = attributes['offset']
            normalization_l1[selection] = attributes['normalization_l1']
            measurement_valid[selection] = attributes[
                'snr_measurement_valid']
            signal_power[selection] = attributes['signal_power']
            noise_power[selection] = attributes['noise_power']
            measured_snr_db[selection] = attributes['measured_snr_db']
            position += count
        assert position == item_count

        transmission_group = destination.create_group('transmissions')
        _write_transmissions(transmission_group, transmissions)
