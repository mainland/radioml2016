#!/usr/bin/env python
from generator_options import configure
options = configure()
from generator_options import ANALOG_SOURCE_SAMPLES
if options.output_format == 'hdf5':
    from generator_options import MODULATIONS
from transmitters import (transmitter_amssb_fixed, transmitters,
                          wbfm_rate_resampler)
from source_alphabet import source_alphabet
from dataset_channel import dynamic_channel, run_dynamic_channel
from dataset_window import normalized_complex_window_with_divisor
from snr_policy import (calibrated_noise_amplitude, measure_snr,
                        nominal_noise_amplitude)
from window_policy import first_window_offset_bounds, settled_window_guard
from gnuradio import gr, blocks
import numpy as np
import numpy.fft, cPickle, gzip
import random

'''
Generate dataset with dynamic channel model across range of SNRs
'''

apply_channel = True


def vector_output(source, *processing_blocks):
    """Materialize a finite complex stream after the supplied blocks."""
    flowgraph = gr.top_block()
    sink = blocks.vector_sink_c()
    chain = (source,) + processing_blocks + (sink,)
    flowgraph.connect(*chain)
    flowgraph.run()
    return np.asarray(sink.data(), dtype=np.complex64)


def channel_input_waveform(source, modulator, fixed_wbfm):
    """Materialize the exact finite waveform presented to the channel."""
    if not fixed_wbfm:
        return vector_output(source, modulator)
    native = vector_output(source, modulator)
    native_source = blocks.vector_source_c(native.tolist(), False)
    return vector_output(native_source, wbfm_rate_resampler())


def make_modulator(mod_type, mod_kwargs, fixed_am_ssb):
    """Construct one historical or repaired modulator instance."""
    if fixed_am_ssb and mod_type.modname == "AM-SSB":
        return transmitter_amssb_fixed()
    return mod_type(**mod_kwargs)


def replay_channel_input(alphabet_type, tx_len, analog_source_offset,
                         random_mask, mod_type, mod_kwargs, fixed_am_ssb,
                         fixed_wbfm):
    """Reconstruct a captured transmission's finite channel input."""
    source = source_alphabet(
        alphabet_type, tx_len, True, source_offset=analog_source_offset,
        random_mask=random_mask)
    modulator = make_modulator(mod_type, mod_kwargs, fixed_am_ssb)
    return channel_input_waveform(
        source, modulator, fixed_wbfm and mod_type.modname == "WBFM")


def window_offsets(sample_count, first_minimum, first_maximum, remaining,
                   window_length):
    """Draw the historical sequence of post-channel window offsets."""
    if first_minimum + window_length >= sample_count:
        raise ValueError(
            'first-window guard %d leaves no complete window in '
            'transmission of %d samples' % (first_minimum, sample_count))
    offsets = []
    offset = random.randint(first_minimum, first_maximum)
    while offset + window_length < sample_count and len(offsets) < remaining:
        offsets.append(offset)
        # Preserve the historical draw after every accepted window, including
        # the final window needed by a modulation/SNR key.
        offset += random.randint(
            window_length, round(sample_count * .05))
    return offsets

analog_segment_length = int(10e3)
analog_segments = None
if options.vary_analog_source:
    analog_segments = range(ANALOG_SOURCE_SAMPLES // analog_segment_length)
    analog_random = random.Random(options.analog_source_seed)
    analog_random.shuffle(analog_segments)

dataset = {}
if options.output_format == 'hdf5':
    window_attributes = {}
    transmissions = []
    transmission_number = 0
    modulation_ids = dict((name, index)
                          for index, name in enumerate(MODULATIONS))

# The output format looks like this
# {('mod type', SNR): np.array(nvecs_per_key, 2, vec_length), etc}

# CIFAR-10 has 6000 samples/class. CIFAR-100 has 600. Somewhere in there seems like right order of magnitude
nvecs_per_key = options.frames_per_key
vec_length = 128
snr_vals = options.snrs
for snr in snr_vals:
    print "snr is ", snr
    for alphabet_type in ("discrete", "continuous"):
        for i,mod_type in enumerate(transmitters[alphabet_type]):
          if mod_type.modname not in options.modulations:
              continue
          dataset[(mod_type.modname, snr)] = np.zeros([nvecs_per_key, 2, vec_length], dtype=np.float32)
          if options.output_format == 'hdf5':
              window_attributes[(mod_type.modname, snr)] = {
                  'transmission_number': np.zeros(
                      nvecs_per_key, dtype=np.uint64),
                  'offset': np.zeros(nvecs_per_key, dtype=np.uint64),
                  'normalization_l1': np.zeros(
                      nvecs_per_key, dtype=np.float32),
                  'snr_measurement_valid': np.zeros(
                      nvecs_per_key, dtype=np.uint8),
                  'signal_power': np.empty(nvecs_per_key, dtype=np.float64),
                  'noise_power': np.empty(nvecs_per_key, dtype=np.float64),
                  'measured_snr_db': np.empty(
                      nvecs_per_key, dtype=np.float64),
              }
              window_attributes[(mod_type.modname, snr)][
                  'signal_power'].fill(np.nan)
              window_attributes[(mod_type.modname, snr)][
                  'noise_power'].fill(np.nan)
              window_attributes[(mod_type.modname, snr)][
                  'measured_snr_db'].fill(np.nan)
          # moar vectors!
          insufficient_modsnr_vectors = True
          modvec_indx = 0
          while insufficient_modsnr_vectors:
              if options.output_format == 'hdf5':
                  current_transmission = transmission_number
                  transmission_number += 1
              tx_len = int(10e3)
              if mod_type.modname == "QAM16":
                  tx_len = int(20e3)
              if mod_type.modname == "QAM64":
                  tx_len = int(30e3)
              analog_source_valid = alphabet_type == "continuous"
              analog_source_offset = 0
              if analog_source_valid and options.vary_analog_source:
                  if tx_len != analog_segment_length:
                      raise ValueError('unexpected analog transmission length')
                  if not analog_segments:
                      raise ValueError(
                          'canonical analog source has no unused segments')
                  analog_source_offset = (
                      analog_segments.pop() * analog_segment_length)
              if options.output_format == 'hdf5':
                  src = source_alphabet(
                      alphabet_type, tx_len, True, capture_random_mask=True,
                      source_offset=analog_source_offset)
              else:
                  src = source_alphabet(
                      alphabet_type, tx_len, True,
                      source_offset=analog_source_offset)
              mod_kwargs = {}
              if options.sps is not None and alphabet_type == "discrete":
                  mod_kwargs["samples_per_symbol"] = random.randint(
                      *options.sps)
              if (options.ebw is not None and alphabet_type == "discrete" and
                      mod_type.modname != "CPFSK"):
                  mod_kwargs["excess_bw"] = random.uniform(*options.ebw)
              if alphabet_type == "discrete":
                  actual_sps = mod_kwargs.get("samples_per_symbol", 8)
                  if mod_type.modname == "CPFSK":
                      actual_ebw = np.nan
                  else:
                      actual_ebw = mod_kwargs.get("excess_bw", 0.35)
              else:
                  actual_sps = 0
                  actual_ebw = np.nan
              mod = make_modulator(
                  mod_type, mod_kwargs, options.fixed_am_ssb)
              channel_seed = options.channel_seed
              if options.channel_seed_policy == 'advance':
                  options.channel_seed = (
                      1 + (options.channel_seed - 1 + 4) % 2147483644)
              first_offset_min, first_offset_max = first_window_offset_bounds(
                  mod_type.modname, actual_sps, options.settled_windows,
                  options.fixed_am_ssb, options.fixed_wbfm)

              if options.snr_mode == 'calibrated':
                  channel_input = channel_input_waveform(
                      src, mod, options.fixed_wbfm and
                      mod_type.modname == "WBFM")
                  clean_output_vector = run_dynamic_channel(
                      channel_input, 0.0, channel_seed)
                  selected_offsets = window_offsets(
                      len(clean_output_vector), first_offset_min,
                      first_offset_max, nvecs_per_key - modvec_indx,
                      vec_length)
                  unit_output_vector = run_dynamic_channel(
                      channel_input, 1.0, channel_seed)
                  noise_amp = calibrated_noise_amplitude(
                      snr, clean_output_vector, unit_output_vector,
                      selected_offsets, vec_length)
                  raw_output_vector = run_dynamic_channel(
                      channel_input, noise_amp, channel_seed)
                  if raw_output_vector.shape != clean_output_vector.shape:
                      raise ValueError(
                          'calibrated channel runs produced unequal lengths')
              else:
                  noise_amp = nominal_noise_amplitude(snr, options.snr_mode)
                  chan = dynamic_channel(noise_amp, channel_seed)
                  snk = blocks.vector_sink_c()

                  if options.fixed_wbfm and mod_type.modname == "WBFM":
                      # Finish decoding and historical FM modulation before
                      # resampling. This prevents finite-stream back-pressure
                      # from making the repaired output depend on unrelated
                      # flowgraphs.
                      native_snk = blocks.vector_sink_c()
                      native_tb = gr.top_block()
                      native_tb.connect(src, mod, native_snk)
                      native_tb.run()
                      native = blocks.vector_source_c(
                          native_snk.data(), False)
                      resampler = wbfm_rate_resampler()
                      tb = gr.top_block()
                      if apply_channel:
                          tb.connect(native, resampler, chan, snk)
                      else:
                          tb.connect(native, resampler, snk)
                  else:
                      tb = gr.top_block()
                      if apply_channel:
                          tb.connect(src, mod, chan, snk)
                      else:
                          tb.connect(src, mod, snk)
                  tb.run()
                  raw_output_vector = np.asarray(
                      snk.data(), dtype=np.complex64)
                  selected_offsets = window_offsets(
                      len(raw_output_vector), first_offset_min,
                      first_offset_max, nvecs_per_key - modvec_indx,
                      vec_length)
              measurement = None
              if (options.measure_snr or
                      options.snr_mode == 'calibrated'):
                  if options.snr_mode != 'calibrated':
                      # Provenance measurements replay captured source state
                      # after the original noisy flowgraph has completed. The
                      # option therefore cannot perturb exported I/Q samples.
                      channel_input = replay_channel_input(
                          alphabet_type, tx_len, analog_source_offset,
                          src.random_mask, mod_type, mod_kwargs,
                          options.fixed_am_ssb, options.fixed_wbfm)
                      clean_output_vector = run_dynamic_channel(
                          channel_input, 0.0, channel_seed)
                  if clean_output_vector.shape != raw_output_vector.shape:
                      raise ValueError(
                          'paired clean and noisy channel runs produced '
                          'unequal lengths')
                  measurement = measure_snr(
                      clean_output_vector, raw_output_vector,
                      selected_offsets, vec_length)
              if options.output_format == 'hdf5':
                  is_wbfm = mod_type.modname == "WBFM"
                  modulator_rate_hz = 220500 if is_wbfm else 200000
                  channel_input_rate_hz = (
                      200000 if options.fixed_wbfm or not is_wbfm else 220500)
                  transmissions.append({
                      'number': current_transmission,
                      'modulation_id': modulation_ids[mod_type.modname],
                      'snr_db': snr,
                      'sps': actual_sps,
                      'ebw': actual_ebw,
                      'modulator_sample_rate_hz': modulator_rate_hz,
                      'channel_input_sample_rate_hz': channel_input_rate_hz,
                      'channel_model_sample_rate_hz': 200000,
                      'channel_seed': channel_seed,
                      'noise_amplitude': noise_amp,
                      'snr_measurement_valid': measurement is not None,
                      'signal_power': (measurement['signal_power']
                                       if measurement is not None else np.nan),
                      'noise_power': (measurement['noise_power']
                                      if measurement is not None else np.nan),
                      'measured_snr_db': (measurement['snr_db']
                                          if measurement is not None else
                                          np.nan),
                      'snr_measurement_window_count': (
                          len(selected_offsets) if measurement is not None
                          else 0),
                      'sample_count': len(raw_output_vector),
                      'analog_source_valid': analog_source_valid,
                      'analog_source_offset': analog_source_offset,
                      'analog_source_length': (tx_len if analog_source_valid
                                               else 0),
                      'random_mask_valid': src.random_mask is not None,
                      'random_mask': src.random_mask,
                      'am_ssb_fixed': (options.fixed_am_ssb and
                                       mod_type.modname == "AM-SSB"),
                      'wbfm_fixed': (options.fixed_wbfm and is_wbfm),
                      'settling_guard_samples': settled_window_guard(
                          mod_type.modname, actual_sps,
                          options.fixed_am_ssb, options.fixed_wbfm),
                  })
              for sampler_indx in selected_offsets:
                  sampled_vector, normalization_l1 = (
                      normalized_complex_window_with_divisor(
                          raw_output_vector, sampler_indx, vec_length)
                  )
                  dataset[(mod_type.modname, snr)][modvec_indx,0,:] = np.real(sampled_vector)
                  dataset[(mod_type.modname, snr)][modvec_indx,1,:] = np.imag(sampled_vector)
                  if options.output_format == 'hdf5':
                      attributes = window_attributes[(mod_type.modname, snr)]
                      attributes['transmission_number'][modvec_indx] = (
                          current_transmission)
                      attributes['offset'][modvec_indx] = sampler_indx
                      attributes['normalization_l1'][modvec_indx] = (
                          normalization_l1)
                      if measurement is not None:
                          window_measurement = measure_snr(
                              clean_output_vector, raw_output_vector,
                              [sampler_indx], vec_length)
                          attributes['snr_measurement_valid'][modvec_indx] = 1
                          attributes['signal_power'][modvec_indx] = (
                              window_measurement['signal_power'])
                          attributes['noise_power'][modvec_indx] = (
                              window_measurement['noise_power'])
                          attributes['measured_snr_db'][modvec_indx] = (
                              window_measurement['snr_db'])
                  modvec_indx += 1

              if modvec_indx == nvecs_per_key:
                  # we're all done
                  insufficient_modsnr_vectors = False

print "all done. writing to disk"
if options.output_format == 'hdf5':
    from hdf5_output import write_hdf5
    ordered_keys = [(modulation, snr) for snr in snr_vals
                    for modulation in MODULATIONS
                    if (modulation, snr) in dataset]
    write_hdf5(options.output, dataset, window_attributes, transmissions,
               options, MODULATIONS, ordered_keys)
else:
    cPickle.dump( dataset, file(options.output, "wb" ) )
