#!/usr/bin/env python
import argparse
import h5py
import logging
import random

import numpy as np

from gnuradio import channels, gr, blocks

from transmitters import *
from source_alphabet import source_alphabet

transmitters = {
    "discrete":[transmitter_bpsk, transmitter_qpsk, transmitter_8psk, transmitter_pam4, transmitter_qam16, transmitter_qam64, transmitter_gfsk, transmitter_cpfsk],
    "continuous":[transmitter_fm, transmitter_am, transmitter_amssb_revised]
    }

def generate(output=None, nvecs_per_key=1000, vec_length=128, seed=2016, vary_sps=False, vary_ebw=False, apply_channel=True):
    """Generate dataset with dynamic channel model across range of SNRs

    Args:
        output: path to output file
        nvecs_per_key: number of signal vectors per settings. Defaults to 1000.
        vec_length: Signal vector length. Defaults to 1000.
        seed: random seed. Defaults to 2016.
        vary_sps: Vary samples per symbol
        vary_ebw: Vary excess bandwidth
        apply_channel: True if channel model should be applied. Defaults to True.
    """
    np.random.seed(seed)
    random.seed(seed)

    items = []

    doppler_freq = 1
    delays = [0.0, 0.9, 1.7]
    mags = [1, 0.8, 0.3]
    ntaps = 8

    for snr in range(-20,20,2):
        print "snr is", snr
        for alphabet_type in transmitters.keys():
            for mod_type in transmitters[alphabet_type]:
                chan_indx = 0
                modvec_indx = 0

                while modvec_indx < nvecs_per_key:
                    tx_len = int(10e3)
                    if mod_type.modname == "QAM16":
                        tx_len = int(20e3)
                    if mod_type.modname == "QAM64":
                        tx_len = int(30e3)
                    src = source_alphabet(alphabet_type, tx_len, True)

                    # Only some modulation types support symbol rate and excess
                    # bandwidth parameters
                    sps = np.nan
                    ebw = np.nan

                    kwargs = {}

                    # Choose symbol rate from range [1, 15], or [2, 15] if using
                    # GFSK.
                    if vary_sps and alphabet_type is 'discrete':
                        if mod_type.modname == 'GFSK':
                            sps = random.randint(2, 15)
                        else:
                            sps = random.randint(1, 15)
                        kwargs['samples_per_symbol'] = sps

                    # Choose excess bandwidth from range [0.1, 1.0]
                    if vary_ebw and alphabet_type is 'discrete' and mod_type.modname != 'CPFSK':
                        ebw = random.uniform(0.1, 1.0)
                        kwargs['excess_bw'] = ebw

                    mod = mod_type(**kwargs)
                    chan_indx += 1

                    noise_amp = 10**(-snr/10.0)

                    chan = channels.dynamic_channel_model(samp_rate=200e3,
                                                          sro_std_dev=0.01,
                                                          sro_max_dev=50,
                                                          cfo_std_dev=.01,
                                                          cfo_max_dev=0.5e3,
                                                          N=8,
                                                          doppler_freq=doppler_freq,
                                                          LOS_model=True,
                                                          K=4,
                                                          delays=delays,
                                                          mags=mags,
                                                          ntaps_mpath=ntaps,
                                                          noise_amp=noise_amp,
                                                          noise_seed=0x1337)

                    snk = blocks.vector_sink_c()

                    tb = gr.top_block()

                    # connect blocks
                    if apply_channel:
                        tb.connect(src, mod, chan, snk)
                    else:
                        tb.connect(src, mod, snk)
                    tb.run()

                    raw_output_vector = np.array(snk.data(), dtype=np.complex64)

                    # Start the sampler some random time after channel model
                    # transients (arbitrary values here). The original RadioML
                    # data set used a range that was too small, so some signals
                    # consisted only of channel transients.
                    #sampler_indx = random.randint(50, 500)
                    sampler_indx = random.randint(2000, 5000)

                    while sampler_indx + vec_length < len(raw_output_vector) and modvec_indx < nvecs_per_key:
                        sampled_vector = raw_output_vector[sampler_indx:sampler_indx+vec_length]

                        # Normalize the energy in this vector to be 1
                        energy = np.sum((np.abs(sampled_vector)))
                        sampled_vector = sampled_vector / energy

                        # Append data item
                        sig = np.stack((sampled_vector.real, sampled_vector.imag))
                        items.append([mod_type.modname, snr, chan_indx, sampler_indx, sps, ebw, sig])

                        # Increase sampler index by an amount great enough so
                        # that we expect to get a new channel often
                        sampler_indx += random.randint(vec_length, round(len(raw_output_vector)*.2))
                        modvec_indx += 1

    print "all done. writing to disk"

    if output:
        save_hdf5(items, ['ms', 'snr', 'chan_idx', 'offset', 'sps', 'ebw', 'iq_data'], output)

def save_hdf5(items, column_names, path, dset_name='radioml'):
    columns = []
    category_columns = {}

    # Compute per-column dtype and data. Data is in numpy array form.
    for i, x in enumerate(items[0]):
        if type(x) == str:
            categories = sorted(set(x[i] for x in items))
            data = np.array([categories.index(x[i]) for x in items])
            columns.append(((column_names[i], data.dtype), data))
            category_columns[column_names[i] + '_categories'] = categories
        elif type(x) == np.ndarray:
            data = np.array([x[i] for x in items])
            columns.append(((column_names[i], data.dtype, data.shape[1:]), data))
        else:
            data = np.array([x[i] for x in items])
            columns.append(((column_names[i], data.dtype), data))

    # Create compound numpy dtype for structured array
    dt = np.dtype([dt for dt, data in columns])

    # Create structured array and fill it with data
    arr = np.empty((len(items), ), dt)
    for i, (dt, data) in enumerate(columns):
        arr[dt[0]] = data

    # Write numpy structured array to HDF5 file
    with h5py.File(path, 'w') as f:
        dset = f.create_dataset(dset_name, (len(arr),), arr.dtype)

        for k in category_columns:
            dset.attrs[k] = category_columns[k]

        dset.write_direct(arr)

def main():
    parser = argparse.ArgumentParser(description='Generate RadioML 2016-like data set.')
    parser.add_argument('-d', '--debug', action='store_const',
                        const=logging.DEBUG,
                        dest='loglevel',
                        default=logging.WARNING,
                        help='print debugging information')
    parser.add_argument('-v', '--verbose', action='store_const',
                        const=logging.INFO,
                        dest='loglevel',
                        help='be verbose')
    parser.add_argument('--seed', type=int,
                        default=2016,
                        help='set random seed')
    parser.add_argument('--sps', action='store_true',
                        default=False,
                        help='vary samples per symbol')
    parser.add_argument('--ebw', action='store_true',
                        default=False,
                        help='vary excess bandwidth')
    parser.add_argument('-n', type=int,
                        default=1000,
                        help='number of signals to generate per parameter set')
    parser.add_argument('-o', '--output',
                        required=True,
                        help='output file')

    # Parse arguments
    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(format='%(asctime)s:%(name)s:%(levelname)s:%(message)s',
                        level=args.loglevel)

    generate(output=args.output,
             seed=args.seed,
             nvecs_per_key=args.n,
             vary_sps=args.sps,
             vary_ebw=args.ebw)

if __name__ == "__main__":
    main()
