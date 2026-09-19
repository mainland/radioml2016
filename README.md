# Reproducible RadioML 2016.10a-like datasets

This repository generates RadioML 2016.10a-like datasets for studying dataset
quality. The Baseline profile retains the published generator's signal paths,
labels, sampling, and normalization in an evidence-supported Python 2.7 / GNU
Radio environment. Explicit random seeds, a small runtime patch, and fixed
execution settings make generation repeatable.

Baseline is a reproducible approximation to the historical generation process.
The distributed dataset's original random states, execution schedule, and
complete software environment are unknown. The selected mapper matches the
distributed data's relative constellation powers. Restarting the channel seed
reduces the earlier advancing-seed candidate's common SNR difference from
2.871 dB to 0.080 dB in the retained six-modulation comparison. [Environment
evidence](docs/historical-environment.md) records what is measured, inferred,
and chosen.

## Reproduce

Use Docker with Linux amd64 support and a recursive checkout. Both image builds
are required: the reproducible image extends the historical candidate.

```sh
git clone --recursive https://github.com/mainland/radioml2016
cd radioml2016
docker build --platform linux/amd64 -t radioml2016:historical .
docker build --platform linux/amd64 -f Dockerfile.reproducible \
  -t radioml2016:reproducible .
```

Run the validation suite, including full dataset hash checks and the
byte-reproducibility matrix:

```sh
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -w /work radioml2016:reproducible \
  python2.7 -m pytest -q tests
```

All generator flags default to Baseline settings, including restarting the
channel seed for each transmission. Generate its pickle with:

```sh
mkdir -p output/datasets
./build_dataset --python-seed 201610 --numpy-seed 201610 \
  --channel-seed 0x1337 --scheduler sts --frames-per-key 1000 \
  --output output/datasets/RML2016.10a-Reproducible-Baseline.dat
```

The pickle contains 11 modulations, 20 labels from -20 through 18, and 1,000
windows per key. Each array has shape `float32[1000, 2, 128]`, with I and Q in
separate rows. Each complex window is divided by `sum(abs(window))`.
Labels are historical control values, not measured SNR.

The **RML2016.10a-Reproducible** family has three named profiles:

- **Baseline** preserves the historical signal, sampling, and noise behavior.
- **Calibrated** changes AM-SSB message transfer, WBFM rate matching, startup
  exclusion, and SNR calibration over exported windows.
- **Calibrated-VariedAudio** adds seeded nonoverlapping analog source segments.

The [dataset definitions](docs/datasets.md) give the exact configurations,
generation commands, and SHA-256 hashes. The recipes produce Baseline as pickle
and HDF5, and the other profiles as HDF5. All HDF5 profiles include SNR
measurements.

The [generation guide](docs/reproducible-generation.md) gives smaller runs,
attributed HDF5 output, exact pickle/HDF5 comparison, artifact preservation,
seed routing, and the reproducibility limits. Preserve the built images:
transitive system dependencies are recorded but are not fully locked against
future changes to the Ubuntu package archive.

## Review the scientific basis

| Question | Evidence and procedure |
| --- | --- |
| Why these historical dependencies? | [Environment selection](docs/historical-environment.md) and [noise reconstruction](docs/noise-evidence.md) |
| Why the January 2016 mapper? | [Calibrated three-candidate SNR comparison](docs/mapper-version-evidence.md) |
| Where are the measurements behind those choices? | [Retained reports, hashes, and scope](evidence/README.md) |
| Do the transmitters transfer their messages? | [Modulator conformance](docs/modulator-conformance.md) |
| Do the windows include transmitter startup? | [Filter-delay measurements and guards](docs/filter-delay-analysis.md) |
| What changes were required for determinism? | [Seeds and execution](docs/reproducible-generation.md#seeds) and [runtime patch](patches/gnuradio-3.7.10.1-fastnoise.patch) |

The environment and mapper investigations use a separately supplied original
pickle identified by SHA-256. Generating a new dataset and running the tests
do not require that original file. The retained reports are recorded
observations, not substitutes for rerunning the documented checks.

## Investigate dataset quality

The baseline preserves known defects so their effects can be studied. Repairs
are explicit interventions, not evidence of what the original authors ran.

| Question or intervention | Generator control |
| --- | --- |
| Recover the nearly suppressed AM-SSB message | `--fixed-am-ssb` |
| Match WBFM output to the 200 ksample/s channel | `--fixed-wbfm` |
| Exclude transmitter startup using measured guards | `--settled-windows` |
| Avoid restarting every analog transmission at the same source segment | `--vary-analog-source` |
| Advance channel seeds between transmissions | `--channel-seed-policy advance` |
| Vary digital samples per symbol and pulse shaping | `--sps MIN MAX`, `--ebw MIN MAX` |
| Correct noise scaling or calibrate exported-window SNR | `--snr-mode scaled`, `--snr-mode calibrated` |
| Retain transmission ancestry, offsets, and optional SNR measurements | `--output-format hdf5`, `--measure-snr` |

Use HDF5 for quality studies. Its transmission and source coordinates support
checking shared ancestry across evaluation splits. All three named profiles
restart the same channel streams, and different transmissions can share source
content. Baseline also contains bit-identical windows under different
transmission IDs. Grouping by transmission therefore does not prevent all
leakage or provide a held-out channel realization. The
[dependence audit](docs/datasets.md#dependence-and-evaluation-splits) records
these limits and the duplicate counts. The
[generation guide](docs/reproducible-generation.md) defines each control and the
schema. The [sigmf_zarr import contract](docs/sigmf-zarr-import-contract.md)
covers downstream conversion.

## Repository map

- Root Python modules implement the one supported 2016.10a generator.
- `Dockerfile`, `Dockerfile.reproducible`, and `patches/` define the environments.
- `scripts/` contains evidence, measurement, and artifact-comparison tools.
- `tests/` checks signal behavior, metadata, and deterministic generation.
- `docs/` explains the methods. `evidence/` retains selected small reports.
- `source_material/` pins the original text and audio as a Git submodule.
- `output/` holds new generated artifacts and is ignored by Git.

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
Recognition Networks," EANN 2016, pp. 213--226.
[DOI: 10.1007/978-3-319-44188-7_16](https://doi.org/10.1007/978-3-319-44188-7_16).
