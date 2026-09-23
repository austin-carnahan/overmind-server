# Base + Skyscraper build steps adapted from Skyscraper's own official
# docker/Dockerfile (https://github.com/Gemba/skyscraper/blob/master/docker/Dockerfile),
# with Python added so `curate` can shell out to the compiled `Skyscraper`
# binary in the same image instead of a second container.
FROM ubuntu:24.04

ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    qt6-base-dev \
    qmake6 \
    qt6-base-dev-tools \
    libqt6sql6-sqlite \
    p7zip-full \
    wget \
    sudo \
    adduser \
    git \
    ca-certificates \
    python3 \
    python3-pip \
    mame-tools \
  && rm -rf /var/lib/apt/lists/*

# update_skyscraper.sh expects a non-root sudo-capable user to exist, per
# Skyscraper's own Dockerfile.
RUN useradd -m docker && echo "docker:docker" | chpasswd && adduser docker sudo

RUN git clone --depth 1 https://github.com/Gemba/skyscraper.git /opt/skyscraper-src \
  && cd /opt/skyscraper-src \
  && rm -f ./VERSION.ini \
  && chmod +x update_skyscraper.sh \
  && ./update_skyscraper.sh \
  && cd / && rm -rf /opt/skyscraper-src

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY curate ./curate

ENTRYPOINT ["python3", "-m", "curate.cli"]
