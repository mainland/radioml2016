#!/usr/bin/env python
"""Test recovered 8192-entry noise-pool indices against historical lrand48.

Usage: python scripts/probe_lrand48.py indices.npy > lrand48-report.json
Requires Python 2.7 or Python 3 and NumPy. The indices are produced by
scripts/audit_rml2016.py --indices; see docs/historical-environment.md.

GNU Radio v3.7.10.1 fastnoise_source_X_impl.cc.t used lrand48() % 8192
for the dynamic channel's AWGN source on GNU systems. glibc's recurrence is
documented in its release/2.23/master/stdlib/drand48-iter.c source:
https://github.com/bminor/glibc/blob/release/2.23/master/stdlib/drand48-iter.c

Only bits 17 through 29 of the updated state reach that index. Consequently
this probe recovers at most the low 30 state bits, conditional on consecutive
draws; it cannot recover the full 48-bit state or an original srand48 seed.
Other blocks consumed the same process-global RNG. A sequence mismatch may
reflect interleaved draws, races, or incorrectly inferred pool indices.
"""

import argparse
import json

import numpy as np


MULTIPLIER = 0x5DEECE66D
INCREMENT = 11
MASK = (1 << 30) - 1


def zero_start_position(state):
    """Return this low-30 state's draw position modulo 2**30 from state 0."""
    current = 0
    position = 0
    multiplier = MULTIPLIER & MASK
    increment = INCREMENT
    for bit in range(30):
        if ((current ^ state) >> bit) & 1:
            current = (multiplier * current + increment) & MASK
            position |= 1 << bit
        increment = (increment * (multiplier + 1)) & MASK
        multiplier = (multiplier * multiplier) & MASK
    assert current == state
    return position


def recover_prefix(row):
    """Return longest compatible prefix and any unique starting state."""
    states = (np.uint64(int(row[0]) << 17) |
              np.arange(1 << 17, dtype=np.uint64))
    initial_states = states.copy()
    recovered = None
    prefix_length = 1
    for index in row[1:]:
        states = ((states * np.uint64(MULTIPLIER) + np.uint64(INCREMENT)) &
                  np.uint64(MASK))
        matches = (states >> np.uint64(17)) == index
        states = states[matches]
        initial_states = initial_states[matches]
        if not len(states):
            break
        prefix_length += 1
        if len(initial_states) == 1:
            recovered = int(initial_states[0])
    return prefix_length, recovered


def inspect(indices, example_count=20):
    indices = np.asarray(indices)
    if (indices.ndim != 2 or not indices.shape[0] or indices.shape[1] < 3 or
            not np.issubdtype(indices.dtype, np.integer) or
            np.any(indices < 0) or np.any(indices >= 8192)):
        raise ValueError("Expected a nonempty integer [frames, samples>=3] array "
                         "with indices between 0 and 8191")
    results = [recover_prefix(row) for row in indices]
    lengths = np.array([result[0] for result in results])
    values, counts = np.unique(lengths, return_counts=True)
    examples = []
    for frame, (length, state) in enumerate(results[:example_count]):
        examples.append({
            "frame": frame,
            "consecutive_prefix_samples": length,
            "conditional_initial_low30_state": state,
            "conditional_zero_start_position_mod_2_30":
                zero_start_position(state) if state is not None else None,
        })
    return {
        "frames": int(indices.shape[0]),
        "samples_per_frame": int(indices.shape[1]),
        "fully_consecutive_frames": int(np.sum(lengths == indices.shape[1])),
        "prefix_length_histogram": {
            str(int(length)): int(count) for length, count in zip(values, counts)
        },
        "frames_with_unique_prefix_start_state":
            sum(state is not None for _, state in results),
        "recurrence": "x = (0x5deece66d*x + 11) mod 2^30; index = x >> 17",
        "interpretation": (
            "States assume uninterrupted draws over the reported prefix. "
            "Only low 30 bits are identifiable from 8192-entry pool indices. "
            "The zero-start position is a phase modulo 2^30, not a total "
            "draw count or proof that the original RNG started at zero. "
            "Mismatches alone do not establish scheduler interleaving."
        ),
        "examples": examples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("indices", help=".npy array of recovered pool indices")
    parser.add_argument("--examples", type=int, default=20,
                        help="number of frame details to include (default: 20)")
    args = parser.parse_args()
    if args.examples < 0:
        parser.error("--examples must be nonnegative")
    try:
        report = inspect(np.load(args.indices, allow_pickle=False), args.examples)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
