# Historical reconstruction candidate; see docs/historical-environment.md.
# The exact original environment is unknown. Xenial security updates postdate
# 2016; retain the built image and /opt/replay-provenance to preserve this build.
# Audio decoding uses Xenial's initial FFmpeg 2.8.6 packages. The original
# decoder and Ubuntu package patch levels remain unestablished.
#
# Build: docker build --platform linux/amd64 -t radioml2016:historical .
# Compare mapper normalization histories with --build-arg MAPPER_REV=...
#   none: 463f9e94f5ea45e5be64bae06291423ead3b70f2 (Jan10,2016)
#   buggy: 52383e2832a86feb452ddd80928bce69147f01c0 (Aug23,2016)
#   fixed: 15e71bf01be68d427ed9f37966b83efc1180a1d5 (Oct11,2016)
# The no-normalization revision is the evidence-supported default. A direct
# candidate supports the distributed dataset's relative SNR pattern. The
# advancing-seed comparison has a common original-minus-candidate offset of
# 2.871 dB. Restarting the channel seed reduces it to 0.080 dB against the
# retained original-data curves, without recovering the original RNG state.
# See docs/mapper-version-evidence.md for the measurements and limitations.
FROM ubuntu:16.04@sha256:a3785f78ab8547ae2710c89e627783cfa7ee7824d3468cae6835c9f4eae23ff7

ARG DEBIAN_FRONTEND=noninteractive
ARG GR_REV=59daaff0d9d04373d3a6b14ea7b46e080bad7a1e
ARG VOLK_REV=4465f9b26354e555e583a7d654710cb63cf914ce
ARG MAPPER_REV=463f9e94f5ea45e5be64bae06291423ead3b70f2
ARG MEDIATOOLS_REV=d11c38bbadb2a56494502f2acc54659749bb81db
ARG BUILD_JOBS=4

# Direct package versions verified against archive.ubuntu.com's xenial and
# xenial-updates Packages.gz on 2026-09-13. Transitive package versions are
# recorded below; retaining the image/debs is required for a complete lock.
# Do not replace these with an apt-get upgrade or an unpinned Python pip install.
RUN printf '%s\n' \
      'deb http://archive.ubuntu.com/ubuntu xenial main universe' \
      'deb http://archive.ubuntu.com/ubuntu xenial-updates main universe' \
      > /etc/apt/sources.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates=20210119~16.04.1 \
      curl=7.47.0-1ubuntu2.19 \
      git=1:2.7.4-0ubuntu1.10 \
      sudo=1.8.16-0ubuntu1.10 \
      build-essential=12.1ubuntu2 \
      gcc-5=5.4.0-6ubuntu1~16.04.12 \
      g++-5=5.4.0-6ubuntu1~16.04.12 \
      cmake=3.5.1-1ubuntu3 \
      pkg-config=0.29.1-0ubuntu1 \
      swig=3.0.8-0ubuntu3 \
      python=2.7.12-1~16.04 \
      python-dev=2.7.12-1~16.04 \
      python2.7=2.7.12-1ubuntu0~16.04.18 \
      python2.7-dev=2.7.12-1ubuntu0~16.04.18 \
      python-numpy=1:1.11.0-1ubuntu1 \
      python-scipy=0.17.0-1 \
      python-matplotlib=1.5.1-1ubuntu1 \
      python-mako=1.0.3+ds1-1ubuntu1 \
      python-cheetah=2.4.4-3.fakesyncbuild1 \
      python-six=1.10.0-3 \
      python-setuptools=20.7.0-1 \
      libboost1.58-dev=1.58.0+dfsg-5ubuntu3.1 \
      libboost-date-time-dev=1.58.0.1ubuntu1 \
      libboost-program-options-dev=1.58.0.1ubuntu1 \
      libboost-filesystem-dev=1.58.0.1ubuntu1 \
      libboost-system-dev=1.58.0.1ubuntu1 \
      libboost-regex-dev=1.58.0.1ubuntu1 \
      libboost-thread-dev=1.58.0.1ubuntu1 \
      libboost-test-dev=1.58.0.1ubuntu1 \
      libfftw3-dev=3.3.4-2ubuntu1 \
      libcppunit-dev=1.13.2-2.1 \
      liborc-0.4-dev=1:0.4.25-1 \
      libavcodec-dev=7:2.8.6-1ubuntu2 \
      libavformat-dev=7:2.8.6-1ubuntu2 \
      libavutil-dev=7:2.8.6-1ubuntu2 \
      libswresample-dev=7:2.8.6-1ubuntu2 \
      libavcodec-ffmpeg56=7:2.8.6-1ubuntu2 \
      libavformat-ffmpeg56=7:2.8.6-1ubuntu2 \
      libavutil-ffmpeg54=7:2.8.6-1ubuntu2 \
      libswresample-ffmpeg1=7:2.8.6-1ubuntu2 \
 && mkdir -p /opt/replay-provenance /opt/replay-src /opt/rml \
 && dpkg-query -W -f='${Package}\t${Version}\n' > /opt/replay-provenance/dpkg.tsv \
 && cp /etc/apt/sources.list /opt/replay-provenance/sources.list \
 && gcc-5 --version > /opt/replay-provenance/compiler.txt \
 && ldd --version > /opt/replay-provenance/libc.txt \
 && python2.7 -c 'import sys,numpy,scipy; print(sys.version); print(numpy.__version__); print(scipy.__version__); numpy.show_config()' \
      > /opt/replay-provenance/python.txt

ENV PATH=/opt/rml/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV PYTHONPATH=/opt/rml/lib/python2.7/dist-packages
ENV LD_LIBRARY_PATH=/opt/rml/lib
ENV PKG_CONFIG_PATH=/opt/rml/lib/pkgconfig
ENV CMAKE_PREFIX_PATH=/opt/rml

# Check v3.7.10.1's exact VOLK gitlink and fetch it explicitly: Xenial's Git
# cannot retrieve a missing old commit during a shallow submodule checkout.
# Do not use update --remote: .gitmodules' branch=master is not the lock.
RUN git init /opt/replay-src/gnuradio \
 && cd /opt/replay-src/gnuradio \
 && git remote add origin https://github.com/gnuradio/gnuradio.git \
 && git fetch --depth 1 origin "$GR_REV" \
 && git checkout --detach FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$GR_REV" \
 && test "$(git rev-parse HEAD:volk)" = "$VOLK_REV" \
 && git -C volk init \
 && git -C volk remote add origin https://github.com/gnuradio/volk.git \
 && git -C volk fetch --depth 1 origin "$VOLK_REV" \
 && git -C volk checkout --detach FETCH_HEAD \
 && test "$(git -C volk rev-parse HEAD)" = "$VOLK_REV" \
 && mkdir build \
 && cd build \
 && cmake .. \
      -DCMAKE_INSTALL_PREFIX=/opt/rml \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_C_COMPILER=/usr/bin/gcc-5 \
      -DCMAKE_CXX_COMPILER=/usr/bin/g++-5 \
      -DPYTHON_EXECUTABLE=/usr/bin/python2.7 \
      -DGR_PYTHON_DIR=/opt/rml/lib/python2.7/dist-packages \
      -DENABLE_DEFAULT=OFF \
      -DENABLE_PYTHON=ON \
      -DENABLE_INTERNAL_VOLK=ON \
      -DENABLE_VOLK=ON \
      -DENABLE_GNURADIO_RUNTIME=ON \
      -DENABLE_GR_BLOCKS=ON \
      -DENABLE_GR_FFT=ON \
      -DENABLE_GR_FILTER=ON \
      -DENABLE_GR_ANALOG=ON \
      -DENABLE_GR_DIGITAL=ON \
      -DENABLE_GR_CHANNELS=ON \
      -DENABLE_TESTING=OFF \
      -DENABLE_PROFILING=OFF \
      -DENABLE_DOXYGEN=OFF \
 && cmake --build . -- -j"$BUILD_JOBS" \
 && cmake --build . --target install \
 && cp CMakeCache.txt /opt/replay-provenance/gnuradio-CMakeCache.txt \
 && git -C .. rev-parse HEAD > /opt/replay-provenance/gnuradio.sha \
 && git -C ../volk rev-parse HEAD > /opt/replay-provenance/volk.sha

RUN git init /opt/replay-src/gr-mapper \
 && cd /opt/replay-src/gr-mapper \
 && git remote add origin https://github.com/gr-vt/gr-mapper.git \
 && git fetch --depth 1 origin "$MAPPER_REV" \
 && git checkout --detach FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$MAPPER_REV" \
 && mkdir build \
 && cd build \
 && cmake .. \
      -DCMAKE_INSTALL_PREFIX=/opt/rml \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_C_COMPILER=/usr/bin/gcc-5 \
      -DCMAKE_CXX_COMPILER=/usr/bin/g++-5 \
      -DPYTHON_EXECUTABLE=/usr/bin/python2.7 \
      -DGR_PYTHON_DIR=/opt/rml/lib/python2.7/dist-packages \
 && cmake --build . -- -j"$BUILD_JOBS" \
 && cmake --build . --target install \
 && cp CMakeCache.txt /opt/replay-provenance/mapper-CMakeCache.txt \
 && git -C .. rev-parse HEAD > /opt/replay-provenance/mapper.sha \
 && python2.7 -c 'from gnuradio import gr,blocks,fft,filter,analog,digital,channels; import mapper; print(gr.version())' \
      > /opt/replay-provenance/import-check.txt

# Allow both Python 2 install layouts used by these older CMake modules.
ENV PYTHONPATH=/opt/rml/lib/python2.7/dist-packages:/opt/rml/lib/python2.7/site-packages
ENV MPLBACKEND=Agg

# October 10, 2016 mediatools revision explicitly selects Python 2. FFmpeg 2.8 still
# exposes avcodec_alloc_frame, so retain its original source without the
# av_frame_alloc compatibility edit required by the previous 18.04 Dockerfile.
# Candidate prior to October 10: 2cac133182206aef994a0db4951001fe86d1bccf (August 30).
RUN git init /opt/replay-src/gr-mediatools \
 && cd /opt/replay-src/gr-mediatools \
 && git remote add origin https://github.com/osh/gr-mediatools.git \
 && git fetch --depth 1 origin "$MEDIATOOLS_REV" \
 && git checkout --detach FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$MEDIATOOLS_REV" \
 && mkdir build \
 && cd build \
 && cmake .. \
      -DCMAKE_INSTALL_PREFIX=/opt/rml \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_C_COMPILER=/usr/bin/gcc-5 \
      -DCMAKE_CXX_COMPILER=/usr/bin/g++-5 \
      -DPYTHON_EXECUTABLE=/usr/bin/python2.7 \
      -DGR_PYTHON_DIR=/opt/rml/lib/python2.7/dist-packages \
 && cmake --build . -- -j"$BUILD_JOBS" \
 && cmake --build . --target install \
 && cp CMakeCache.txt /opt/replay-provenance/mediatools-CMakeCache.txt \
 && git -C .. rev-parse HEAD > /opt/replay-provenance/mediatools.sha \
 && python2.7 -c 'import mediatools,matplotlib; print(mediatools.__file__); print(matplotlib.__version__)' \
      >> /opt/replay-provenance/import-check.txt

# No automatic volk_profile: SIMD selection changes floating point rounding.
# Record CPU flags, VOLK preferences, output hashes and all RNG states for each
# experiment. VOLK_GENERIC=1 is a separately labeled control, not evidence of
# the original CPU's execution path. This image intentionally retains the
# historical shared lrand48 behavior.
# Retain the documented UID/GID build arguments for mounted source/data files.
ARG USERNAME=radioml
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN groupadd --gid "$USER_GID" "$USERNAME" \
 && useradd --uid "$USER_UID" --gid "$USER_GID" -m "$USERNAME" \
 && printf '%s ALL=(root) NOPASSWD:ALL\n' "$USERNAME" > "/etc/sudoers.d/$USERNAME" \
 && chmod 0440 "/etc/sudoers.d/$USERNAME"
USER $USERNAME
WORKDIR /home/$USERNAME
CMD ["/bin/bash"]
