FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    git cmake build-essential pkg-config \
    libfftw3-dev libpng-dev libzstd-dev \
    libusb-1.0-0-dev libhidapi-dev \
    libcurl4-openssl-dev \
    libboost-all-dev libeigen3-dev \
    python3 python3-pip python3-mako \
    libarmadillo-dev \
    ocl-icd-opencl-dev \
    libnng-dev \
    libjemalloc-dev \
    libtiff-dev \
    && rm -rf /var/lib/apt/lists/*

# Rust
RUN apt-get update && apt-get install -y curl && \
    curl https://sh.rustup.rs -sSf | bash -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# VOLK
RUN git clone --recursive https://github.com/gnuradio/volk.git /opt/volk && \
    cd /opt/volk && git submodule update --init --recursive && \
    mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make -j$(nproc) && make install && ldconfig

# SatDump
RUN git clone --recursive https://github.com/SatDump/SatDump.git /opt/satdump
WORKDIR /opt/satdump

# Disable GUI and interface completely
RUN sed -i 's/add_subdirectory(src-ui)/#add_subdirectory(src-ui)/' CMakeLists.txt
RUN sed -i 's/add_subdirectory(src-interface)/#add_subdirectory(src-interface)/' CMakeLists.txt
RUN sed -i 's/add_subdirectory(src-gui)/#add_subdirectory(src-gui)/' CMakeLists.txt || true

RUN mkdir build && cd build && \
    cmake .. \
      -DCMAKE_BUILD_TYPE=Release \
      -DUSE_OPENCV=OFF && \
    make -j$(nproc) && \
    make install



ENTRYPOINT ["satdump"]
