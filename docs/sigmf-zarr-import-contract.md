# HDF5 to sigmf_zarr import contract

The attributed HDF5 file is the Python 2.7 generator's interchange format.
Conversion and dataset splitting belong in the modern `sigmf_zarr` environment.
This repository supplies the contract and validation fixture, but no importer.
An importer must accept schema `radioml2016-attributed` version 1 and preserve
the following information exactly.

The reproducibility fixture uses GNU Radio's single-thread scheduler (`sts`).
Schema version 1 records the selected scheduler in `generation_options_json`
and also permits the experimental thread-per-block scheduler (`tpb`). An
importer must preserve that value rather than infer it from the schema version.
It must preserve all generation options, the `modulation_names_json` vocabulary
and order, and the `schema` and `schema_version` identifiers as source
provenance. It must also preserve the root `analog_source_json` identity and
coordinate definition.

## Sample and label mapping

- Convert `windows/iq[N,2,128]` to complex samples as
  `iq[:,0,:] + 1j*iq[:,1,:]`. The source dtype is little-endian `float32`.
- Map `windows/modulation_id` through the root
  `modulation_names_json` vocabulary. Do not infer labels from row order.
- Preserve `windows/snr_db` as the requested label and preserve `snr_mode` from
  `generation_options_json`. Only calibrated mode targets a measured
  post-channel SNR over the selected windows.
- Preserve `windows/transmission_number` as the group identifier and
  `windows/offset` as the zero-based post-channel sample coordinate.
- Preserve `windows/normalization_l1`. It is the float32 divisor applied to the
  raw complex window and permits amplitude-aware downstream analysis.
- Preserve the window-aligned SNR measurement validity flag, clean signal
  power, realized noise power, and measured SNR. Invalid powers and SNRs are
  NaN, not zero.

## Transmission mapping

Rows of every dataset under `transmissions` share the same index. The importer
must preserve SPS, EBW, native modulator rate, channel-input rate,
channel-model rate, channel seed, requested noise amplitude, post-channel
sample count, aggregate SNR measurement fields and window count, random mask
and validity flag, canonical analog-source offset, length and validity flag,
both transmitter repair flags, and `settling_guard_samples`. Zero SPS and NaN
EBW mean not applicable. Interpret `ebw` using the modulation: RRC roll-off for
the six linear modulations, Gaussian-filter BT for GFSK, and NaN for CPFSK and
analog modulations. Preserve the field name and value without treating roll-off
and BT as the same physical quantity. A zero random mask is meaningful only
when `random_mask_valid` is one. Analog source coordinates are meaningful only
when `analog_source_valid` is one. Invalid SNR measurements have a zero
measurement window count and NaN powers and SNR.

Preserve `channel_seed_policy` and `initial_channel_seed` from
`generation_options_json`, together with every transmission's `channel_seed`.
A missing policy in an earlier schema-version-1 file means `advance`. It does
not mean the command-line default, `restart`. Restarting transmissions reuse
the supplied base. Advancing transmissions increment it by four, wrapping in
`1..2147483644`, across the complete run. A seed identifies the channel
configuration, not a unique transmission or an independent realization.

Preserve `vary_analog_source` and `analog_source_seed` from
`generation_options_json`. When variation is enabled, validate that applicable
source intervals are in bounds, 10,000 items long, aligned to 10,000, and do
not overlap. When it is disabled, applicable offsets are zero. These are
pre-modulator canonical-source coordinates, not post-channel window offsets.

Preserve `settled_windows` from `generation_options_json`. When it is true,
validate `windows/offset >= transmissions/settling_guard_samples` through each
window's transmission-number reference. When it is false, preserve the guard
as provenance so later analysis can identify windows selected during startup.

Preserve `measure_snr` from `generation_options_json`. Calibrated mode records
measurements even when that option is false because calibration already
requires the paired clean run. Treat `snr_measurement_valid`, rather than the
option alone, as authoritative for each row.

All windows with the same transmission number must remain in the same split.
The importer may replace the file-local integer with a globally unique group
identifier, but it must retain a reversible mapping to the source artifact and
row number. Transmission grouping does not prevent shared source content or,
with `restart`, repeated channel and noise streams across different IDs.
Baseline even contains bit-identical windows under different transmission IDs.
An importer must not describe such grouping as a channel-held-out split. All
three named profiles use one channel base seed, so that evaluation requires
additional generation with different seeds and an explicit source-separation
policy. Preserve the metadata needed to audit those choices. The
[dependence audit](datasets.md#dependence-and-evaluation-splits) records the
reference artifacts' duplicate counts and the limits of that measurement.

## Validation fixture

Generate a persistent import fixture with the direct reporting interface:

```sh
mkdir -p output/reproducibility
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -v "$PWD/output/reproducibility:/out" -w /work \
  radioml2016:reproducible \
  python2.7 tests/check_reproducibility.py --output /out
```

The command writes `attributed-0.h5`, a byte-identical repeat named
`attributed-1.h5`, and `reproducibility-matrix.json`. The matrix's
`interchange_contract` object records every required dataset's shape, NumPy
dtype string, and SHA-256 hash over its C-order bytes. A downstream import test
should import `attributed-0.h5`, export the same logical arrays from
`sigmf_zarr`, and compare those fingerprints before implementing group-aware
splits. Running the check through pytest validates the same contract but places
these files in a temporary directory that the container removes.

The array fingerprints do not cover root HDF5 attributes. The downstream test
must compare `schema`, `schema_version`, `modulation_names_json`, and
`generation_options_json` separately, along with `analog_source_json`.

HDF5 object bytes need not survive conversion. Numeric arrays, vocabulary
order, units, coordinate origins, applicability markers, and provenance flags
must survive.
