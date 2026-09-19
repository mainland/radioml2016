#!/usr/bin/env python
from generator_options import configure
options = configure()
from generator_options import ANALOG_SOURCE_SAMPLES
from transmitters import transmitter_amssb_fixed, transmitters
from source_alphabet import source_alphabet
from dataset_window import normalized_complex_window
from gnuradio import channels, gr, blocks
import numpy as np
import numpy.fft, cPickle, gzip
import random

'''
Generate dataset with dynamic channel model across range of SNRs
'''

apply_channel = True

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
              if options.fixed_am_ssb and mod_type.modname == "AM-SSB":
                  mod = transmitter_amssb_fixed()
              else:
                  mod = mod_type(**mod_kwargs)
              fD = 1
              delays = [0.0, 0.9, 1.7]
              mags = [1, 0.8, 0.3]
              ntaps = 8
              noise_amp = 10**(-snr/10.0)
              chan = channels.dynamic_channel_model( 200e3, 0.01, 50, .01, 0.5e3, 8, fD, True, 4, delays, mags, ntaps, noise_amp, options.channel_seed )
              if options.channel_seed_policy == 'advance':
                  options.channel_seed = 1 + (options.channel_seed - 1 + 4) % 2147483644

              snk = blocks.vector_sink_c()

              tb = gr.top_block()

              # connect blocks
              if apply_channel:
                  tb.connect(src, mod, chan, snk)
              else:
                  tb.connect(src, mod, snk)
              tb.run()

              raw_output_vector = np.array(snk.data(), dtype=np.complex64)
              # start the sampler some random time after channel model transients (arbitrary values here)
              sampler_indx = random.randint(50, 500)
              while sampler_indx + vec_length < len(raw_output_vector) and modvec_indx < nvecs_per_key:
                  sampled_vector = normalized_complex_window(
                      raw_output_vector, sampler_indx, vec_length)
                  dataset[(mod_type.modname, snr)][modvec_indx,0,:] = np.real(sampled_vector)
                  dataset[(mod_type.modname, snr)][modvec_indx,1,:] = np.imag(sampled_vector)
                  # bound the upper end very high so it's likely we get multiple passes through
                  # independent channels
                  sampler_indx += random.randint(vec_length, round(len(raw_output_vector)*.05))
                  modvec_indx += 1

              if modvec_indx == nvecs_per_key:
                  # we're all done
                  insufficient_modsnr_vectors = False

print "all done. writing to disk"
cPickle.dump( dataset, file(options.output, "wb" ) )
