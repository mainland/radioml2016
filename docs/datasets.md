# RML2016.10a-Reproducible datasets

The RML2016.10a-Reproducible family contains three RadioML2016.10a-like
datasets for studying dataset quality. Baseline approximates the historical
generation process within the evidence-supported, deterministic environment.
It does not recover the original examples. Calibrated and
Calibrated-VariedAudio introduce the following explicit interventions.

| Setting | Baseline | Calibrated | Calibrated-VariedAudio |
| --- | --- | --- | --- |
| AM-SSB zero-frequency oscillator | Historical sine | Cosine | Cosine |
| WBFM channel input rate | Historical 220.5 ksample/s | Resampled to 200 ksample/s | Resampled to 200 ksample/s |
| Initial window selection | Historical 50--500 offset | Measured startup guard | Measured startup guard |
| Noise policy | Historical label-to-amplitude rule | Calibrated over exported windows | Calibrated over exported windows |
| Channel seed policy | Restart | Restart | Restart |
| Analog source selection | Repeat the initial segment | Repeat the initial segment | Seeded nonoverlapping segments |
| Artifact formats | Pickle and HDF5 | HDF5 | HDF5 |

Each dataset contains 220,000 windows: 11 modulations, 20 labels from -20
through 18 in steps of 2, and 1,000 windows per key. Each window contains 128
complex samples, stored as `float32[2, 128]` in I/Q order and normalized by
`sum(abs(window))`. Digital samples per symbol and pulse shaping retain their
historical defaults: 8 samples per symbol, RRC roll-off 0.35 for linear
modulations, and Gaussian BT 0.35 for GFSK. CPFSK retains its original pulse
shape.

All profiles retain the historical analog source mapping: keep every other
44.1 ksample/s decoded mono sample, then interpret the result as 44.1 ksample/s
modulator input. This produces twice-speed playback relative to the decoded
recording and can alias source content before modulation. The WBFM rate repair
changes only the modulator-to-channel interface. The
[canonical-source description](reproducible-generation.md#canonical-analog-source)
explains the retained transformation.

All profiles use Python, NumPy, and analog-source seeds of 201610, initial
channel seed `0x1337` with `--channel-seed-policy restart`, and the
single-thread scheduler. All generator defaults select Baseline behavior.
`--channel-seed-policy advance` is a separate experimental control and is not
part of these profiles. HDF5 files include
transmission ancestry, analog source coordinates, normalization divisors, and
paired SNR measurements. Baseline's HDF5 I/Q and labels exactly match its
pickle. The pickle preserves the original dictionary layout and protocol 0.

The Calibrated profile enables `--fixed-am-ssb`, `--fixed-wbfm`,
`--settled-windows`, and `--snr-mode calibrated`. Calibrated-VariedAudio adds
`--vary-analog-source`. This varies audio content, not analog modulation
parameters. The [generation
guide](reproducible-generation.md#generator-variants) defines the mechanisms
and their limits.

Historical labels are control values. Calibrated labels specify aggregate
clean-signal to realized-noise power over the exported windows of each
transmission, before normalization. Individual windows can have different
measured SNRs, and signal power includes any carrier. Compare the recorded
measurements as well as labels. Baseline versus Calibrated combines several
interventions. Calibrated versus Calibrated-VariedAudio isolates the change
in source selection. These artifacts do not define training or evaluation
splits.

## Dependence and evaluation splits

Every transmission in all three profiles uses channel base seed `0x1337`.
The patched runtime restarts its fading, drift, and noise streams at each
transmission. Different transmission IDs therefore do not identify different
channel realizations. A named profile alone cannot supply a split that holds
out a different channel realization. Such a study needs additional runs with
different channel seeds and an explicit source-separation policy. Record those
runs separately from these reference artifacts, and check source reuse across
runs as well as within them.

The [recorded artifact audit](../evidence/dataset-quality.json) finds the
following excess bit-identical windows within modulation/SNR keys. A group of
`k` identical stored I/Q arrays contributes `k-1` to the count. All digital
classes have zero duplicates under this criterion.

| Profile | WBFM | AM-DSB | AM-SSB | Total |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 186 | 213 | 219 | 618 |
| Calibrated | 0 | 0 | 0 | 0 |
| Calibrated-VariedAudio | 0 | 0 | 0 | 0 |

For example, Baseline rows 8,327 and 8,939 are identical WBFM windows at label
-20 and post-channel offset 9,509, but belong to transmissions 221 and 237.
These are zero-based HDF5 row and sample indexes. Grouping by transmission
alone can therefore place identical examples in different splits. Keep all
windows from one transmission together, then audit duplicates and shared
source and channel ancestry across the proposed split.

The count compares complete stored float32 bytes without gain fitting or
rounding. It does not count near-duplicates or matches across different
modulation/SNR keys. Zero exact duplicates in the calibrated profiles does not
establish independence: both still restart the channel, and Calibrated also
reuses the same analog source segment. Calibrated-VariedAudio uses disjoint
segments within a run, but segment separation alone does not establish
statistical independence.

With the three reference HDF5 files in `output/datasets/`, reproduce the audit:

```sh
mkdir -p output/quality-audit
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -v "$PWD/output/quality-audit:/out" -w /work \
  radioml2016:reproducible \
  python2.7 scripts/audit_dataset_quality.py output/datasets/*.h5 \
    --output /out/quality.json
```

The command refuses to overwrite its report. Compare its `artifacts` entries
with the retained audit, including input hashes. The retained report identifies
the reviewed source snapshot and image. A fresh report identifies the audit
script and libraries, so the report metadata need not be byte-identical. SNR
summaries read the stored paired measurements without rerunning the channel.
Neither this audit nor its duplicate counts describe the original released
RadioML dataset.

## Generate the artifacts

Build both images as described in the [README](../README.md#reproduce), then
run from the repository root:

```sh
mkdir -p output/datasets
set -- --seed 201610 --python-seed 201610 --numpy-seed 201610 \
  --analog-source-seed 201610 --channel-seed 0x1337 \
  --channel-seed-policy restart --scheduler sts \
  --frames-per-key 1000 \
  --snrs -20 -18 -16 -14 -12 -10 -8 -6 -4 -2 0 2 4 6 8 10 12 14 16 18 \
  --modulations BPSK QPSK 8PSK PAM4 QAM16 QAM64 GFSK CPFSK WBFM AM-DSB AM-SSB

./build_dataset "$@" --snr-mode historical --output-format pickle \
  --output output/datasets/RML2016.10a-Reproducible-Baseline.dat
./build_dataset "$@" --snr-mode historical --output-format hdf5 --measure-snr \
  --output output/datasets/RML2016.10a-Reproducible-Baseline.h5
./build_dataset "$@" --fixed-am-ssb --fixed-wbfm --settled-windows \
  --snr-mode calibrated --output-format hdf5 --measure-snr \
  --output output/datasets/RML2016.10a-Reproducible-Calibrated.h5
./build_dataset "$@" --fixed-am-ssb --fixed-wbfm --settled-windows \
  --snr-mode calibrated --vary-analog-source --output-format hdf5 --measure-snr \
  --output output/datasets/RML2016.10a-Reproducible-Calibrated-VariedAudio.h5
```

## Reference hashes

These SHA-256 values identify complete serialized files, including HDF5
metadata. They apply to the pinned Linux amd64 runtime and the commands above.
The four files occupy about 1.26 GiB in total. The reference image ID is
`sha256:d79d833df84c954151a179d804aa1d0422f10c154097ab2c79d107db2ba19dfc`.
Rebuilding against changed transitive dependencies can produce different
bytes. Preserve the built image and [generation
provenance](reproducible-generation.md#preserve-a-review-artifact) with the
artifacts.

| File | SHA-256 |
| --- | --- |
| `RML2016.10a-Reproducible-Baseline.dat` | `af5d4a17ac2d1699e5e0c67198bacbdcc20caaa8988519bb33c6af5d208d8ec6` |
| `RML2016.10a-Reproducible-Baseline.h5` | `f5ce285c62b5c099ce0f0bc89057ff17298313f0ceab9260bbd4d40d9bdc7eaa` |
| `RML2016.10a-Reproducible-Calibrated.h5` | `caeb06bdb9791d8f86df52922ae70297d33795d694813b7a98e6ac17445423c5` |
| `RML2016.10a-Reproducible-Calibrated-VariedAudio.h5` | `df92c6ec10d9aab7dca7edb502ed156be893cb3e868b12154e8c4fab5eeffa64` |

## Check full reproduction

The [dataset regression](../tests/check_datasets.py) generates all four files
concurrently in four fresh processes, requires these literal hashes, and
compares the Baseline pickle and HDF5 I/Q and labels exactly. It is part of
the default pytest suite and carries the `slow` marker. It needs space for
about 1.26 GiB of generated files. Run it alone with:

```sh
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -w /work radioml2016:reproducible \
  python2.7 -m pytest -q tests/check_datasets.py
```

Pytest writes artifacts to temporary storage inside the container. To retain
the reproduced files, generator logs, commands, sizes, hashes, and comparison
report, use the direct interface with a new output directory:

```sh
mkdir -p output/datasets-reproduced
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -v "$PWD/output/datasets-reproduced:/out" \
  -w /work radioml2016:reproducible \
  python2.7 tests/check_datasets.py --output /out
```

The direct interface refuses to overwrite its artifacts, logs, or
`datasets.json` report. A mismatch fails the regression. Do not replace a
reference hash without reviewing the changed data, metadata, configuration,
or runtime that caused it.
