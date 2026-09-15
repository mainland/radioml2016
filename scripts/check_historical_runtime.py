#!/usr/bin/env python2.7
"""Check the historical Dockerfile's candidate stack with finite flowgraphs.

Run in the historical image:
  python2.7 scripts/check_historical_runtime.py --output /tmp/runtime.json
The defaults describe the pre-February no-normalization mapper. For the
February bug, add ``--mapper-amplitude 2 --pam4-amplitude 12``; for the
October fix, use ``--mapper-amplitude 1 --pam4-amplitude 1.5``.

This checks compatibility and characteristic implementation behavior. It does
not establish which versions produced the original dataset or reproduce it.
Historical channel fingerprints can vary because blocks share lrand48 state.
The JSON report goes to --output; native GNU Radio/media diagnostics may use
stdout, and this script's progress messages go to stderr.
"""
from __future__ import print_function

import argparse
import ctypes
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

import matplotlib
import numpy as np
import scipy
from gnuradio import analog, blocks, channels, gr
import mapper
import mediatools


def stream(tb, sink):
    tb.run()
    a = np.asarray(sink.data(), dtype=np.complex64)
    assert a.size > 0, 'Empty output stream'
    assert np.isfinite(a).all(), 'Nonfinite output stream'
    return a


def fingerprint(a):
    return dict(samples=int(a.size),
                sha256=hashlib.sha256(a.tostring()).hexdigest(),
                peak=float(np.max(np.abs(a))),
                mean_power=float(np.mean(np.abs(a) ** 2)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True,
                        help='JSON report path (parent directory must exist)')
    parser.add_argument('--mapper-amplitude', type=int, choices=[1, 2],
                        default=1, help='expected BPSK amplitude: 1 without '
                        'normalization or after the fix (default), 2 with '
                        'the last-point bug')
    parser.add_argument('--pam4-amplitude', type=float,
                        choices=[1.5, 3.0, 12.0], default=3.0,
                        help='expected PAM4 peak: 3 without normalization '
                        '(default), 12 with the accumulator bug, or 1.5 '
                        'after the fix')
    args = parser.parse_args()
    output = os.path.abspath(args.output)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(script_dir)
    # The original source_alphabet uses paths relative to the repository root.
    os.chdir(repo)
    sys.path.insert(0, repo)
    import transmitters
    import source_alphabet

    assert sys.version_info[:3] == (2, 7, 12), sys.version
    assert np.__version__ == '1.11.0', np.__version__
    assert scipy.__version__ == '0.17.0', scipy.__version__
    assert matplotlib.__version__ == '1.5.1', matplotlib.__version__
    assert gr.version() == '3.7.10.1', gr.version()
    report = dict(
        scope='candidate compatibility; not original dataset provenance',
        python=sys.version, numpy=np.__version__, scipy=scipy.__version__,
        gnuradio=gr.version(), matplotlib=matplotlib.__version__,
        mapper=mapper.__file__, mediatools=mediatools.__file__,
        modulation_checks={})

    # Historical fixed-point sine has a small interpolation error at zero;
    # replacing this with mathematical zero would remove real AM-SSB leakage.
    tb = gr.top_block()
    sine = analog.sig_source_f(200e3, analog.GR_SIN_WAVE, 0.0, 1.0)
    head = blocks.head(gr.sizeof_float, 512)
    sink = blocks.vector_sink_f()
    tb.connect(sine, head, sink)
    tb.run()
    a = np.asarray(sink.data(), dtype=np.float32)
    assert a.size == 512 and np.all(a.view(np.uint32) == 0x31f80cb5), a[:16]
    report['zero_frequency_sine'] = dict(samples=512,
                                         float32_bits='0x31f80cb5',
                                         value=float(a[0]))

    # The February bug changes BPSK amplitude from 1 to 2. The October fix
    # restores 1, so PAM4 below separates the fixed and no-normalization cases.
    # These checks identify installed behavior, not the original mapper.
    tb = gr.top_block()
    source = blocks.vector_source_b([0, 1] * 16, False)
    mod = mapper.mapper(mapper.BPSK, [0, 1])
    sink = blocks.vector_sink_c()
    tb.connect(source, mod, sink)
    a = stream(tb, sink)
    expected = np.asarray([args.mapper_amplitude, -args.mapper_amplitude] * 16,
                          dtype=np.complex64)
    assert np.array_equal(a, expected), a[:16]
    report['bpsk_mapper'] = fingerprint(a)

    # BPSK cannot distinguish no normalization from the corrected mapper.
    # PAM4 has raw peak 3, buggy peak 12, and corrected peak 1.5.
    tb = gr.top_block()
    source = blocks.vector_source_b([0, 0, 0, 1, 1, 0, 1, 1] * 8, False)
    mod = mapper.mapper(mapper.PAM4, [0, 1, 3, 2])
    sink = blocks.vector_sink_c()
    tb.connect(source, mod, sink)
    a = stream(tb, sink)
    assert np.max(np.abs(a)) == args.pam4_amplitude, a[:16]
    report['pam4_mapper'] = fingerprint(a)

    # Independently compile the historical pool using this candidate's compiler
    # and libm. Compare the installed block with its pool and an independent
    # lrand48 recurrence, without involving scheduler threads.
    build_dir = tempfile.mkdtemp(prefix='rml2016-runtime-')
    try:
        executable = os.path.join(build_dir, 'noise-pool')
        subprocess.check_call(['c++', '-O2', '-std=c++11',
                               os.path.join(script_dir, 'rml2016_noise_pool.cc'),
                               '-o', executable])
        pool_csv = subprocess.check_output([executable, 'mt', '4919'])
        pair = np.loadtxt(io.BytesIO(pool_csv), delimiter=',', dtype=np.float32)
        pool = pair[:, 0].astype(np.complex64)
        pool.imag = pair[:, 1]
        assert pool.size == 8192
        noise = analog.fastnoise_source_c(analog.GR_GAUSSIAN, 1.0, 4919, 8192)
        libc = ctypes.CDLL(None)
        libc.srand48.argtypes = [ctypes.c_long]
        libc.srand48.restype = None
        libc.srand48(0)
        state = 0x330e
        indices = []
        for unused in range(4096):
            state = (0x5deece66d * state + 0xb) & ((1 << 48) - 1)
            indices.append((state >> 17) % 8192)
        expected = pool[np.asarray(indices)]
        observed = np.asarray([noise.sample() for unused in indices],
                              dtype=np.complex64)
        assert np.array_equal(observed.view(np.uint32),
                              expected.view(np.uint32)), 'Historical noise mismatch'
        report['fastnoise'] = dict(seed=4919, lrand48_seed=0,
                                   pool=fingerprint(pool),
                                   checked_samples=int(observed.size),
                                   distinct_pool_entries=len(set(indices)),
                                   samples=fingerprint(observed))
    finally:
        shutil.rmtree(build_dir)

    np.random.seed(1337)
    random.seed(1337)
    # Explicit order makes this check stable; it does not replace the original
    # generator's Python 2 dictionary iteration order in an exact replay.
    for alphabet in ['discrete', 'continuous']:
        for cls in transmitters.transmitters[alphabet]:
            tb = gr.top_block()
            source = source_alphabet.source_alphabet(alphabet, 1024, True)
            mod = cls()
            sink = blocks.vector_sink_c()
            tb.connect(source, mod, sink)
            a = stream(tb, sink)
            if cls.modname == 'AM-SSB':
                assert 0 < np.max(np.abs(a)) < 1e-6, \
                    'Expected small nonzero historical AM-SSB sine leakage'
            else:
                assert np.any(a != 0), 'Unexpected zero ' + cls.modname
            report['modulation_checks'][cls.modname] = fingerprint(a)
            print('Checked ' + cls.modname, file=sys.stderr)
            tb.disconnect_all()

    assert len(report['modulation_checks']) == 11
    # Exercise the exact channel constructor signature in the released script.
    tb = gr.top_block()
    source = blocks.vector_source_c([1.0 + 0.0j] * 4096, False)
    channel = channels.dynamic_channel_model(
        200e3, 0.01, 50, .01, 0.5e3, 8, 1, True, 4,
        [0.0, 0.9, 1.7], [1, 0.8, 0.3], 8, 1.0, 0x1337)
    sink = blocks.vector_sink_c()
    tb.connect(source, channel, sink)
    report['channel'] = fingerprint(stream(tb, sink))
    report['channel_fingerprint_repeatable'] = False
    with open(output, 'w') as handle:
        json.dump(report, handle, sort_keys=True, indent=2)
        handle.write('\n')
    print('Wrote ' + output, file=sys.stderr)


if __name__ == '__main__':
    main()
