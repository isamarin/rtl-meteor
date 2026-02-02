FROM debian:12

ENV DEBIAN_FRONTEND=noninteractive

# Базовые зависимости
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
    libopencv-dev \
    libglfw3-dev \
    libglew-dev \
    libglm-dev \
    libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev \
    && rm -rf /var/lib/apt/lists/*

# Rust (для зависимостей SatDump)
RUN apt-get update && apt-get install -y curl && \
    curl https://sh.rustup.rs -sSf | bash -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# VOLK (рекомендуется SatDump)
RUN git clone --recursive https://github.com/gnuradio/volk.git /opt/volk && \
    cd /opt/volk && mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make -j$(nproc) && make install && ldconfig

# SatDump
RUN git clone --recursive https://github.com/SatDump/SatDump.git /opt/satdump
WORKDIR /opt/satdump

RUN mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make -j$(nproc) && \
    make install

ENTRYPOINT ["satdump"]
