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
transmission, without changing the source-selection policy. This reproduces the
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
