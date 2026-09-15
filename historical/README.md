# Historical generator references

These files preserve the earlier dataset generator, source-alphabet generator,
and their slicing and statistics helpers for provenance review. Their contents
are unchanged from Git revision
`20f99215e01a80489ad0aa4f41d86207efe788f6`, the source tree preceding the local
environment reconstruction. The maintained generation workflow is documented in the
[repository README](../README.md).

| File | SHA-256 |
| --- | --- |
| `generate_RML2016.04c.py` | `9735eb242202d59f95660fab0e99d5712660ea7967e365b95504b7e184b6d72a` |
| `generate_alphabet_dataset.py` | `cdb63f3c1b513fedf2af48735f0a16287e4e3d1e02f46399dadb3e4a81fdd1f0` |
| `timeseries_slicer.py` | `9471a88efbfc5f050de405575c7e438591da3f193cb392650a8f6de399f87e9f` |
| `analyze_stats.py` | `0ca1eeef382e109b9bd8ccd3b09b8708b19b5ca5c07bb228ab42cbba73685154` |

The scripts originally lived at the repository root. Their imports refer to
the companion modules and runtime of that source revision. To inspect the
complete source tree, including the original `source_alphabet.py` and
`transmitters.py`, export it from Git:

```sh
mkdir -p output/upstream-source
git archive 20f99215e01a80489ad0aa4f41d86207efe788f6 | \
  tar -x -C output/upstream-source
```

The source-material submodule and historical runtime are separate dependencies.
These reference files do not establish which environment produced a released
dataset.

## Evidence in the earlier generator

The following comparison uses the upstream 04c and 10a files at that revision.

| Property | 04c source | 10a source |
| --- | --- | --- |
| Transmissions per modulation/SNR key | One | Repeat until 1,000 windows are collected |
| Window selection | Trim to a common length, then use 128-sample windows at stride 64 | Random initial offset of 50--500, then random increments of at least 128 |
| Adjacent-window overlap within a transmission | 64 raw samples | None |
| Maximum sample-rate offset | 100 Hz | 50 Hz |
| Maximum carrier-frequency offset | 1,000 Hz | 500 Hz |
| Channel constructor seed | `0x1337` | `0x1337` |
| Noise amplitude | `10**(-snr/10)` | `10**(-snr/10)` |
| Window normalization | Sum of complex sample magnitudes, through `calc_vec_energy` | Sum of complex sample magnitudes, inline |

The shared normalization is a sum of magnitudes, despite comments calling it
energy. The 04c slicer creates overlapping examples from one transmission per
key. The later sampling design changes that ancestry, which matters when
investigating dependence between training and evaluation examples.

## Source chronology

The filename is not a dated snapshot of an April 2016 release. Follow the
renames and edits when using this code as evidence:

- `342fb0ac151afa06572c1b8d891c7d7d801acb93` (August 26, 2016) adds
  per-window normalization to `timeseries_slicer.py`.
- `7669e0a11e067116384c086deb24d94e539a75fd` (August 29, 2016) introduces
  `generate_dataset4.py`. Its message explicitly motivates collecting windows
  across multiple channel-model instances.
- `e0cac7f12ea2bd1aa9e9adcecafe41140f49f402` (September 12, 2016) renames
  `generate_dataset3.py` to `generate_RML2016.04c.py` and
  `generate_dataset4.py` to `generate_RML2016.10a.py`.

The preserved 04c script writes a dictionary named `RML2014.04c_dict.dat` and
an array named `RML2016.04c.dat`. That inconsistent naming is preserved as
source evidence, not used to infer either artifact's creation date.
