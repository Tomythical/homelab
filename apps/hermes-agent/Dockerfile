# Adds the native runtime libraries required by Playwright Chromium.
# The base image remains pinned to the same WebUI release used by deployment.yaml.
FROM ghcr.io/nesquena/hermes-webui:0.52.264

LABEL org.opencontainers.image.source="https://github.com/Tomythical/homelab"

USER root

ARG KUBECTL_VERSION=v1.34.0
ARG KUBECTL_SHA256=cfda68cba5848bc3b6c6135ae2f20ba2c78de20059f68789c090166d6abc3e2c

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libasound2t64 \
        libatk-bridge2.0-0t64 \
        libatk1.0-0t64 \
        libatspi2.0-0t64 \
        libcairo2 \
        libcups2t64 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libglib2.0-0t64 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libx11-6 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
        fonts-liberation \
        fonts-noto-color-emoji \
    && curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && echo "${KUBECTL_SHA256}  /usr/local/bin/kubectl" | sha256sum -c - \
    && chmod 0755 /usr/local/bin/kubectl \
    && rm -rf /var/lib/apt/lists/*

# Preserve the upstream root entrypoint; it drops privileges before starting WebUI.
USER root
