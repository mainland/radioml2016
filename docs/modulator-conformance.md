# Validate the RadioML transmitters

The clean-modulator conformance check drives all eleven transmitter classes
with deterministic data, omits the channel model, and recovers the transmitted
message with reference computations in NumPy and SciPy. AM-SSB uses the
explicit cosine repair because the historical path nearly suppresses its
message. The check validates the transmitter stage separately from noise,
fading, frequency offset, sample-rate offset, window extraction, and dataset
normalization.

Run the check in the pinned reproducible image:

```sh
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -w /work \
  radioml2016:reproducible \
  python2.7 -m pytest -q tests/check_modulators.py
```

The command exits unsuccessfully when a conformance threshold is violated. To
write the acquisition offsets and measured recovery metrics to JSON, run:

```sh
mkdir -p output/conformance
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -v "$PWD/output/conformance:/out" -w /work \
  radioml2016:reproducible \
  python2.7 tests/check_modulators.py --output /out/modulators.json
```

The direct command and pytest run execute the same `run_checks()` function.
Only the direct command serializes the returned measurements.

## Reference receivers

The default cases for the six linear digital transmitters use 8 samples per
symbol and excess bandwidth 0.35. The check groups the deterministic input bits
MSB first, constructs the documented input-indexed constellations, applies an
independently implemented root-raised-cosine matched filter, acquires symbol
timing and delay, and makes nearest-neighbor decisions. Each transmitter must
recover 512 symbols without error and have RMS error-vector magnitude below
0.005 after one complex gain correction.

The pinned `gr-mapper` source names every supplied permutation a `greymap`, but
that name does not describe every emitted constellation. BPSK, QPSK, 8PSK, and
QAM16 have nearest-neighbor Gray labels. PAM4 has one non-Gray transition among
its three adjacent pairs, and QAM64 has 64 non-Gray transitions among its 112
horizontal and vertical adjacent pairs. The reference receiver constructs the
PSK mappings by decoding Gray labels and records the QAM mappings as spatial
bit-label grids. It preserves the non-Gray PAM4 and QAM64 behavior because that
behavior is part of the pinned transmitter implementation.

The GFSK and CPFSK receivers calculate phase increments, acquire symbol timing
and polarity, and decide bits from the sign of the mean increment in each
symbol. Each transmitter must recover 1,024 bits without error. The two mean
frequency levels must differ by more than 0.05 radians per sample, and the
relative standard deviation of the complex envelope must remain below
`1e-4`.

The parameter matrix also runs every digital transmitter at the boundaries of
SPS 2--12 and roll-off or BT 0.1--0.5, one parameter at a time, and at seeded
interior combinations. Its `excess_bandwidth` report field means RRC roll-off
for linear modulations and Gaussian-filter BT for GFSK. Linear transmitters
must recover every symbol with RMS EVM below 0.05. Low-BT GFSK has multi-symbol
pulse memory, so the receiver trains a 65-tap linear equalizer on one
deterministic segment and requires zero errors on a disjoint held-out segment.

The WBFM receiver calculates phase differences using the configured 75 kHz
maximum deviation. It inverts the documented bilinear pre-emphasis transfer
function, acquires the five-to-one decimation phase and delay, and compares the
recovered audio with the input multitone. Correlation must exceed 0.999,
normalized RMS error must remain below 0.01, and relative envelope variation
must remain below `1e-4`.

The AM receivers coherently recover the real message after fitting delay and
gain. Correlation must exceed 0.999, normalized RMS error must remain below
0.05, and carrier amplitude must remain within 0.95 to 1.05. AM-DSB sideband
imbalance must remain below 0.1 dB. The fixed AM-SSB path must select positive
complex-baseband frequencies and suppress the other sideband by at least 40 dB.

These thresholds express clean-channel properties with margins around the
measurements from the pinned Linux amd64 image. Zero symbol and bit errors are
exact requirements because the check adds no noise or channel impairments.

## Scope and observed limitations

The check establishes clean message transfer and the listed modulation-specific
properties. It does not establish receiver performance under channel
impairments, calibrate dataset SNR labels, or replace broader randomized
testing. The parameter sweep covers the stated ranges, not every value the CLI
can accept.

The WBFM transmitter produces five output samples per 44.1 kHz input sample,
which is 220.5 kHz. The dataset generator configures its channel model for 200
kHz. The conformance receiver uses the transmitter's actual 220.5 kHz rate and
therefore does not resolve that generator-level mismatch.

The AM-SSB check selects the local `--fixed-am-ssb` implementation. That
implementation is the provenance-pinned minimal cosine repair documented in
[reproducible generation](reproducible-generation.md#am-ssb-implementation),
not an upstream RadioML patch.
