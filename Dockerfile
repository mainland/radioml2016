FROM ubuntu:18.04
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

#
# Update
#
RUN apt-get update \
  && apt-get upgrade -y \
  && apt-get install -y \
  apt-utils \
  && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

#
# Install useful packages
#

RUN apt-get update \
  && apt-get install -y \
    git \
    ninja-build \
    sudo \
  && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

#
# Install packages required for UHD
#

RUN apt-get update \
  && apt-get install -y \
    autoconf \
    automake \
    build-essential \
    cmake \
    libboost-date-time-dev \
    libboost-dev \
    libboost-filesystem-dev \
    libboost-program-options-dev \
    libboost-regex-dev \
    libboost-serialization-dev \
    libboost-system-dev \
    libboost-test-dev \
    libboost-thread-dev \
    pkg-config \
    python3 \
    python3-dev \
    python3-distutils \
    python3-mako \
    python3-pip \
    python3-virtualenv \
    virtualenv \
  && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

#
# Install packages required for GNURadio
#

RUN apt-get update \
  && apt-get install -y \
    autoconf \
    automake \
    build-essential \
    ccache \
    cmake \
    cpufrequtils \
    doxygen \
    fort77 \
    g++ \
    git \
    gpsd \
    gpsd-clients \
    gtk2-engines-pixbuf \
    libasound2-dev \
    libboost-all-dev \
    libcanberra-gtk-module \
    libcomedi-dev \
    libcppunit-1.14-0 \
    libcppunit-dev \
    libcppunit-doc \
    libfftw3-bin \
    libfftw3-dev \
    libfftw3-doc \
    libfontconfig1-dev \
    libgps23 \
    libgps-dev \
    libgsl-dev \
    libncurses5 \
    libncurses5-dev \
    liborc-0.4-0 \
    liborc-0.4-dev \
    libpulse-dev \
    libqt4-dev \
    libqt4-dev-bin \
    libqwt6abi1 \
    libqwt-dev \
    libqwtplot3d-qt5-dev \
    libsdl1.2-dev \
    libtool \
    libudev-dev \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    libusb-dev \
    libxi-dev \
    libxrender-dev \
    libzmq3-dev \
    libzmq5 \
    ncurses-bin \
    pyqt4-dev-tools \
    python-cheetah \
    python-dev \
    python-docutils \
    python-gps \
    python-gtk2 \
    python-lxml \
    python-mako \
    python-numpy \
    python-numpy-dbg \
    python-numpy-doc \
    python-opengl \
    python-qt4 \
    python-qt4-dbg \
    python-qt4-dev \
    python-qt4-doc \
    python-qwt5-qt4 \
    python-requests \
    python-scipy \
    python-setuptools \
    python-six \
    python-sphinx \
    python-tk \
    python-wxgtk3.0 \
    python-zmq \
    qt4-bin-dbg \
    qt4-default \
    qt4-dev-tools \
    qt4-doc \
    r-base-dev \
    swig \
    wget \
  && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

#
# Install packages required for RadioML
#

RUN apt-get update \
  && apt-get install -y \
    libavcodec-dev \
    libavformat-dev \
    python-matplotlib \
    python-pip \
  && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN pip install cmappertools==1.0.26

#
# Build and install UHD
#

RUN git clone -b dragonradio/3.9.5 https://github.com/drexelwireless/uhd.git /tmp/uhd \
  && cd /tmp/uhd/host \
  && mkdir build \
  && cd build \
  && cmake -DCMAKE_FIND_ROOT_PATH=/usr -G Ninja .. \
  && ninja \
  && ninja install \
  && ldconfig \
  && cd \
  && rm -rf /tmp/uhd

#
# Build and install GNURadio
#

RUN git clone -b maint-3.7 --recursive https://github.com/gnuradio/gnuradio.git /usr/local/gnuradio/src/gnuradio \
  && cd /usr/local/gnuradio/src/gnuradio \
  && mkdir build \
  && cd build \
  && cmake -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=/usr/bin/python -DGR_PYTHON_DIR=/usr/lib/python2.7/dist-packages -G Ninja .. \
  && ninja \
  && ninja install \
  && ldconfig \
  && cd \
  && rm -rf /usr/local/gnuradio/src/gnuradio/build

#
# Build and install https://github.com/osh/gr-mediatools.git
#
# See:
#   https://stackoverflow.com/questions/43432797/failed-to-make-when-installing-gr-mediatools
#   https://stackoverflow.com/questions/43067480/cmake-building-error-trying-to-install-gnuradio-mediatools-%ef%bd%81module-in-gnuradio/43069374#43069374

RUN git clone https://github.com/osh/gr-mediatools.git /usr/local/gnuradio/src/gr-mediatools \
  && cd /usr/local/gnuradio/src/gr-mediatools \
  && git checkout d11c38bb \
  && sed -ibak -e 's/d_frame = avcodec_alloc_frame/d_frame = av_frame_alloc/' lib/mediatools_audiosource_impl.cc \
  && mkdir build \
  && cd build \
  && cmake -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=/usr/bin/python -DGR_PYTHON_DIR=/usr/lib/python2.7/dist-packages -G Ninja .. \
  && ninja \
  && ninja install \
  && ldconfig \
  && cd \
  && rm -rf /usr/local/gnuradio/src/gr-mediatools/build

#
# Build and install https://github.com/gr-vt/gr-mapper.git
#

RUN git clone https://github.com/gr-vt/gr-mapper.git /usr/local/gnuradio/src/gr-mapper \
  && cd /usr/local/gnuradio/src/gr-mapper \
  && git checkout 2ea1eb68 \
  && mkdir build \
  && cd build \
  && cmake -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=/usr/bin/python -DGR_PYTHON_DIR=/usr/lib/python2.7/dist-packages -G Ninja .. \
  && ninja \
  && ninja install \
  && ldconfig \
  && cd \
  && rm -rf /usr/local/gnuradio/src/gr-mapper/build

#
# Create radioml user
#
ARG USERNAME=radioml
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
  && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
  && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
  && chmod 0440 /etc/sudoers.d/$USERNAME

#
# Run everything from here on out as the atf user
#
USER $USERNAME

WORKDIR /home/$USERNAME

# VOLUME ["/cache", "/common_logs"]

CMD ["/bin/bash"]
