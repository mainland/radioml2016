#!/usr/bin/env python
from generator_options import configure
options = configure()
from generator_options import ANALOG_SOURCE_SAMPLES
from transmitters import (transmitter_amssb_fixed, transmitters,
                          wbfm_rate_resampler)
from source_alphabet import source_alphabet
from dataset_channel import dynamic_channel, run_dynamic_channel
from dataset_window import normalized_complex_window
from snr_policy import calibrated_noise_amplitude, nominal_noise_amplitude
from window_policy import first_window_offset_bounds
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
          # moar vectors!
          insufficient_modsnr_vectors = True
          modvec_indx = 0
          while insufficient_modsnr_vectors:
              tx_len = int(10e3)
              if mod_type.modname == "QAM16":
                  tx_len = int(20e3)
              if mod_type.modname == "QAM64":
                  tx_len = int(30e3)
              analog_source_offset = 0
              if alphabet_type == "continuous" and options.vary_analog_source:
                  if tx_len != analog_segment_length:
                      raise ValueError('unexpected analog transmission length')
                  if not analog_segments:
                      raise ValueError(
                          'canonical analog source has no unused segments')
                  analog_source_offset = (
                      analog_segments.pop() * analog_segment_length)
              src = source_alphabet(
                  alphabet_type, tx_len, True,
                  source_offset=analog_source_offset)
              mod_kwargs = {}
              if options.sps is not None and alphabet_type == "discrete":
                  mod_kwargs["samples_per_symbol"] = random.randint(*options.sps)
              if (options.ebw is not None and alphabet_type == "discrete" and
                      mod_type.modname != "CPFSK"):
                  mod_kwargs["excess_bw"] = random.uniform(*options.ebw)
              actual_sps = (mod_kwargs.get("samples_per_symbol", 8)
                            if alphabet_type == "discrete" else 0)
              if options.fixed_am_ssb and mod_type.modname == "AM-SSB":
                  mod = transmitter_amssb_fixed()
              else:
                  mod = mod_type(**mod_kwargs)
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
              for sampler_indx in selected_offsets:
                  sampled_vector = normalized_complex_window(
                      raw_output_vector, sampler_indx, vec_length)
                  dataset[(mod_type.modname, snr)][modvec_indx,0,:] = np.real(sampled_vector)
                  dataset[(mod_type.modname, snr)][modvec_indx,1,:] = np.imag(sampled_vector)
                  modvec_indx += 1

              if modvec_indx == nvecs_per_key:
                  # we're all done
                  insufficient_modsnr_vectors = False

print "all done. writing to disk"
cPickle.dump( dataset, file(options.output, "wb" ) )
