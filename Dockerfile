FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Базовые зависимости
RUN apt-get update && apt-get install -y \
    git cmake build-essential pkg-config \
    libfftw3-dev libpng-dev libzstd-dev \
    libusb-1.0-0-dev libhidapi-dev \
    libopencv-dev libcurl4-openssl-dev \
    libboost-all-dev libeigen3-dev \
    python3 python3-pip python3-mako \
    libarmadillo-dev \
    ocl-icd-opencl-dev \
    libnng-dev \
    && rm -rf /var/lib/apt/lists/*



# Rust (нужен для некоторых модулей SatDump)
RUN apt-get update && apt-get install -y curl && \
    curl https://sh.rustup.rs -sSf | bash -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# ---------------------------
# Сборка VOLK
# ---------------------------
RUN git clone --recursive https://github.com/gnuradio/volk.git /opt/volk && \
    cd /opt/volk && \
    git submodule update --init --recursive && \
    mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make -j$(nproc) && \
    make install && \
    ldconfig

# ---------------------------
# Сборка SatDump
# ---------------------------
RUN git clone --recursive https://github.com/SatDump/SatDump.git /opt/satdump

WORKDIR /opt/satdump

RUN mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make -j$(nproc) && \
    make install

ENTRYPOINT ["satdump"]
