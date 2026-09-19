# Determine the historical mapper normalization

The October 11, 2016 `gr-mapper` change corrected its constellation
normalization accumulator. The buggy February-through-October implementation,
called *pre-fix* below, emits BPSK points at amplitudes `+2` and `-2`. The
corrected implementation emits `+1` and `-1`. The gain difference depends on
the constellation, so the two implementations also predict different effective
signal-to-noise ratios for QPSK, 8PSK, PAM4, QAM16, and QAM64.

The dataset's final normalization does not make these implementations
equivalent. For a raw window

$$
y[n] = a s[n] + w[n],
\qquad
z[n] = \frac{y[n]}{\sum_k |y[k]|},
$$

the mapper gain $a$ scales the signal but not the additive noise $w[n]$. The
final divisor scales their sum. It removes absolute stored amplitude while
retaining the signal-to-noise structure.

This procedure compares the distributed dataset with no-normalization, buggy,
and fixed candidate datasets, then fits the corresponding source-history
models. It produces evidence for selecting a mapper revision. It does not
recover the original random states or prove that a complete candidate
environment generated the distributed file.

## Experimental design

[`run_mapper_evidence.sh`](../scripts/run_mapper_evidence.sh) builds six
images:

1. The historical environment with the January 10 no-normalization mapper
   revision `463f9e94f5ea45e5be64bae06291423ead3b70f2`.
2. The historical environment with the August 23 pre-fix mapper revision
   `52383e2832a86feb452ddd80928bce69147f01c0`.
3. The historical environment with the October 11 fixed mapper revision
   `15e71bf01be68d427ed9f37966b83efc1180a1d5`.
4. A reproducible generator image derived from the no-normalization image.
5. A reproducible generator image derived from the pre-fix image.
6. A reproducible generator image derived from the post-fix image.

The three reproducible images use the same source tree, source material, Python
and NumPy seeds, advancing channel seeds, STS scheduler, and deterministic
channel runtime. The runner explicitly selects `--channel-seed-policy advance`
to reproduce the recorded comparison. The named Baseline profile instead
uses `restart`. The mapper revision is the intended difference among these
three candidates. Each image generates
1,000 windows for all 20 SNR labels and all eleven modulations. Generating the
complete modulation list preserves the generator loop's seed advancement and
sampler draws. The comparison then selects the six mapper-based modulations.
Before generation, the runner executes the historical runtime check against
all three base images. It checks both BPSK and PAM4 because BPSK cannot
distinguish no normalization from corrected normalization. The expected
`(BPSK peak, PAM4 peak)` pairs are `(1, 3)`, `(2, 12)`, and `(1, 1.5)` for the
no-normalization, buggy, and corrected histories, respectively.

The deterministic runtime gives the candidate datasets identical latent draws
and avoids treating scheduler variation as mapper evidence. Its private noise
selection is not the historical process-global `lrand48` interleaving. The
candidate noise has the reconstructed Gaussian pool, seed routing, and label
amplitude rule, but its joint process differs from the original runtime. The
procedure therefore compares distributions and SNR curves. It cannot replay the
distributed dataset byte for byte.

## Primary method: estimate actual SNR

The channel adds noise after sample-rate offset, carrier offset, and fading.
That noise remains broadband. In contrast, each mapper-based transmitter uses
an RRC pulse with eight samples per symbol and excess bandwidth 0.35. Its
nominal one-sided band edge is

$$
\frac{1 + 0.35}{2 \cdot 8} = 0.084375
$$

cycles per sample. The maximum 500 Hz carrier offset at 200 ksample/s adds only
0.0025 cycles per sample. Frequencies at or beyond 0.15 cycles per sample are
therefore a conservative noise region.

[`estimate_mapper_snr.py`](../scripts/estimate_mapper_snr.py) applies a Hann
taper, takes a 128-point FFT, and estimates each window's noise power from the
median power in that out-of-band region. Dividing by `log(2)` corrects the
median of exponentially distributed complex-Gaussian FFT-bin power. Dividing
by the taper energy converts the result to power per sample. The script then
forms

$$
\widehat{\mathop{\rm SNR}} =
\frac{\text{total power}}{\text{estimated noise power}} - 1.
$$

Both powers contain the same final window-normalization factor, so their ratio
does not require the original unnormalized waveform. Nor does this estimator
require the historical noise RNG state.

The generator uses noise amplitude `10**(-label/10)`. Its noise power therefore
falls 2 dB for every 1 dB increase in the stored label. For each dataset and
modulation, the tool fits a curve with this known slope over estimated SNRs
from -8 through 25 dB. The fitted intercept records the effective signal gain.
The pre-fix/post-fix amplitude ratios and predicted SNR shifts are:

| Modulation | Amplitude ratio | Predicted SNR shift |
| --- | ---: | ---: |
| BPSK | 2 | 6.02 dB |
| QPSK | 4 | 12.04 dB |
| 8PSK | 8 | 18.06 dB |
| PAM4 | 8 | 18.06 dB |
| QAM16 | approximately 11.30 | approximately 21.06 dB |
| QAM64 | approximately 39.35 | approximately 31.90 dB |

The generated candidates serve as a calibration. A modulation supports a
historical mapper conclusion only if the measured candidate-intercept shift is
close to its prediction and each fitted curve contains enough labels in the
usable range. The distributed dataset's intercept is then compared with the
two calibrated candidate intercepts. The report also treats distributed
AM-SSB at label -20 as an effectively noise-only check: estimated noise power
should be close to total power.

The pre/post candidates do not exhaust the source history. Commit
[`943277c`][normalization-introduction] introduced constellation normalization
on February 1, 2016, with the accumulator bug. Its parent did not normalize
constellations. Commit [`463f9e9`][qam64-revision] is the preceding revision
that already contains QAM64. The report therefore fits three relative-power
models: no normalization, the last-point accumulator, and corrected
average-magnitude normalization. Each fit removes one global intercept offset
before computing its RMS residual across modulations. This distinguishes
normalization behavior even if the reconstructed channel has a common
signal/noise scale mismatch.

Individual estimates from 128-sample windows are noisy and can have a negative
signal residual at low SNR. The tool retains those residuals instead of
silently discarding them, aggregates up to 1,000 windows per key, and reports
the usable labels and unconstrained slope as diagnostics. Spectral leakage can
impose a high-SNR ceiling, which is why the fit excludes estimates above 25 dB
and calibration is mandatory.

## Result

The completed full-dataset run calibrates successfully. The measured
pre-fix/post-fix intercept shifts differ from the theoretical shifts by 0.42 dB
or less for all six modulations. Each curve uses eight or nine in-range labels,
and the unconstrained slopes range from 1.89 through 2.11 dB per label dB. The
AM-SSB/-20 noise-only control has median estimated noise/total power 0.989 in
the distributed data and 1.008 in all three candidates.

Each generated control selects its own normalization model:

| Candidate | Selected model | RMS residual after global offset |
| --- | --- | ---: |
| January 10 | No normalization | 0.375 dB |
| August 23 | February last-point bug | 0.348 dB |
| October 11 | Corrected normalization | 0.407 dB |

The distributed dataset gives:

| Normalization model | RMS residual after global offset |
| --- | ---: |
| No normalization | 0.172 dB |
| February 1 last-point bug | 3.943 dB |
| October 11 corrected normalization | 6.354 dB |

The distributed residuals under no normalization are -0.385 through +0.073 dB
across the six modulations. This is strong evidence that the distributed
dataset used a mapper before constellation normalization was introduced,
rather than either later implementation. It also explains why absolute
pre/post distances split 3-3 by modulation: neither later candidate represents
the distributed data's relative constellation powers.

The direct January candidate with advancing channel seeds supplies the
end-to-end check. Its pickle
has SHA-256
`0488f50aa7c7bd9ca6f151fd6cdaed6c18dc5390416585577db3744b6f6cc475`.
The median distributed-minus-candidate SNR-intercept difference is 2.871 dB.
After removing that one common difference, the six per-modulation residuals
range from -0.580 through +0.686 dB and have 0.471 dB RMS error. This is close
to the three candidate self-check errors and supports making the January
revision the historical-image default.

The advancing-seed comparison alone does not explain its 2.871 dB
difference from the distributed dataset. The runtime checks show
the predicted `(BPSK peak, PAM4 peak)` triples and the same reconstructed noise
pool and selected noise sequence in all three images. Their pool and sequence
mean powers are 0.982834 and 0.979644, respectively. The signal-only
transmitter checks likewise follow the mapper's predicted relative gains.
Those facts validate the reconstructed candidates, but they cannot recover the
original pre-normalization noise amplitude. A normalized noise-only window
contains no absolute-scale information. Those controls alone cannot assign
the common difference uniquely to signal gain, noise scaling, or another
historical channel detail. The seed-policy control below tests one such
channel difference directly.

The [retained report](../evidence/mapper/snr-comparison.json) has SHA-256
`c425f94d7ffde085a415f0522109cb204681c911014392a5a47a1cac3527c9a5`.
Its [evidence index](../evidence/README.md) records the input identities,
candidate images, and preservation limits. Rerun the procedure below into
`output/mapper-evidence/` to compare a fresh result with that observation.

## Channel-seed control

The published generator supplies `0x1337` to every channel constructor. The
mapper candidates above instead advanced that base by four for every
transmission. Repeating the January candidate with
`--channel-seed-policy restart` changes the full pickle SHA-256 to
`af5d4a17ac2d1699e5e0c67198bacbdcc20caaa8988519bb33c6af5d208d8ec6`.
All other generator settings and the pinned runtime are unchanged.

The [seed-policy report](../evidence/mapper/channel-seed-policy.json) applies
the same estimator and fitting rules to that candidate. It compares the fresh
candidate curves with the original-data curves retained in the earlier
mapper report. The original dataset was not refitted for this control.

| Channel seed policy | Common original-minus-candidate offset | RMS residual after offset |
| --- | ---: | ---: |
| Advance | 2.871 dB | 0.471 dB |
| Restart | 0.080 dB | 0.039 dB |

Changing this policy accounts for most of the earlier discrepancy in the
candidate comparison. It changes the fading realization as well as drift and
noise, so this control does not isolate fading gain from the other channel
components. It also does not recover the original shared RNG interleaving.
The remaining 0.080 dB is not an independently measured noise-scale error.

To refit the comparison against the original arrays, generate a restarting
candidate and reuse the primary estimator command below:

```sh
./build_dataset --channel-seed-policy restart \
  --output output/mapper-evidence/restart.dat
```

In that estimator command, set `--no-normalization /data/restart.dat` and
write a new report, for example `--output /data/restart-snr-comparison.json`.
Keep the pre-fix and post-fix inputs unchanged. Compare its
`direct_no_normalization_comparison` with the retained seed-policy report's
`restart_comparison`. The report records both candidate hashes, the retained
input-report hash, estimator hash, image ID, configuration, and fitted curves.

## Run the comparison

Use only a trusted pickle. Python pickle loading can execute instructions from
the input. The runner requires the investigated distributed dataset SHA-256:

```text
b29ccc25b00d0718cd3b70ffa9158662ec83f6d9b63ffd845c7bcbe3b3096e8c
```

From a recursive checkout with Docker available, run:

```sh
./scripts/run_mapper_evidence.sh \
  /path/to/RML2016.10a_dict.pkl \
  output/mapper-evidence
```

The command builds the candidate images, generates approximately 220,000
windows from each mapper, verifies the original input hash, and writes:

| Path | Contents |
| --- | --- |
| `no-normalization.dat` | Candidate pickle generated with the January 10 mapper |
| `pre-fix.dat` | Candidate pickle generated with the August 23 mapper |
| `post-fix.dat` | Candidate pickle generated with the October 11 mapper |
| `none-generation.log` | No-normalization generator output |
| `pre-generation.log` | Pre-fix generator output |
| `post-generation.log` | Post-fix generator output |
| `none-runtime.json`, `none-runtime.log` | No-normalization runtime check |
| `pre-runtime.json`, `pre-runtime.log` | Pre-fix runtime check |
| `post-runtime.json`, `post-runtime.log` | Post-fix runtime check |
| `images.json` | Docker image identities and configuration |
| `snr-comparison.json` | Primary SNR curves, calibration, and mapper distances |

The runner refuses to overwrite these principal artifacts. Select a new output
directory for another run. Set `RML_MAPPER_IMAGE_PREFIX` to change the six
Docker image tags.

To run the primary estimator against existing candidate pickles, invoke it
inside any reproducible image:

```sh
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" \
  -v "/path/to/original-directory:/input:ro" \
  -v "$PWD/output/mapper-evidence:/data" -w /work \
  radioml2016:mapper-evidence-post-reproducible \
  python2.7 scripts/estimate_mapper_snr.py \
    /input/RML2016.10a_dict.pkl /data/pre-fix.dat /data/post-fix.dat \
    --no-normalization /data/no-normalization.dat \
    --expected-original-sha256 \
      b29ccc25b00d0718cd3b70ffa9158662ec83f6d9b63ffd845c7bcbe3b3096e8c \
    --output /data/snr-comparison.json
```

The estimator does not impose the known original-file hash unless
`--expected-original-sha256` is supplied.

## Interpret the report

Inspect these quantities in `snr-comparison.json` before selecting a mapper:

1. For each modulation, compare `candidate_intercept_shift_db` with
   `expected_candidate_shift_db`. A large `candidate_shift_error_db` means the
   spectral estimator did not calibrate for that modulation.
2. Inspect each curve's `point_count`, `snr_labels_db`, and unconstrained
   `fitted_slope_db_per_label_db`. Sparse curves or a slope far from 2 weaken
   the intercept comparison.
3. Inspect `noise_control_am_ssb_minus_20`. Its median noise-to-total ratio
   should be near one. This checks the noise floor rather than mapper behavior.
4. Inspect `normalization_model_fits`. All three generated candidates should
   select their own models. For the distributed dataset, compare the three RMS
   residuals after the fitted global offset. This relative-power comparison is
   more informative than counting which of the two later candidates is closer.
5. Inspect `direct_no_normalization_comparison`. Its common offset is an
   absolute-scale diagnostic. Its RMS residual after removing that offset tests
   whether the direct candidate reproduces the modulation-dependent pattern.
   Do not interpret the common offset as a noise-amplitude measurement.

Windows can share a transmission, and the distributed pickle does not identify
that membership. The report supplies no p-value or independence claim. Preserve
the complete report and candidate artifacts rather than recording only an
aggregate preference.

[normalization-introduction]: https://github.com/gr-vt/gr-mapper/commit/943277ccd08951c1937e24624cbd10fce9bc32c3
[qam64-revision]: https://github.com/gr-vt/gr-mapper/commit/463f9e94f5ea45e5be64bae06291423ead3b70f2
