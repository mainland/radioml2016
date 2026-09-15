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

The default output retains the original pickle protocol 0 and
`dict[(modulation, snr)] -> float32[1000, 2, 128]` layout. Python 3 can read it
using `pickle.load(stream, encoding='latin1')`. For smaller runs, use
`--modulations BPSK QPSK --snrs -20 18 --frames-per-key 80`. SNRs are sorted.
Modulations follow transmitter order, with digital paths before analog paths.
Streams continue across selected keys and transmissions, so a subset run need
not equal slicing a full dataset.

For the representative `--frames-per-key 80 --snrs -20 18` invocation,
the restarting-channel pickle has SHA-256
`a1dfcf6d9d5a5e574ad5538ce069a90c7b6b0b0348bc81b9910b640c6c2e928f`.
The regression requires this literal hash and fresh-process repeatability.

Generation selects GNU Radio's single-thread scheduler (`STS`) before any
flowgraph is constructed. The reproducibility fixture requires identical
pickle bytes across fresh STS processes. Use `--scheduler tpb` only to
investigate the historical thread-per-block scheduler (`TPB`). TPB is not part
of the reproducibility guarantee for parameter or seed variations.

## Seeds

| Option | Default and purpose |
| --- | --- |
| `--seed` | `201610`; supplies Python and NumPy defaults |
| `--python-seed` | Overrides the sampler's initial offsets and window increments |
| `--numpy-seed` | Overrides the digital source masks; analog sources draw no mask |
| `--channel-seed` | `0x1337` (4919); base reused for every transmission |

Python and NumPy seeds accept `0..4294967295`. Channel seeds accept
`1..2147483644`. GNU Radio treats zero as a time seed. Every transmission
reuses the supplied channel base, following the published generator's repeated
`0x1337` constructor argument. In the patched runtime this restarts the private
channel streams, so equal-length transmissions share the same channel evolution
and noise sequence before amplitude scaling. It does not recover the original
shared RNG interleaving.

AWGN uses `base`, sample-rate drift uses `base+1`, carrier-frequency drift uses
`base+2`, and fading path `i` uses angle seed `base+i` and walk seed `base+i+1`.

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
remain unchanged. The image sets `PYTHONHASHSEED=0`, `VOLK_GENERIC=1`,
`OMP_NUM_THREADS=1`, and `OPENBLAS_NUM_THREADS=1` before Python starts.
The helper requires these settings, Python 2.7, and the patched runtime marker.

## Validation and limits

Run [tests/check_reproducibility.py](../tests/check_reproducibility.py) using
the container command in the [README](../README.md#check-reproducibility). It
compares three fresh processes across all 11 modulations at SNRs -20 and 18
with 80 windows per key, exercising multiple transmissions, and checks
independent Python, NumPy, and channel seed changes.

Byte identity applies to the tested Linux amd64 image, source inputs, and
execution settings. Other architectures or rebuilt dependencies may differ.
The environment-reconstruction image preserves GNU Radio's shared RNG for the
evidence investigation. Explicit seeds alone do not make that runtime
deterministic.
