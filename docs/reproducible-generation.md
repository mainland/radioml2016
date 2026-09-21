# Generate and validate a RadioML 2016.10a-like dataset

The generator starts from the pinned
[environment reconstruction](historical-environment.md), assigns every random
source an explicit seed, and applies a GNU Radio patch that removes shared
channel RNG state. The output is a new dataset. The distributed dataset's
random states and execution schedule remain unknown.

## Build and run

From a recursive checkout with Docker and Linux amd64 support:

```sh
docker build --platform linux/amd64 -t radioml2016:historical .
docker build --platform linux/amd64 -f Dockerfile.reproducible \
  -t radioml2016:reproducible .
./build_dataset --python-seed 201610 --numpy-seed 201610 \
  --channel-seed 0x1337 --scheduler sts --output RML2016.10a_dict.dat
```

`build_dataset` mounts the checkout read-write so it can create the requested
output, runs as the caller's UID/GID, and disables networking. Run it from the
repository root. Both image builds are required because the reproducible image
extends the historical candidate. `RML_IMAGE` may select another compatible
image. Preserve the source commit, built-image identity, command line, and
output hash with each generated artifact.

The reproducible-image build converts the MP3 input into a canonical analog
source stream and verifies both files by SHA-256. Generation therefore does
not invoke the MP3 decoder. The historical image retains the original decoder
path for evidence collection.

The default output retains the original pickle protocol 0 and
`dict[(modulation, snr)] -> float32[1000, 2, 128]` layout. Python 3 can read it
using `pickle.load(stream, encoding='latin1')`. For smaller runs, use
`--modulations BPSK QPSK --snrs -20 18 --frames-per-key 80`. SNRs are sorted.
Modulations follow transmitter order, with digital paths before analog paths.
Streams continue across selected keys and transmissions, so a subset run need
not equal slicing a full dataset.

For the representative `--frames-per-key 80 --snrs -20 18` invocation, the
Baseline pickle SHA-256 is
`a1dfcf6d9d5a5e574ad5538ce069a90c7b6b0b0348bc81b9910b640c6c2e928f`.
Adding `--channel-seed-policy advance` produces
`bf8183edabea8e3c608ec5cde7cfa6818187ce999d82dbb7ab3a6ed1def2f697`.
The slow regression requires both literal digests and repeatability across
fresh processes. The [baseline mapper control](../evidence/baseline.json)
used advancing seeds. Changing only its mapper to the October revision
produces the former `c1158937...` fixture. Removing unused generator imports
leaves that January output unchanged. These checks detect changes that
fresh-process repeatability alone would miss. They do not establish that the
selected environment generated the distributed dataset.

Generation selects GNU Radio's single-thread scheduler (`STS`) before any
flowgraph is constructed. The reproducibility fixture requires identical
pickle bytes across fresh STS processes. Use `--scheduler tpb` only to
investigate the historical thread-per-block scheduler (`TPB`). TPB is not part
of the reproducibility guarantee for parameter or seed variations.

## Generator variants

### Canonical analog source

The original continuous-source flowgraph uses the pinned mediatools decoder,
passes its mono `int16` stream through `interleaved_short_to_complex`,
multiplies by `float32(1/65535)`, and retains output zero from
`complex_to_float`. It therefore retains even-indexed mono samples rather than
performing an ordinary mono conversion. The source block emits silence after
end of file, so an unbounded GNU Radio sink cannot be used to discover the
decoded length.

The decoded mono audio is sampled at 44,100 samples/s. Keeping every other
sample leaves 22,050 source items per second of the recording, but all three
analog transmitters interpret those items at 44,100 samples/s. The implied
playback is therefore twice as fast as the decoded recording. This sample
selection applies no antialiasing filter, so source content above 11,025 Hz
can alias before modulation. Freezing the stream preserves both the time-scale
change and any aliasing from that selection. It does not measure how much
high-frequency content the recording contains.

At image-build time,
[`decode_analog_source.cc`](../scripts/decode_analog_source.cc) uses the same
pinned mediatools implementation, stops when its decoder reaches end of file,
and reproduces the even-sample float32 mapping. The verified input and output
are:

| Artifact | Size or count | SHA-256 |
| --- | ---: | --- |
| `serial-s01-e01.mp3` | 25 MiB | `dad05be9b299f3d44bde87d161d525ad0660109ada40b66e33d12999594a069b` |
| Canonical `<f4` stream | 70,056,888 items | `dfa1cdf1d11950f099f685c9c0d2a1197019415ffcf50c8d8f1988dc532a8325` |

The decoder emits 140,113,775 mono shorts. Keeping global even indexes yields
70,056,888 floats, including the final even-indexed sample. The first 10,000
canonical items have SHA-256
`95aa6c9f2aa1ff9cf37df432d6ee47170859cfdef2050ffcc684e5487580e1fa`,
which exactly matches the recorded original flowgraph prefix. Replacing the
runtime decoder with this stream leaves the representative compatibility
pickle hash unchanged.

## Seeds

| Option | Default and purpose |
| --- | --- |
| `--seed` | `201610`; supplies Python and NumPy defaults |
| `--python-seed` | Overrides the sampler's initial offsets and window increments |
| `--numpy-seed` | Overrides the digital source masks; analog sources draw no mask |
| `--channel-seed` | `0x1337` (4919); channel base seed |
| `--channel-seed-policy` | `restart`; reuse the base for each transmission, or `advance` to change it |

Python and NumPy seeds accept `0..4294967295`. Channel seeds
accept `1..2147483644`. GNU Radio treats zero as a time seed. With the default
`--channel-seed-policy restart`, every transmission uses the supplied base
seed. This follows the published generator's repeated `0x1337` constructor
argument. In the patched runtime it also restarts the private channel streams,
so equal-length transmissions share the same channel evolution and noise
sequence before amplitude scaling. It does not recover the original shared
RNG interleaving.

With `--channel-seed-policy advance`, transmission `b`, counted from zero
across the run, uses
`base = 1 + ((channel_seed - 1 + 4*b) % 2147483644)`. The base advances across
modulation and SNR boundaries and wraps within the supported range. This
changes fading, drift, and noise realizations. It does not establish statistical independence between
transmissions.

Under either policy, AWGN uses `base`, sample-rate drift uses `base+1`,
carrier-frequency drift uses `base+2`, and fading path `i` uses angle seed
`base+i` and walk seed `base+i+1`.

## Deterministic evaluation

The [GNU Radio patch](../patches/gnuradio-3.7.10.1-fastnoise.patch) gives each
fast-noise instance private `drand48_data` state. It retains the historical
Gaussian pool construction and 48-bit recurrence, makes the pool/sign draw
order explicit, and assigns different seeds to clock and carrier drift.
Thread scheduling no longer assigns shared random draws to channel components.
This changes their joint random process from the original implementation.

Private RNG state is necessary but not sufficient for every TPB execution.
Different finite-stream work schedules can change a later transmission when
generation parameters alter source or sampler behavior. STS fixes the block
execution order and is therefore part of the reproducibility contract.

The generator retains the original loop order, source lengths, modulators,
channel parameters apart from seeds, window sampling, and normalization by
`sum(abs(window))`. CLI parsing and runtime checks live in
[generator_options.py](../generator_options.py). Source and transmitter code
retain their historical defaults. The image sets `PYTHONHASHSEED=0`,
`VOLK_GENERIC=1`, `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, and the
canonical analog-source path before Python starts. The helper requires these
settings, the verified source size, Python 2.7, and the patched runtime marker.

## Validation and limits

Run [tests/check_reproducibility.py](../tests/check_reproducibility.py) using
the container command in the [README](../README.md#check-reproducibility). It
compares three fresh processes across all 11 modulations at SNRs -20 and 18
with 80 windows per key, exercising multiple transmissions, and checks
independent Python, NumPy, and channel seed changes. It checks that the
default restarts the channel seed and that explicit advancement repeats its
separate fixture.

Byte identity applies to the tested Linux amd64 image, source inputs, and
execution settings. Other architectures or rebuilt dependencies may differ.
The environment-reconstruction image preserves GNU Radio's shared RNG for the
evidence investigation. Explicit seeds alone do not make that runtime
deterministic.
