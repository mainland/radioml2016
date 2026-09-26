# Recorded evidence for reconstruction choices

The noise and mapper reports are byte-preserved observations from the
September 2026 investigation. They let a reviewer inspect the measurements
behind the historical environment and mapper choices without first generating
three full datasets. They are not new validation results for subsequent code
changes.

| Reports | Recorded observation | Reproduce and interpret |
| --- | --- | --- |
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
