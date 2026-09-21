# RadioML 2016 dataset generation

This repository generates deterministic datasets with the RadioML 2016.10a
modulations, labels, and window layout. It pins a Linux amd64 environment,
assigns every random source an explicit seed, and fixes the GNU Radio execution
order. The generated data is a reconstruction, not a byte-for-byte copy of the
distributed dataset.

The [historical environment guide](docs/historical-environment.md) records the
version evidence and its limits. Programs in [scripts/](scripts/) reproduce the
noise analysis against a separately supplied copy of the distributed dataset.
The [mapper-version investigation](docs/mapper-version-evidence.md) estimates
actual SNR without recovering the noise RNG state, calibrates the estimator
against paired mapper candidates, and fits the relative constellation powers
for no normalization, the February 2016 accumulator bug, and the October 2016
fix. A direct candidate with advancing channel seeds confirms the earlier
no-normalization behavior, which is now the default. That candidate differs
from the distributed dataset by a common 2.871 dB SNR offset. Restarting the
channel seed reduces the offset to 0.080 dB against the retained original-data
curves, with 0.039 dB RMS residual after removing it.

## Build the environment

Clone recursively to obtain the original text and audio sources:

```sh
git clone --recursive https://github.com/mainland/radioml2016
cd radioml2016
docker build --platform linux/amd64 -t radioml2016:historical .
docker build --platform linux/amd64 -f Dockerfile.reproducible \
  -t radioml2016:reproducible .
```

Both images are required: the reproducible image extends the historical
candidate. The [historical environment guide](docs/historical-environment.md)
explains the selected versions and the noise-evidence investigation.

During the reproducible-image build, the pinned historical decoder converts
the MP3 source into the exact float32 stream consumed by the analog
transmitters. The build verifies both the input MP3 and derived stream by
SHA-256. Dataset generation reads that canonical stream, so later runs do not
depend on MP3 decoder behavior.

The image uses the January 10, 2016 `gr-mapper` revision before constellation
normalization was introduced. That choice is based on the distributed
dataset's relative SNR across six digital modulations, not on its publication
date. The recorded 2.871 dB common absolute-SNR mismatch applies to the
advancing-seed comparison.

## Generate the compatibility dataset

Use the original generator parameters and specify every seed and the scheduler:

```sh
./build_dataset \
  --python-seed 201610 \
  --numpy-seed 201610 \
  --channel-seed 0x1337 \
  --scheduler sts \
  --frames-per-key 1000 \
  --output RML2016.10a_reproducible.dat
```

The output contains 11 modulations, the 20 SNR labels from -20 through 18,
1,000 windows per key, and 128 complex samples per window. Its Python 2 pickle
uses protocol 0 and maps each `(modulation, SNR)` key to a
`float32[1000, 2, 128]` array.

The generator defaults to GNU Radio's single-thread scheduler (`STS`). The
reproducibility test requires byte-identical output across fresh STS processes.
Use `--scheduler tpb` only to investigate the thread-per-block scheduler; TPB
is outside the reproducibility guarantee.

The result is not byte-identical to the distributed RML2016.10a pickle. The
original Python, NumPy, and process-global channel RNG states, scheduler
interleaving, and complete environment are unknown. The supported claim is a
deterministic reconstruction that preserves the known generator semantics and
output schema in the pinned Linux amd64 image.

The representative 80-window, two-label compatibility fixture has SHA-256
`a1dfcf6d9d5a5e574ad5538ce069a90c7b6b0b0348bc81b9910b640c6c2e928f`.
The test suite treats this as a golden value, not merely as equality between
two fresh runs.

Do not pass `--fixed-am-ssb`, `--fixed-wbfm`, `--settled-windows`,
`--vary-analog-source`, `--sps`, or `--ebw` for this profile. The first four
options repair known historical behavior or repeated source content. The range
options change transmitter parameters and consume additional Python RNG draws,
even when both endpoints are equal. Those variants are reproducible, but they
are not the closest mirror of the distributed dataset's generator.

For a smaller run:

```sh
./build_dataset --python-seed 42 --numpy-seed 43 --channel-seed 44 \
  --modulations BPSK QPSK --snrs 18 --frames-per-key 80 --output example.dat
```

### Channel seed policy

Every flag defaults to the baseline behavior. The default
`--channel-seed-policy restart` reuses the supplied channel base seed for
every transmission, following the published constructor argument. In the
patched runtime this repeats the private channel streams. It does not replay
the original shared RNG interleaving.

Pass `--channel-seed-policy advance` to advance the base by four for each
transmission, independently of analog source selection. This reproduces the
earlier advancing-seed fixture:
`bf8183edabea8e3c608ec5cde7cfa6818187ce999d82dbb7ab3a6ed1def2f697`.
The [generation guide](docs/reproducible-generation.md#seeds) defines the
seed range, component routing, and wraparound.

### Canonical analog source

The historical continuous-source path decodes
`source_material/serial-s01-e01.mp3`, groups consecutive mono `int16` samples
as complex values, scales by `float32(1/65535)`, and retains the real part.
Consequently, it keeps every other decoded mono sample. The reproducible image
performs that exact conversion once at build time with
[`scripts/decode_analog_source.cc`](scripts/decode_analog_source.cc).

The canonical stream contains 70,056,888 little-endian float32 items and has
SHA-256
`dfa1cdf1d11950f099f685c9c0d2a1197019415ffcf50c8d8f1988dc532a8325`.
Its first 10,000 items have SHA-256
`95aa6c9f2aa1ff9cf37df432d6ee47170859cfdef2050ffcc684e5487580e1fa`,
matching the output previously measured through the original GNU Radio source
flowgraph. The historical image retains the MP3 path for provenance work; the
reproducible generator requires the canonical stream installed in its image.

### Vary the analog source segment

By default, every analog transmission retains the historical behavior of
starting at item zero of the source. Add `--vary-analog-source` to assign each
analog transmission a different aligned 10,000-item segment:

```sh
./build_dataset --vary-analog-source --analog-source-seed 201610 \
  --output varied-analog.dat
```

The option permutes all 7,005 complete segments without replacement. Its
separate RNG defaults to `--seed`, so segment selection does not perturb
window-position or channel random streams. The generator fails instead of
reusing source material if a run requires more segments. Omitting the option
consumes no source-selection draws and preserves the compatibility pickle
hash. The pickle contains only windows and labels, so retain the command and
seed with the generated artifact.

### AM-SSB repair

The original AM-SSB flowgraph nearly suppresses the message because it uses a
real sine oscillator at zero frequency. This behavior remains the default for
generator compatibility. Add `--fixed-am-ssb` to change that oscillator to
cosine without changing the remaining blocks, label, seeds, or evaluation
order. The repair follows from the published source and measured failure
mechanism. It is not an upstream patch or a reconstruction of a replacement
flowgraph.

The reproducibility regression demonstrates deterministic message transfer.
The separate conformance and channel controls measure sideband suppression and
the historical SNR-label semantics.

### WBFM rate repair

The original WBFM block emits 220.5 ksample/s into a channel configured for
200 ksample/s. This mismatch remains the default for generator compatibility.
Add `--fixed-wbfm` to insert an exact 400/441 rational resampler before the
channel. The repair changes the channel input rate to 200 ksample/s without
changing the native WBFM modulator.

### Vary SPS and pulse shaping

Use `--sps MIN MAX` to draw an integer samples-per-symbol value from the
inclusive range for each digital transmission. Use `--ebw MIN MAX` to draw RRC
roll-off for linear modulations or Gaussian-filter BT for GFSK. These are
distinct parameters. For example:

```sh
./build_dataset --sps 2 12 --ebw 0.1 0.5 --output varied.dat
```

Both draws use `--python-seed`. Omitting an option consumes no additional
random draw and retains its generator default: SPS 8 and roll-off or BT 0.35.
CPFSK ignores `--ebw`.

### Skip transmitter startup

The historical generator draws its first post-channel window offset uniformly
from the inclusive range 50--500. That range begins before the startup response
ends for the six RRC transmitters, WBFM, and repaired AM-SSB. Add
`--settled-windows` to shift the same 451-value uniform draw so its lower bound
is at or beyond a modulation-specific startup guard:

```sh
./build_dataset --settled-windows --sps 2 12 --ebw 0.1 0.5 \
  --output settled.dat
```

The guard uses the actual SPS and repair flags. EBW changes the distribution of
RRC response energy but not the filter's finite support, so it does not change
the conservative RRC guard. Omitting `--settled-windows` preserves the original
50--500 draw and default bytes. See [filter delay
analysis](docs/filter-delay-analysis.md) for the measurements, formulas, and
limits.

See [reproducible generation](docs/reproducible-generation.md) for seed routing,
runtime changes, and the scope of reproducibility.

## Check reproducibility

```sh
mkdir -p output/check
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -v "$PWD/output/check:/out" -w /work \
  radioml2016:reproducible \
  python2.7 tests/check_reproducibility.py --output /out
```

The check compares three fresh runs across all 11 modulations at two SNRs
with 80 windows per key, then checks independent seed changes.

## Check transmitter and channel conformance

Run [tests/check_modulators.py](tests/check_modulators.py) in the reproducible
image to demodulate deterministic clean outputs from all eleven transmitters:

```sh
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -w /work \
  radioml2016:reproducible \
  python2.7 -m pytest -q tests/check_modulators.py
```

Run `python2.7 -m pytest -q -m 'not slow' tests` to add deterministic channel,
filter-delay, and mapper-evidence checks. The checks use independent reference
computations for message recovery and signal properties. See [modulator
conformance](docs/modulator-conformance.md) for receiver methods and [filter
delay analysis](docs/filter-delay-analysis.md) for startup-window measurements.
The modulator, channel-control, and filter-delay scripts also provide direct
`--output` interfaces for JSON measurement reports.

## Historical source references

[Earlier generators and their helpers](historical/README.md) are preserved
unchanged, with source revision, hashes, and a comparison of their sampling
and channel settings. They provide evidence of the generator's development.

## References

The [DeepSig release page](https://www.deepsig.ai/datasets/) identifies
RadioML 2016.10A as the release that supersedes 2016.04C and links its
[generator source](https://github.com/radioML/dataset). It associates the
paper below with 2016.04C. The paper provides background on modulation
recognition. The 2016.10A release description and generator history identify
the dataset studied here.

T. J. O'Shea, J. Corgan, and T. C. Clancy, "Convolutional Radio Modulation
Recognition Networks," EANN 2016, pp. 213--226. [DOI:
10.1007/978-3-319-44188-7_16](https://doi.org/10.1007/978-3-319-44188-7_16).
