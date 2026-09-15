/* SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Copyright 2002, 2015 Free Software Foundation, Inc.
 *
 * The random-number algorithms below are adapted from GNU Radio:
 * https://github.com/gnuradio/gnuradio/blob/v3.7.10.1/gnuradio-runtime/lib/math/random.cc
 * https://github.com/gnuradio/gnuradio/blob/v3.7.8/gnuradio-runtime/lib/math/random.cc
 * The pool construction follows:
 * https://github.com/gnuradio/gnuradio/blob/v3.7.10.1/gr-analog/lib/fastnoise_source_X_impl.cc.t
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 *
 * The GNU Radio source also retains this notice:
 * Copyright 1997 Massachusetts Institute of Technology
 *
 * Permission to use, copy, modify, distribute, and sell this software and its
 * documentation for any purpose is hereby granted without fee, provided that
 * the above copyright notice appear in all copies and that both that
 * copyright notice and this permission notice appear in supporting
 * documentation, and that the name of M.I.T. not be used in advertising or
 * publicity pertaining to distribution of the software without specific,
 * written prior permission. M.I.T. makes no representations about the
 * suitability of this software for any purpose. It is provided "as is"
 * without express or implied warranty.
 */

// Diagnostic pool generator; does not simulate the channel or recover a seed.
// Build: c++ -O2 -std=c++11 scripts/rml2016_noise_pool.cc -o /tmp/rml2016_noise_pool
// Run:   /tmp/rml2016_noise_pool mt 4919 > /tmp/pool.csv
// Other candidates: mt 5489, nr 4919. Each produces 8192 real,imaginary rows.
// Boost development headers are required; no GNU Radio installation is needed.
// See docs/historical-environment.md for the comparison and its limitations.

#include <boost/random.hpp>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>

class MersenneTwisterGaussian {
    boost::mt19937 engine;
    boost::uniform_real<float> distribution;
    boost::variate_generator<boost::mt19937&, boost::uniform_real<float> > uniform;
    bool stored;
    float saved;

public:
    explicit MersenneTwisterGaussian(unsigned int seed)
        : engine(seed), uniform(engine, distribution), stored(false), saved(0) {}

    float gaussian()
    {
        if (stored) {
            stored = false;
            return saved;
        }
        float x, y, radius_squared;
        do {
            x = 2.0 * uniform() - 1.0;
            y = 2.0 * uniform() - 1.0;
            radius_squared = x * x + y * y;
        } while (radius_squared >= 1.0f || radius_squared == 0.0f);
        stored = true;
        // Preserve the pre-2018 mixed float/double expressions. Replacing
        // log/sqrt with logf/sqrtf changes rounding in the historical pool.
        saved = x * std::sqrt(-2.0 * std::log(static_cast<double>(radius_squared)) /
                              radius_squared);
        return y * std::sqrt(-2.0 * std::log(static_cast<double>(radius_squared)) /
                             radius_squared);
    }
};

class NumericalRecipesGaussian {
    long seed;
    long shuffled;
    long table[32];
    bool stored;
    float saved;

    float uniform()
    {
        const long modulus = 2147483647;
        long quotient;
        if (seed <= 0 || !shuffled) {
            // Historical behavior: every nonnegative seed becomes 1.
            seed = (-seed < 1) ? 1 : -seed;
            for (int j = 39; j >= 0; --j) {
                quotient = seed / 127773;
                seed = 16807 * (seed - quotient * 127773) - 2836 * quotient;
                if (seed < 0)
                    seed += modulus;
                if (j < 32)
                    table[j] = seed;
            }
            shuffled = table[0];
        }
        quotient = seed / 127773;
        seed = 16807 * (seed - quotient * 127773) - 2836 * quotient;
        if (seed < 0)
            seed += modulus;
        const int j = shuffled / (1 + (modulus - 1) / 32);
        shuffled = table[j];
        table[j] = seed;
        float result = (1.0 / modulus) * shuffled;
        if (result > 1.0 - 1.2e-7)
            result = 1.0 - 1.2e-7;
        return result;
    }

public:
    explicit NumericalRecipesGaussian(long initial_seed)
        : seed(initial_seed), shuffled(0), stored(false), saved(0)
    {
        for (int i = 0; i < 32; ++i)
            table[i] = 0;
    }

    float gaussian()
    {
        if (stored) {
            stored = false;
            return saved;
        }
        float x, y, radius_squared;
        do {
            x = 2.0 * uniform() - 1.0;
            y = 2.0 * uniform() - 1.0;
            radius_squared = x * x + y * y;
        } while (radius_squared >= 1.0 || radius_squared == 0.0);
        // Unlike the MT version, this historical implementation rounds the
        // common multiplier to float before multiplying by x and y.
        const float multiplier =
            std::sqrt(-2.0 * std::log(static_cast<double>(radius_squared)) /
                      radius_squared);
        stored = true;
        saved = x * multiplier;
        return y * multiplier;
    }
};

template <typename Generator> void print_pool(Generator& generator)
{
    const float amplitude = 1.0f / std::sqrt(2.0f);
    for (int i = 0; i < 8192; ++i) {
        // GNU Radio called complex(gasdev(), gasdev()), whose argument order
        // is unspecified. Make GCC's observed right-to-left order explicit.
        // Compare an I/Q-swapped pool when examining another compiler.
        const float imaginary = generator.gaussian();
        const float real = generator.gaussian();
        std::printf("%.9g,%.9g\n", amplitude * real, amplitude * imaginary);
    }
}

int main(int argc, char** argv)
{
    if (argc != 3 || (std::strcmp(argv[1], "mt") && std::strcmp(argv[1], "nr"))) {
        std::fprintf(stderr, "Usage: %s {mt|nr} SEED\n", argv[0]);
        return 2;
    }
    char* end;
    errno = 0;
    const long long seed = std::strtoll(argv[2], &end, 0);
    if (errno || end == argv[2] || *end) {
        std::fprintf(stderr, "Invalid seed: %s\n", argv[2]);
        return 2;
    }
    if (!std::strcmp(argv[1], "mt")) {
        // GNU Radio used wall-clock time for seed 0, so exclude it from this
        // diagnostic rather than silently substitute a deterministic zero.
        if (seed <= 0 || seed > std::numeric_limits<unsigned int>::max()) {
            std::fprintf(stderr, "MT seed must be between 1 and 2^32-1.\n");
            return 2;
        }
        MersenneTwisterGaussian generator(static_cast<unsigned int>(seed));
        print_pool(generator);
    } else {
        if (seed <= -2147483647LL || seed >= 2147483647LL) {
            std::fprintf(stderr, "NR seed magnitude must be less than 2147483647.\n");
            return 2;
        }
        NumericalRecipesGaussian generator(static_cast<long>(seed));
        print_pool(generator);
    }
    return std::ferror(stdout) ? 1 : 0;
}
