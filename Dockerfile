ARG LIBC=glibc
FROM ghcr.io/void-linux/void-${LIBC}-full:latest

RUN mkdir -p /etc/xbps.d && \
    cp /usr/share/xbps.d/*-repository-*.conf /etc/xbps.d/ && \
    sed -i 's|repo-default|repo-ci|g' /etc/xbps.d/*-repository-*.conf && \
    xbps-install -Syu xbps && \
    xbps-install -yu && \
    xbps-install -y sudo bash curl git

RUN useradd -G xbuilder -M builder

RUN git clone --depth 1 https://github.com/void-linux/void-packages.git /void-packages && \
    chown -R builder:builder /void-packages

WORKDIR /void-packages

RUN sudo -Eu builder common/travis/set_mirror.sh && \
    sudo -Eu builder common/travis/prepare.sh && \
    common/travis/fetch-xtools.sh && \
    chown -R builder:builder . && \
    rm -rf hostdir/sources/* masterdir-*/var/cache/xbps/*
