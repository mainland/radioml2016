#!/usr/bin/env python
from gnuradio import gr, blocks
import mediatools
import numpy as np
import os

class source_alphabet(gr.hier_block2):
    def __init__(self, dtype="discrete", limit=10000, randomize=False,
                 capture_random_mask=False, source_offset=0,
                 random_mask=None):
        if capture_random_mask or random_mask is not None:
            self.random_mask = None
        if(dtype == "discrete"):
            gr.hier_block2.__init__(self, "source_alphabet",
                gr.io_signature(0,0,0),
                gr.io_signature(1,1,gr.sizeof_char))

            self.src = blocks.file_source(gr.sizeof_char, "source_material/gutenberg_shakespeare.txt")
            self.convert = blocks.packed_to_unpacked_bb(1, gr.GR_LSB_FIRST);
            #self.convert = blocks.packed_to_unpacked_bb(8, gr.GR_LSB_FIRST);
            self.limit = blocks.head(gr.sizeof_char, limit)
            self.connect(self.src,self.convert)
            last = self.convert

            # whiten our sequence with a random block scrambler (optionally)
            if(randomize):
                rand_len = 256
                if random_mask is None:
                    rand_bits = np.random.randint(2, size=rand_len)
                else:
                    rand_bits = np.asarray(random_mask, dtype=np.uint8)
                    if (rand_bits.shape != (rand_len,) or not
                            np.logical_or(
                                rand_bits == 0, rand_bits == 1).all()):
                        raise ValueError(
                            "random mask must contain 256 binary values")
                if capture_random_mask or random_mask is not None:
                    # Preserve the exact whitening sequence as transmission
                    # provenance without changing the GNU Radio input array.
                    self.random_mask = np.asarray(
                        rand_bits, dtype=np.uint8).copy()
                source_bits = (rand_bits.tolist()
                               if random_mask is not None else rand_bits)
                self.randsrc = blocks.vector_source_b(source_bits, True)
                self.xor = blocks.xor_bb()
                self.connect(self.randsrc,(self.xor,1))
                self.connect(last, self.xor)
                last = self.xor

        else:   # "type_continuous"
            gr.hier_block2.__init__(self, "source_alphabet",
                gr.io_signature(0,0,0),
                gr.io_signature(1,1,gr.sizeof_float))

            canonical_source = os.environ.get("RADIOML_ANALOG_SOURCE")
            if canonical_source is None:
                if source_offset:
                    raise ValueError(
                        "source offsets require the canonical analog source")
                # Provenance: this is the original RadioML conversion path. It
                # remains available to the historical image; reproducible
                # generation sets RADIOML_ANALOG_SOURCE to the byte-verified
                # float32 stream derived through this exact chain.
                self.src = mediatools.audiosource_s(
                    ["source_material/serial-s01-e01.mp3"])
                self.convert2 = blocks.interleaved_short_to_complex()
                self.convert3 = blocks.multiply_const_cc(1.0/65535)
                self.convert = blocks.complex_to_float()
                self.connect(self.src, self.convert2, self.convert3,
                             self.convert)
                last = self.convert
            else:
                if not os.path.isfile(canonical_source):
                    raise IOError("canonical analog source not found: " +
                                  canonical_source)
                self.src = blocks.file_source(
                    gr.sizeof_float, canonical_source, False)
                if source_offset < 0 or not self.src.seek(
                        source_offset, os.SEEK_SET):
                    raise ValueError("invalid analog source offset: %r" %
                                     source_offset)
                last = self.src
            self.limit = blocks.head(gr.sizeof_float, limit)

        # connect head or not, and connect to output
        if(limit==None):
            self.connect(last, self)
        else:
            self.connect(last, self.limit, self)


if __name__ == "__main__":
    print "QA..."

    # Test discrete source
    tb = gr.top_block()
    src = source_alphabet("discrete", 1000)
    snk = blocks.vector_sink_b()
    tb.run()

    # Test continuous source
    tb = gr.top_block()
    src = source_alphabet("continuous", 1000)
    snk = blocks.vector_sink_f()
    tb.run()
