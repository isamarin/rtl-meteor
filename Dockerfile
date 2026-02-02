###############################################
# Stage 1 — Build environment
###############################################
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# Base dependencies
RUN apt-get update && apt-get install -y \
    git build-essential cmake g++ pkgconf \
    libfftw3-dev libpng-dev libtiff-dev \
    libjemalloc-dev libcurl4-openssl-dev \
    libvolk2-dev libnng-dev \
    libglfw3-dev zenity \
    portaudio19-dev libzstd-dev libhdf5-dev \
    librtlsdr-dev libhackrf-dev libairspy-dev libairspyhf-dev \
    libad9361-dev libiio-dev libbladerf-dev \
    libomp-dev ocl-icd-opencl-dev \
    intel-opencl-icd mesa-opencl-icd \
    libopencv-dev libarmadillo-dev \
    libglew-dev libglm-dev \
    libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev \
    python3 python3-pip python3-mako \
    && rm -rf /var/lib/apt/lists/*

# Clone SatDump
RUN git clone --recursive https://github.com/SatDump/SatDump.git /opt/satdump
WORKDIR /opt/satdump

# Build SatDump
RUN mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr && \
    make -j$(nproc) && \
    make install

###############################################
# Stage 2 — Minimal runtime
###############################################
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

# Runtime dependencies only
RUN apt-get update && apt-get install -y \
    libfftw3-3 libpng16-16 libtiff5 \
    libjemalloc2 libcurl4 \
    libvolk2 libnng \
    libglfw3 zenity \
    portaudio19-dev libzstd1 libhdf5-103 \
    librtlsdr0 libhackrf0 libairspy0 libairspyhf1 \
    libad9361-0 libiio0 libbladerf2 \
    libomp5 ocl-icd-libopencl1 \
    intel-opencl-icd mesa-opencl-icd \
    libopencv-core4.5 libopencv-imgproc4.5 libopencv-highgui4.5 \
    libarmadillo10 \
    libglew2.2 libglm-dev \
    libxrandr2 libxinerama1 libxcursor1 libxi6 \
    && rm -rf /var/lib/apt/lists/*

# Copy binaries from builder
COPY --from=builder /usr /usr

# Create user matching host UID/GID
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN groupadd -g $HOST_GID satdump && \
    useradd -m -u $HOST_UID -g $HOST_GID satdump

USER satdump
WORKDIR /home/satdump

ENTRYPOINT ["satdump"]
