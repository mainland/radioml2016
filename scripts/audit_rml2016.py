#!/usr/bin/env python
"""Fingerprint a trusted RML2016 pickle against candidate GNU Radio noise pools.

Requires Python 2.7 or Python 3, NumPy and SciPy (available in the historical
Docker image). Pools are CSV files with one real,imag pair per line;
scripts/rml2016_noise_pool.cc generates the historical candidates. See
docs/historical-environment.md for commands and expected control results.
This diagnoses the noise pool; it does not identify an exact release or
reproduce the entire generator. Only load a pickle from a trusted source.
"""

import argparse
import hashlib
import json
import os
import pickle
import sys

import numpy as np
from scipy.spatial import cKDTree


def fingerprint(samples, pool):
    """Fit pool entries and one positive scale per 128-sample observation.

    The generator normalizes each window, so phase identifies candidate pool
    entries independently of scale. A robust magnitude estimate and subsequent
    Cartesian nearest-neighbor fits resolve nearly coincident pool phases.
    """
    observed = samples.transpose(0, 2, 1).astype(np.float64)
    radii = np.linalg.norm(observed, axis=2)
    pool_radii = np.linalg.norm(pool, axis=1)
    if np.any(radii == 0) or np.any(pool_radii == 0):
        raise ValueError("Phase matching requires nonzero samples and pool entries")
    unit = observed / radii[:, :, None]
    distances, indices = cKDTree(pool / pool_radii[:, None]).query(
        unit.reshape(-1, 2)
    )
    indices = indices.reshape(radii.shape)
    scale = np.median(radii / pool_radii[indices], axis=1)
    tree = cKDTree(pool)
    for _ in range(3):
        _, indices = tree.query((observed / scale[:, None, None]).reshape(-1, 2))
        indices = indices.reshape(radii.shape)
        recovered = pool[indices]
        scale = (recovered * observed).sum(axis=(1, 2)) / (recovered**2).sum(
            axis=(1, 2)
        )
    relative_error = np.linalg.norm(
        observed - scale[:, None, None] * recovered, axis=(1, 2)
    ) / np.linalg.norm(observed, axis=(1, 2))
    result = {
        "sample_count": int(distances.size),
        "phase_distance_below_1e-6": int(np.count_nonzero(distances < 1e-6)),
        "phase_distance_max": float(distances.max()),
        "phase_distance_median": float(np.median(distances)),
        "relative_waveform_error_min": float(relative_error.min()),
        "relative_waveform_error_median": float(np.median(relative_error)),
        "relative_waveform_error_max": float(relative_error.max()),
        "windows_below_1e-6_relative_error": int(
            np.count_nonzero(relative_error < 1e-6)
        ),
    }
    return result, indices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pickle", help="Trusted original dataset pickle")
    parser.add_argument("--modulation", default="AM-SSB")
    parser.add_argument("--snr", type=int, default=-20)
    parser.add_argument(
        "--pool", action="append", default=[], metavar="LABEL=CSV",
        help="Candidate pool; repeat to compare positive and negative controls",
    )
    parser.add_argument(
        "--indices",
        help="Save indices for a single, verified matching pool as a NumPy file",
    )
    args = parser.parse_args()
    if args.indices and len(args.pool) != 1:
        parser.error("--indices requires exactly one --pool")
    digest = hashlib.sha256()
    with open(args.pickle, "rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
        source.seek(0)
        dataset = (pickle.load(source) if sys.version_info[0] == 2 else
                   pickle.load(source, encoding="latin1"))
    if not isinstance(dataset, dict) or not dataset:
        raise ValueError("Expected a nonempty dictionary")
    for key, value in dataset.items():
        if not (
            isinstance(key, tuple) and len(key) == 2
            and isinstance(value, np.ndarray) and value.ndim == 3
            and value.shape[0] > 0 and value.shape[1:] == (2, 128)
            and np.isfinite(value).all()
        ):
            raise ValueError("Unexpected key/array structure or nonfinite data")
    norms = [
        np.abs(value[:, 0, :] + 1j * value[:, 1, :]).sum(axis=1)
        for value in dataset.values()
    ]
    report = {
        "path": os.path.realpath(args.pickle),
        "size_bytes": os.path.getsize(args.pickle),
        "sha256": digest.hexdigest(),
        "key_count": len(dataset),
        "modulations": sorted({key[0] for key in dataset}),
        "snrs": sorted({int(key[1]) for key in dataset}),
        "shapes": sorted({tuple(value.shape) for value in dataset.values()}),
        "dtypes": sorted({str(value.dtype) for value in dataset.values()}),
        "sum_abs_min": float(min(value.min() for value in norms)),
        "sum_abs_max": float(max(value.max() for value in norms)),
        "probe_key": [args.modulation, args.snr],
        "pools": {},
    }
    if args.pool and (args.modulation, args.snr) not in dataset:
        parser.error("Requested modulation/SNR key is absent from the dataset")
    for specification in args.pool:
        label, separator, path = specification.partition("=")
        if not separator or not label or not path:
            parser.error("--pool must have the form LABEL=CSV")
        if label in report["pools"]:
            parser.error("Pool labels must be unique")
        pool = np.loadtxt(path, delimiter=",")
        if pool.shape != (8192, 2) or not np.isfinite(pool).all():
            raise ValueError("Expected a finite 8192-row, two-column noise pool")
        result, indices = fingerprint(dataset[args.modulation, args.snr], pool)
        result["path"] = os.path.realpath(path)
        with open(path, "rb") as source:
            result["sha256"] = hashlib.sha256(source.read()).hexdigest()
        report["pools"][label] = result
        if args.indices:
            if result["relative_waveform_error_max"] >= 1e-6:
                raise ValueError("Pool does not match every window; refusing index export")
            with open(args.indices, "wb") as destination:
                np.save(destination, indices, allow_pickle=False)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
