# RadioML 2016 dataset generation

This repository reconstructs a candidate software environment for the RadioML
2016.10a generators and records the evidence supporting each selected version.
The environment is compatible with the public generator, but the distributed
dataset's exact software revisions, CPU, and random states remain unknown.

## Historical environment and evidence

The [historical environment guide](docs/historical-environment.md) records the
candidate versions, supporting evidence, and remaining uncertainty. Programs
in [scripts/](scripts/) reproduce the noise analysis against a separately
supplied copy of the distributed dataset and check the selected runtime.

Clone recursively to obtain the original text and audio sources, then build:

```sh
git clone --recursive https://github.com/mainland/radioml2016
cd radioml2016
docker build --platform linux/amd64 -t radioml2016:historical .
```

Check the historical stack:

```sh
mkdir -p output/evidence
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/work:ro" -v "$PWD/output/evidence:/out" -w /work \
  radioml2016:historical \
  python2.7 scripts/check_historical_runtime.py --output /out/runtime.json
```

The [noise evidence commands](docs/noise-evidence.md)
compare a supplied original dataset pickle against competing Gaussian pools
and test recovered indices against the historical random-number recurrence.
Generated evidence stays in `output/`. The historical image preserves the
shared channel RNG, so fixed software versions alone do not make it repeat.

## References

The [DeepSig release page](https://www.deepsig.ai/datasets/) identifies
RadioML 2016.10A as the release that supersedes 2016.04C and links its
[generator source](https://github.com/radioML/dataset). It associates the
paper below with 2016.04C. The paper provides background on modulation
recognition. The 2016.10A release description and generator history identify
the dataset studied here.

T. J. O'Shea, J. Corgan, and T. C. Clancy, "Convolutional Radio Modulation
Recognition Networks," EANN 2016, pp. 213--226. [DOI:
10.1007/978-3-319-44188-7_16](https://doi.org/10.1007/978-3-319-44188-7_16).
