"""Configure reproducible dataset generation before importing GNU Radio."""
import argparse
import json
import os
import random
import sys

MODULATIONS = ('BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64', 'GFSK',
               'CPFSK', 'WBFM', 'AM-DSB', 'AM-SSB')
ENVIRONMENT = dict(PYTHONHASHSEED='0', VOLK_GENERIC='1',
                   OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                   RADIOML_ANALOG_SOURCE=(
                       '/opt/rml/share/radioml2016/serial-s01-e01.f32'))
RUNTIME = 'radioml2016-canonical-audio-v3'
ANALOG_SOURCE_SAMPLES = 70056888
ANALOG_SOURCE_SHA256 = (
    'dfa1cdf1d11950f099f685c9c0d2a1197019415ffcf50c8d8f1988dc532a8325')


def configure():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=lambda value: int(value, 0), default=201610,
                        help='default Python and NumPy seed (default: 201610)')
    parser.add_argument('--python-seed', type=lambda value: int(value, 0))
    parser.add_argument('--numpy-seed', type=lambda value: int(value, 0))
    parser.add_argument('--channel-seed', type=lambda value: int(value, 0),
                        default=0x1337,
                        help='channel base seed (default: 0x1337)')
    parser.add_argument('--channel-seed-policy',
                        choices=('restart', 'advance'), default='restart',
                        help='restart the base seed for each transmission or '
                        'advance it by 4 (default: restart)')
    parser.add_argument('--frames-per-key', type=int, default=1000)
    parser.add_argument('--snrs', type=int, nargs='+', default=list(range(-20, 20, 2)))
    parser.add_argument('--modulations', choices=MODULATIONS, nargs='+',
                        default=list(MODULATIONS))
    parser.add_argument('--scheduler', choices=('tpb', 'sts'), default='sts',
                        help='GNU Radio scheduler (default: sts)')
    parser.add_argument('--sps', type=int, nargs=2, metavar=('MIN', 'MAX'),
                        help='draw integer samples per symbol from inclusive '
                        'MIN..MAX for digital modulations')
    parser.add_argument('--ebw', type=float, nargs=2, metavar=('MIN', 'MAX'),
                        help='draw RRC roll-off or GFSK Gaussian-filter BT '
                        'uniformly from MIN..MAX')
    parser.add_argument('--fixed-am-ssb', action='store_true',
                        help='use the minimal zero-frequency cosine repair '
                        '(the original implementation remains the default)')
    parser.add_argument('--fixed-wbfm', action='store_true',
                        help='resample WBFM to the 200 ksample/s channel rate '
                        '(the original 220.5 ksample/s path remains the default)')
    parser.add_argument('--settled-windows', action='store_true',
                        help='select first windows after the measured '
                        'transmitter and channel startup response')
    parser.add_argument('--vary-analog-source', action='store_true',
                        help='draw nonoverlapping 10000-sample source segments '
                        'for analog transmissions')
    parser.add_argument('--analog-source-seed',
                        type=lambda value: int(value, 0),
                        help='analog segment permutation seed (default: --seed)')
    parser.add_argument('--output', default='RML2016.10a_dict.dat')
    args = parser.parse_args()
    os.environ['GR_SCHEDULER'] = args.scheduler.upper()
    for name in ('python_seed', 'numpy_seed'):
        if getattr(args, name) is None:
            setattr(args, name, args.seed)
    if args.analog_source_seed is None:
        args.analog_source_seed = args.seed
    for name in ('seed', 'python_seed', 'numpy_seed', 'analog_source_seed'):
        if not 0 <= getattr(args, name) <= 0xffffffff:
            parser.error('--%s must be in 0..4294967295' % name.replace('_', '-'))
    # GNU Radio uses time for zero; the fading path also uses base+i and base+i+1.
    if not 1 <= args.channel_seed <= 2147483644:
        parser.error('--channel-seed must be in 1..2147483644; zero seeds from time')
    if args.frames_per_key < 1:
        parser.error('--frames-per-key must be positive')
    if any(snr not in range(-20, 20, 2) for snr in args.snrs):
        parser.error('--snrs must use the original -20..18 labels in steps of 2')
    args.snrs = sorted(set(args.snrs))
    if args.sps is not None:
        minimum, maximum = args.sps
        if minimum < 1 or maximum < minimum:
            parser.error('--sps requires 1 <= MIN <= MAX')
        if 'GFSK' in args.modulations and minimum < 2:
            parser.error('--sps MIN must be at least 2 when GFSK is selected')
    if args.ebw is not None:
        minimum, maximum = args.ebw
        if not 0.0 < minimum <= maximum <= 1.0:
            parser.error('--ebw requires 0 < MIN <= MAX <= 1')
    if sys.version_info[:2] != (2, 7):
        parser.error('use Python 2.7 in the Dockerfile.reproducible image')
    if any(os.environ.get(key) != value for key, value in ENVIRONMENT.items()):
        parser.error('use Dockerfile.reproducible with its default RNG/numeric environment')
    try:
        with open('/opt/replay-provenance/deterministic-runtime.json') as source:
            runtime = json.load(source)
    except (IOError, ValueError):
        parser.error('missing deterministic runtime; build Dockerfile.reproducible')
    if runtime.get('runtime') != RUNTIME:
        parser.error('unsupported deterministic runtime: %r' % runtime)
    analog_source = os.environ['RADIOML_ANALOG_SOURCE']
    if (not os.path.isfile(analog_source) or
            os.path.getsize(analog_source) != 280227552):
        parser.error('missing canonical analog source; rebuild '
                     'Dockerfile.reproducible')
    import numpy as np
    random.seed(args.python_seed)
    np.random.seed(args.numpy_seed)
    return args
