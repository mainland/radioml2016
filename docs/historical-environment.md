# Likely environment for RadioML 2016.10a

**The best supported reconstruction is an Ubuntu 16.04 / Python 2.7 stack
with GNU Radio's 2015--2018 Boost-based Gaussian generator and shared
`lrand48` noise-pool selection.** GNU Radio 3.7.10.1 is a working, dated
representative of that implementation. The evidence does not identify the
exact original release, package revisions, CPU, or initial random states.

The [Dockerfile](../Dockerfile) builds the candidate below. It preserves the
historical signal-processing code, including its nondeterministic shared
channel RNG. Deterministic generation requires a separate runtime change.
Software-version selection alone cannot make the original generator repeat.

Research was consolidated and primary source revisions checked on September
15, 2026. This document separates source history, reproduced measurements, and
reconstruction choices. No recovered environment manifest establishes the
complete original stack.

## Selected versions and confidence

| Component | Docker candidate | Evidence and uncertainty |
| --- | --- | --- |
| OS / architecture | Ubuntu 16.04, Linux amd64 | Upstream's contemporary Docker recipe uses Xenial. Original architecture and exact OS image are unrecorded. |
| GNU Radio | 3.7.10.1 | Released in August 2016; its Gaussian pool and `lrand48` selection match original-data measurements. These behaviors occur in other revisions too. |
| VOLK | 1.3.0 development source, `4465f9b26354e555e583a7d654710cb63cf914ce` | Exact submodule recorded by the selected GNU Radio commit; original VOLK revision and selected SIMD kernels remain unknown. |
| Python | 2.7.12 | Released generator uses Python 2 syntax/APIs; 2.7.12 appears in the inspected October 2016 RadioML image package database. This does not identify the generating interpreter. |
| NumPy / SciPy | 1.11.0 / 0.17.0 | Same contemporary image database and Xenial package family; original patch levels unestablished. |
| Matplotlib | 1.5.1 | Xenial package, needed by the existing imports. No original-data measurement identifies this version. |
| gr-mapper | January 10, 2016 no-normalization revision | Evidence-supported default. A direct candidate matches the distributed dataset's relative SNR across six mapper modulations with 0.471 dB RMS error after one common offset. The absolute SNR remains 2.871 dB lower in the candidate. |
| gr-mediatools | October 10, 2016 revision | Contemporary Python 2 build fix; retains the decoder code. No original audio decode has been recovered for comparison. |
| FFmpeg libraries | 2.8.6 | Initial Xenial package version; builds the old mediatools source without an API compatibility patch. Original decoder version remains unknown. |
| Boost / FFTW | 1.58 / 3.3.4 | Xenial build dependencies. The measured pool agrees with the candidate Boost implementation, without uniquely identifying its version. |
| Compiler | GCC / G++ 5.4 | Xenial compiler family; a reconstruction choice, with no recovered original compiler identity. |

The image digest and source commits are explicit:

```text
ubuntu:16.04  sha256:a3785f78ab8547ae2710c89e627783cfa7ee7824d3468cae6835c9f4eae23ff7
GNU Radio    59daaff0d9d04373d3a6b14ea7b46e080bad7a1e
VOLK         4465f9b26354e555e583a7d654710cb63cf914ce
gr-mapper    463f9e94f5ea45e5be64bae06291423ead3b70f2
gr-mediatools d11c38bbadb2a56494502f2acc54659749bb81db
source_material 07615fff2fe281e9c62a86cd048a3b6cc8bb98db
```

**The base image and some Ubuntu security package revisions postdate 2016.**
For example, the selected interpreter package is
`python2.7=2.7.12-1ubuntu0~16.04.18`; the compiler is
`gcc-5=5.4.0-6ubuntu1~16.04.12`. This is a reconstruction of the likely
software family, with a tested build, rather than a recovered 2016 machine.
The built image records all installed package versions in
`/opt/replay-provenance/dpkg.tsv`.

## What the historical sources establish

### Release chronology and contemporary containers

The public generator named `generate_RML2016.10a.py` was committed on September
12, 2016. GNU Radio's signed `v3.7.10.1` tag is dated August 15, 2016 and
points to the commit used above. These dates establish availability. The
dataset name is insufficient to infer a particular day of generation. Sources:
[generator history][generator-history], [GNU Radio tag][gr-tag].

Upstream's `dockerRML` recipe selects Ubuntu 16.04 and installs NumPy,
SciPy, and Matplotlib from apt. It fetches moving PyBOMBS, recipes, and source
branches. The inspected December 12, 2016 change adds gr-mediatools to its
install command. Rebuilding that recipe now cannot establish its 2016
dependencies. Sources: [minimal-SDR recipe][docker-recipe],
[mediatools addition][docker-mediatools].

The version investigation also inspected Docker registry configurations and
selected archived layers:

| Registry image digest | Recorded creation time (UTC) | Observation |
| --- | --- | --- |
| `radioml/sdr@sha256:7db85803fd98eda7514fb05ab347ac602a9581971da28092da6131612ec11ee0` | October 12, 2016 | Its attempted GNU Radio installation layer contains an HTML response saved as an ALSA source archive, with no GNU Radio installation. Its package database supplies the Python/NumPy/SciPy candidate versions. |
| `yonidavidson/minsdr@sha256:20412ea49ccfd23ea6ee900972cd710c6a32d8c07f6af11e4511fa97c01cb8be` | December 10, 2016 | Inspected libraries report GNU Radio `3.7.11git` and VOLK `1.3.0`. This is a contemporary alternative, with no demonstrated connection to generation of the released arrays. |

The second image is suggested in [upstream issue 30][issue30]. Registry
metadata: [RadioML SDR][sdr-tags], [Yoni minimal SDR][yoni-tags]. These
observations come from local inspection of the specified registry images;
they do not establish that either container generated the dataset.

The dataset archive inspected during the investigation recorded a June 26, 2018
modification time for its pickle member. That is consistent with later
packaging, but it does not establish when its arrays were generated. The pickle
contains waveform arrays without seed or environment metadata. The investigated
pickle's SHA-256 is
`b29ccc25b00d0718cd3b70ffa9158662ec83f6d9b63ffd845c7bcbe3b3096e8c`.

### The strongest version constraint comes from the noise

GNU Radio replaced its older Numerical Recipes RNG with Boost MT19937 in
[September 2015][boost-change]. In the selected revision,
[`gr::random`][gr-random] constructs the Gaussian values and
[`fastnoise_source`][fastnoise-implementation] fills a pool using its supplied
seed. [`sample()`][fastnoise-header] selects pool entries with process-global
`lrand48()` on this Linux build.

Local analysis of the original AM-SSB/-20 dB samples found the following
phase matches to candidate Gaussian pools:

| Candidate pool | Matching sample phases within `1e-6`, out of 128,000 |
| --- | ---: |
| Historical Boost MT, seed `0x1337` (4919) | 128,000 |
| Boost MT default seed 5489 | 302 |
| Earlier Numerical Recipes generator, supplied seed 4919 | 430 |

Moreover, 220 of 1,000 windows follow all 128 consecutive historical
`lrand48` selections. The combined evidence supports the pool construction
and selection algorithm. It does not recover the full global RNG state,
the interleaving of channel consumers, or an exact GNU Radio release.
These are local experimental results, not measurements published by the
dataset authors. The [noise evidence procedure](noise-evidence.md) reproduces
the comparisons and recurrence count from a supplied pickle.

A [March 2018 change][xoroshiro-change] replaced global pool selection with
per-instance xoroshiro128+ and removed the pool RNG's explicit seed
initializer. That implementation changes both the stochastic process and
seed routing. Building a moving `maint-3.7` branch therefore misses an
empirically important part of the original behavior. GNU Radio 3.7.10.1
provides the matching earlier behavior.

### Mapper and audio choices remain less certain

The [October 11 mapper fix][mapper-fix] changes accumulation in the
constellation normalization calculation. For BPSK it changes amplitudes from
`+2/-2` to `+1/-1`. The public generator predates the fix, but the dataset's
generation date is unknown. The date alone does not select a mapper. The
[mapper-version investigation](mapper-version-evidence.md) builds all three
revisions and generates matched candidate datasets. Its primary test estimates
actual SNR from out-of-band power, calibrates the estimate against the known
pre/post gain change, and compares the resulting SNR curves with the
distributed arrays. The calibrated candidates reproduce their theoretical gain
shifts within 0.42 dB. After one common offset is fitted, the distributed
modulation powers match the earlier no-normalization behavior with 0.172 dB RMS
residual, versus 3.943 dB for the February accumulator bug and 6.354 dB for the
October fix. A full candidate built from the [January 10 no-normalization
revision][mapper-no-normalization] selects its own model with 0.375 dB RMS
residual. After removing one 2.871 dB common difference, its SNR intercepts
match the distributed dataset with 0.471 dB RMS error. The source runtime also
gives the predicted BPSK/PAM4 mapper peaks and identical reconstructed
complex-noise power across all three candidates.

These results support using the January revision as the default, but they do
not establish the cause of the 2.871 dB absolute-SNR difference. Final window
normalization prevents a noise-only window from identifying the original
unnormalized noise amplitude, so the remaining difference cannot presently be
assigned uniquely to signal gain, noise scaling, or another channel detail.
The mapper runtime check alone does not establish this result. Revision
`463f9e94f5ea45e5be64bae06291423ead3b70f2`, the buggy revision
`52383e2832a86feb452ddd80928bce69147f01c0`, and the corrected revision remain
selectable through `--build-arg MAPPER_REV=...`.

The [October 10 mediatools revision][mediatools-fix] explicitly requests Python
2 libraries. FFmpeg 2.8.6 retains the API it uses, so the Dockerfile builds
that source without compatibility substitutions. This choice establishes
compatibility, not original decoder identity. Runtime checks decoded finite,
nonempty audio. The MP3's cover-image packet produces a warning before audio
succeeds. Repeated candidate audio decodes produced identical bursts. Matching
original audio remains untested.

UHD is omitted because the simulated generation path instantiates no radio
hardware blocks. Matplotlib uses its headless Agg backend. The source-material
submodule remains at the recorded original commit rather than downloading
new text or audio.

## Build, inspect, and validate

From a recursive checkout:

```sh
docker build --platform linux/amd64 -t radioml2016:historical .
mkdir -p output/evidence
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD/output/evidence:/out" \
  -v "$PWD:/work:ro" -w /work radioml2016:historical \
  python2.7 scripts/check_historical_runtime.py --output /out/runtime.json
docker image inspect radioml2016:historical
```

The [runtime script](../scripts/check_historical_runtime.py) checks the selected
versions, BPSK and PAM4 mapper amplitudes, sine-at-zero behavior, media decoding,
all eleven modulators, and historical noise samples against an independent
pool/LCG implementation. Its JSON report separates build compatibility from
original provenance. The defaults, `--mapper-amplitude 1 --pam4-amplitude 3`,
describe the no-normalization image. Use amplitudes 2 and 12 for the February
bug, or 1 and 1.5 for the October fix. BPSK alone cannot distinguish the first
and third histories. This checks an explicitly chosen candidate, rather than
inferring an original revision from its version string.

This historical-image check is a standalone Python 2.7 program. The image
intentionally preserves GNU Radio's shared RNG and omits the deterministic
runtime patch and test-only dependencies. It validates the environment
reconstruction; it does not provide repeatable dataset generation.

`BUILD_JOBS` controls compilation parallelism (default 4). `USERNAME`,
`USER_UID`, and `USER_GID` support working with mounted files. Source revision
arguments allow explicit candidate comparisons. Changing GNU Radio also
requires setting `VOLK_REV` to that commit's actual gitlink.

The Dockerfile pins its base digest, direct apt dependencies, and full source
commits. It verifies the GNU Radio/VOLK relationship during the build.
Transitive apt dependencies are recorded rather than individually pinned. It
retains source trees under `/opt/replay-src` and records package versions,
compiler/libc details, source SHAs, and CMake settings under
`/opt/replay-provenance`. Preserve the built image and that directory for
repeatable future use. Rebuilding against the live Ubuntu archive is not a
complete byte-for-byte image lock.

The [retained runtime reports and image identities](../evidence/README.md)
record the three mapper candidates used in the version investigation. Those
checks establish build compatibility, the expected mapper amplitudes, and the
reconstructed noise implementation. They do not identify the environment that
generated the distributed dataset. Run the command above to record the image
you build, rather than reusing an earlier image identity.

## Why explicit seeds also require a runtime change

The released generator leaves Python's sampler and NumPy's digital-mask RNG
unseeded. Its channel constructor supplies `0x1337` to seeded noise pools and
fading components, but AWGN, carrier drift, and clock drift consume the
separate shared `lrand48` stream concurrently. Their assignment of draws can
therefore depend on thread scheduling.

Local fixed-state controls repeated source bits, the BPSK transmitter, and
individual channel components, while the combined historical channel failed
to repeat. A reproducible new dataset needs explicit seeds,
deterministic allocation of channel random draws, stable evaluation order,
and a fixed numerical environment. That reproducible extension cannot be
claimed to regenerate the released dataset, whose original states and
schedule remain unknown.

[generator-history]: https://github.com/radioML/dataset/commit/7ef3be6d4386b6f4f3ccd5147369e8bd6fc56784
[gr-tag]: https://api.github.com/repos/gnuradio/gnuradio/git/tags/7c17d1cd1daa08fc3b6613f11f553f41ae7b3bd9
[docker-recipe]: https://github.com/radioML/dockerRML/blob/b421450fefe0bb31ee970561427c49dc73000afe/minimal-SDR/Dockerfile
[docker-mediatools]: https://github.com/radioML/dockerRML/commit/b421450fefe0bb31ee970561427c49dc73000afe
[issue30]: https://github.com/radioML/dataset/issues/30#issuecomment-633240711
[sdr-tags]: https://hub.docker.com/v2/repositories/radioml/sdr/tags?page_size=100
[yoni-tags]: https://hub.docker.com/v2/repositories/yonidavidson/minsdr/tags?page_size=100
[boost-change]: https://github.com/gnuradio/gnuradio/commit/e172d55e2bfe63e5b99e7d432f9386c37bff8c84
[gr-random]: https://github.com/gnuradio/gnuradio/blob/59daaff0d9d04373d3a6b14ea7b46e080bad7a1e/gnuradio-runtime/lib/math/random.cc
[fastnoise-implementation]: https://github.com/gnuradio/gnuradio/blob/59daaff0d9d04373d3a6b14ea7b46e080bad7a1e/gr-analog/lib/fastnoise_source_X_impl.cc.t
[fastnoise-header]: https://github.com/gnuradio/gnuradio/blob/59daaff0d9d04373d3a6b14ea7b46e080bad7a1e/gr-analog/lib/fastnoise_source_X_impl.h.t
[xoroshiro-change]: https://github.com/gnuradio/gnuradio/commit/c31f52882a7eefda683cec42e65a95fd2127f780
[mapper-fix]: https://github.com/gr-vt/gr-mapper/commit/15e71bf01be68d427ed9f37966b83efc1180a1d5
[mapper-no-normalization]: https://github.com/gr-vt/gr-mapper/commit/463f9e94f5ea45e5be64bae06291423ead3b70f2
[mediatools-fix]: https://github.com/osh/gr-mediatools/commit/d11c38bbadb2a56494502f2acc54659749bb81db
