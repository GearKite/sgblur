FROM bitnami/pytorch:2.2.1-debian-12-r0

WORKDIR /opt/blur

USER 0

# Dependencies
RUN apt-get -qq update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    # * Pillow
    libffi-dev \
    libfreetype6-dev \
    libfribidi-dev \
    libharfbuzz-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff5-dev \
    libwebp-dev \
    gcc \
    libgl1 \
    # * sgblur
    libturbojpeg0-dev \
    libjpeg-turbo-progs \
    exiftran \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt ./
RUN pip install --no-cache-dir -r ./requirements.txt

# Source files
COPY ./src ./src
COPY ./scripts ./scripts
COPY ./models ./models
COPY ./demo.html ./
COPY ./docker/docker-entrypoint.sh ./
RUN chmod +x ./docker-entrypoint.sh

# Expose service
EXPOSE 8001
ENTRYPOINT ["./docker-entrypoint.sh"]
