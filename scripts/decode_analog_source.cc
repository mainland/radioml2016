// Decode the RadioML analog source through the pinned mediatools implementation.
//
// The original GNU Radio flowgraph treats consecutive mono int16 samples as
// complex values, multiplies them by float32(1/65535), and keeps the real part.
// This program deliberately preserves that unusual even-sample mapping.  It is
// build-time provenance machinery, not a replacement MP3 implementation.
#include <mediatools_audiosource_impl.h>

#include <cstdint>
#include <cstdio>
#include <vector>

int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s SOURCE_MP3 OUTPUT_F32\n", argv[0]);
        return 2;
    }

    mediatools_audiosource_impl decoder;
    if (!decoder.open(argv[1])) return 3;
    FILE* output = std::fopen(argv[2], "wb");
    if (!output) return 4;

    const float scale = static_cast<float>(1.0 / 65535.0);
    std::uint64_t decoded_shorts = 0;
    std::uint64_t emitted_floats = 0;
    std::vector<int16_t> values;
    while (decoder.d_ready) {
        values.clear();
        decoder.readData(values);
        for (std::vector<int16_t>::const_iterator value = values.begin();
             value != values.end(); ++value, ++decoded_shorts) {
            if (decoded_shorts % 2 != 0) continue;
            const float converted = static_cast<float>(*value) * scale;
            if (std::fwrite(&converted, sizeof(converted), 1, output) != 1) {
                std::fclose(output);
                decoder.close();
                return 5;
            }
            ++emitted_floats;
        }
    }

    const int close_status = std::fclose(output);
    decoder.close();
    if (close_status != 0) return 6;
    std::printf("decoded_shorts=%llu emitted_floats=%llu\n",
                static_cast<unsigned long long>(decoded_shorts),
                static_cast<unsigned long long>(emitted_floats));
    return 0;
}
