# Recorded evidence for reconstruction choices

The noise and mapper reports are byte-preserved observations from the
September 2026 investigation. They let a reviewer inspect the measurements
behind the historical environment and mapper choices without first generating
three full datasets. They are not new validation results for subsequent code
changes. The separate baseline control identifies which mapper produces the
golden fixture used by the reproducibility test. The manual validation record
separately summarizes a fresh local build and validation of the maintained
generator.

| Reports | Recorded observation | Reproduce and interpret |
| --- | --- | --- |
| [Manual validation](manual-validation.json) | Uncached local builds pass all four dataset hashes, the reproducibility matrix, and the retained dataset quality audit. | [Manual procedure](../docs/reproducible-generation.md#manual-validation) |
| [Dataset quality](dataset-quality.json) | Baseline has 618 excess exact duplicate windows within modulation/SNR keys. All three named profiles reuse one channel base seed. | [Artifact audit and split limits](../docs/datasets.md#dependence-and-evaluation-splits) |
| [Baseline mapper control](baseline.json) | January and October mappers produce distinct fixture hashes. Removing unused imports leaves the January output unchanged. | [Baseline generation](../docs/reproducible-generation.md#build-and-run) |
| [Noise pools](noise/pool-comparison.json) | The Boost MT pool seeded with 4919 fits all 1,000 AM-SSB/-20 windows. Alternative pools fail the same criterion. | [Noise procedure](../docs/noise-evidence.md) |
| [AM-SSB/+18 control](noise/pool-comparison-amssb-18.json) | Tests the noise model where residual message leakage is more visible. | [Noise procedure](../docs/noise-evidence.md#am-ssb-at-18-db) |
| [Selector recurrence](noise/lrand48.json) | 220 of 1,000 windows follow 128 consecutive historical `lrand48` selections. | [Recurrence test](../docs/noise-evidence.md#5-test-the-order-of-the-indices) |
| [Mapper comparison](mapper/snr-comparison.json) | Three mapper candidates select their own models. The distributed data favors no normalization. This advancing-seed comparison leaves a common SNR offset. | [Mapper procedure](../docs/mapper-version-evidence.md) |
| [January](mapper/none-runtime.json), [August](mapper/pre-runtime.json), [October](mapper/post-runtime.json) runtime controls | Mapper amplitudes and reconstructed noise checks for each candidate. | [Runtime checks](../docs/historical-environment.md#build-inspect-and-validate) |
| [Channel seed policy](mapper/channel-seed-policy.json) | Restarting the candidate seed reduces the common SNR difference from 2.871 to 0.080 dB against retained original-data curves. | [Seed-policy control](../docs/mapper-version-evidence.md#channel-seed-control) |
| [Candidate images](mapper/images.json) | Identities and build configuration of the six mapper images. | [Candidate design](../docs/mapper-version-evidence.md#experimental-design) |

Verify the preserved report bytes from this directory:

```sh
sha256sum -c SHA256SUMS
```

The dataset-quality report is the unchanged September 26, 2026 artifact audit.
It identifies the three reference HDF5 files by SHA-256 and records the reviewed
source snapshot and image. It counts excess bit-identical windows within each
modulation/SNR key, records one duplicate group's ancestry, and summarizes
stored paired SNR measurements. It does not measure near-duplicates or
statistical independence, and it does not analyze the original dataset.
The maintained audit command reproduces its `artifacts` entries.

The original input is supplied separately. The investigated pickle has SHA-256
`b29ccc25b00d0718cd3b70ffa9158662ec83f6d9b63ffd845c7bcbe3b3096e8c`.
The mapper report records this hash and all three candidate dataset hashes.
The pool reports record their input and pool hashes. The recurrence report
has no independent input digest and must be interpreted with the preceding
pool-match and index-export steps.

The mapper report's estimator SHA-256 identifies the script used for that
measurement. It differs from the maintained script's hash. Embedded paths
identify the original container mounts, not files a clone must contain. A fresh
report records the script and paths used for the new run. Compare numerical
results and input identities rather than requiring identical report bytes after
path or provenance changes.

The repository retains these small reports and the commands to regenerate the
evidence. The original dataset, candidate datasets, generation logs, and built
images must be supplied or regenerated separately. No report recovers the full
original runtime or the dataset's unknown seeds.

The baseline control records mapper revisions, image identities, generator
hashes, seeds, and output hashes. Holding the generator and environment fixed,
it reproduces the former golden hash by changing only the January mapper to
the October revision. It also records identical January output before and
after removal of unused generator imports. These observations establish the
fixture's mapper dependence, without identifying the original dataset's full
environment.

To compare the fixture hashes, use the January and October builds described
in the mapper procedure and generate with `--frames-per-key 80 --snrs -20 18
--channel-seed-policy advance`, leaving other options at defaults. Both this
control and the full mapper comparison used advancing seeds. Their recorded
hashes and SNR offset do not describe the restarting Baseline profile. The
separate seed-policy report records the restarting control. The earlier
report's source and image identities refer to the measured snapshots. The pre-cleanup source snapshot and measured
image layers are not included in a clone.
