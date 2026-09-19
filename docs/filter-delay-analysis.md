# Analyze transmitter and channel startup delay

The generator does not reliably skip transmitter startup. It draws the first
post-channel window offset uniformly from the inclusive integer range 50--500,
but several transmitter filters retain material response energy beyond sample
500. The channel contributes only a few samples of displacement and does not
remove that transmitter history.

This conclusion depends on what *too early* means. The analysis reports two
separate thresholds:

- The response peak aligns an input item with the strongest output sample.
- The operational response end is the sample index by which all but `1e-7` of
  a first-item response's energy has arrived. This threshold excludes the
  measured float32 phase-accumulator floor. It is not an assertion that an IIR
  has exact finite support.

A window beginning before the response peak precedes the nominal message
alignment. A window beginning before the operational guard can still contain
cold-start behavior caused by missing prehistory. Neither condition makes the
stored samples numerically invalid. Startup may itself be useful information,
but it is not a stationary sample from an established transmission.

## Method

[`analyze_filter_delay.py`](../scripts/analyze_filter_delay.py) changes only the
first input item and subtracts a baseline transmission. For the linear digital
modulators and AM paths, this gives a complex message response. For GFSK,
CPFSK, and WBFM, the tool differentiates complex phase first so that the FM
phase integrator does not turn a finite frequency pulse into a permanent phase
offset. The GFSK response is limited to its source-defined `5*SPS-1` shaping
taps. Later differences are numerical phase-accumulator noise.

The channel analysis injects an isolated complex impulse at input sample ages
64, 256, 512, 2,048, and 8,192. It measures peak displacement, energy-centroid
displacement, a local zero-frequency phase-slope delay, and the operational
response end for the baseline, CFO, SRO, fading, and combined controls. AWGN is
memoryless, so its timing path is the baseline path. Adding noise to an impulse
would obscure the delay measurement.

For the cascade diagnostic, the tool adds the transmitter response end to the
largest measured channel response-end displacement. This is conservative and
reproducible. It is not an exact group-delay law for nonlinear transmitters or
a time-varying channel.

Run the measurement in the pinned reproducible image:

```sh
mkdir -p output/filter-delay
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -v "$PWD/output/filter-delay:/out" -w /work \
  radioml2016:reproducible \
  python2.7 scripts/analyze_filter_delay.py \
    --output /out/filter-delay.json
```

The JSON records the full response measurements, the SPS/EBW boundary sweep,
all channel ages, each modulation/channel combination, and the implemented
settled-window guards. The report produced during this investigation has
SHA-256
`b27fbc7c48e01b6ac79cc6b4038931fae6e5402c788c85cab0134da258af4dae`.
Reproduce it rather than treating the ignored output path as a source artifact.

## Default transmitter and combined-channel results

The table uses default SPS 8 and EBW 0.35. Peak and guard offsets include the
combined channel. The percentages are exact counts under the inclusive uniform
50--500 first-offset rule.

| Modulation | Latest measured response peak | Starts before peak | Operational guard | Starts before guard | Repair guard |
| --- | ---: | ---: | ---: | ---: | ---: |
| BPSK | 350 | 66.52% | 636 | 100% | 710 |
| QPSK | 350 | 66.52% | 636 | 100% | 710 |
| 8PSK | 350 | 66.52% | 636 | 100% | 710 |
| PAM4 | 350 | 66.52% | 636 | 100% | 710 |
| QAM16 | 350 | 66.52% | 636 | 100% | 710 |
| QAM64 | 350 | 66.52% | 636 | 100% | 710 |
| GFSK | 17 | 0% | 37 | 0% | 50 |
| CPFSK | 2 | 0% | 12 | 0% | 50 |
| WBFM | 137 | 19.29% | 318 | 59.42% | 318 |
| AM-DSB | 0 | 0% | 9 | 0% | 50 |
| Repaired AM-SSB | 200 | 33.26% | 403 | 78.27% | 409 |
| WBFM with rate repair | 108 | 12.86% | 260 | 46.56% | 260 |

The AM-SSB delay uses the fixed-oscillator path as a structural proxy. The
historical zero-frequency sine suppresses the message before the same 401-tap
Hilbert filter, so its signal transient is nearly zero and the stored window is
normally dominated by channel noise. The structural delay matters for
`--fixed-am-ssb`.

The six mapper/RRC transmitters all peak at clean-transmitter sample 352. Their
operational response end is sample 631 at the default parameters. The combined
channel advances the peak by two samples but has response energy through delay
+5, producing the 350 peak and 636 guard in the table. For every default linear
modulation, about two thirds of first windows begin before the pulse peak, and
every permitted first offset begins before the operational startup guard.

The conclusion is not universal across modulations. Default GFSK, CPFSK, and
AM-DSB have passed their operational startup guards before the minimum offset
50. WBFM and repaired AM-SSB remain affected for substantial parts of the
historical offset range.

## Channel results

The channel peak displacement is -2 samples for every control and measured
age. Baseline, AWGN, and CFO have an operational response-end displacement of
-2. SRO varies from -2 through 0 over the measured ages. Fading and the combined
channel have response energy through displacement +5.

For the fading and combined controls, the energy-centroid displacement changes
from approximately -1.59 to -1.63 samples over the measured ages. Their local
zero-frequency phase-slope delay changes from approximately -1.23 to -1.37
samples. This variation is expected: the multipath coefficients evolve with
sample age, so the channel has no single constant group delay. These small
channel terms do not explain or compensate the hundreds of samples of RRC,
WBFM, or Hilbert startup history.

## SPS and pulse-shaping dependence

For the six mapper/RRC transmitters, the measured pulse peak is
`5.5*SPS**2` output samples. At SPS 2 the boundary sweep peaks at sample 22 and
has an operational end of 43--44, before the minimum first offset. At SPS 8 the
peak is 352 and the operational end spans 597--694 as EBW changes from 0.5 to
0.1. At SPS 12 the peak is 792 and the operational end spans 1,192--1,521.
Thus a fixed guard cannot support the repository's SPS and EBW ranges.

GFSK has a `5*SPS-1` shaping response. Its operational end remains below offset
50 except at SPS 12 and Gaussian-filter BT 0.1, where it reaches sample 58.
CPFSK's measured response ends at samples 1, 7, and 11 for SPS 2, 8, and 12.

## Consequence for dataset generation

The generator retains the historical sampler because startup behavior follows
from the published source. These measurements use reconstructed transmissions
and do not identify the startup content of individual distributed windows. The
default first-offset draw remains 50--500. `--settled-windows` shifts the same
451-value inclusive uniform draw to `guard..guard+450`. The option consumes the
same number of Python RNG draws as the historical sampler.

The repair uses exact or conservative structural support where the transmitter
has a finite response. A direct probe finds nonzero default RRC response
through sample 704, beyond the operational end at 631. The implemented first
sample after that response is conservatively bounded by `11*SPS**2+1`, then the
five-sample channel term is added. This produces `11*SPS**2+6`, or 710 at SPS
8. EBW changes the tap values and operational energy boundary but not the RRC
tap count, so the structural repair guard does not depend on EBW. GFSK and
CPFSK likewise use SPS-dependent structural bounds. WBFM retains the measured
tail-energy criterion because its preemphasis filter is IIR.

The HDF5 schema records `settling_guard_samples` for every transmission whether
or not the repair is enabled. It also records `settled_windows` in
`generation_options_json`. Downstream analysis can therefore test the repair
invariant or quantify historical windows with offsets below their guard. The
guard is tied to the pinned transmitter implementations and configured dynamic
channel. It must be remeasured before either is changed.
