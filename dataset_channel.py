"""Construct and run the pinned RadioML dynamic channel."""
from __future__ import print_function

import numpy as np
from gnuradio import blocks, channels, gr


def dynamic_channel(noise_amplitude, seed):
    """Return the dataset channel with the requested complex-noise amplitude."""
    return channels.dynamic_channel_model(
        200e3, 0.01, 50, .01, 0.5e3, 8, 1, True, 4,
        [0.0, 0.9, 1.7], [1, 0.8, 0.3], 8, noise_amplitude, seed)


def run_dynamic_channel(samples, noise_amplitude, seed):
    """Run a finite complex waveform through a fresh channel instance.

    Args:
        samples: One-dimensional complex channel-input waveform.
        noise_amplitude: RMS amplitude requested from GNU Radio's complex
            Gaussian source.
        seed: Channel base seed.

    Returns:
        The finite complex64 channel output.

    Raises:
        ValueError: If the waveform or noise amplitude is invalid.
    """
    samples = np.asarray(samples, dtype=np.complex64)
    if samples.ndim != 1 or samples.size == 0:
        raise ValueError('channel input must be a nonempty one-dimensional array')
    if not np.isfinite(samples).all():
        raise ValueError('channel input must be finite')
    if not np.isfinite(noise_amplitude) or noise_amplitude < 0:
        raise ValueError('noise amplitude must be finite and nonnegative')
    flowgraph = gr.top_block()
    source = blocks.vector_source_c(samples.tolist(), False)
    channel = dynamic_channel(noise_amplitude, seed)
    sink = blocks.vector_sink_c()
    flowgraph.connect(source, channel, sink)
    flowgraph.run()
    return np.asarray(sink.data(), dtype=np.complex64)
