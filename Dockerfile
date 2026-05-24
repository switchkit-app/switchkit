FROM python:3.11-slim@sha256:4aded0d8e6cc5da8e12a9fd235b9c1f70534cd3b8f8d24480bcc090c2ff2fd4b

LABEL org.opencontainers.image.title="Switch Kit"
LABEL org.opencontainers.image.description="Plex → Jellyfin migration readiness inspector"
LABEL org.opencontainers.image.licenses="AGPL-3.0"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.source="https://github.com/switchkit/plex-to-jellyfin"

WORKDIR /app

# Create non-root user (C5 fix)
RUN adduser --disabled-password --gecos "" switchkit

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir . \
    && mkdir -p /output \
    && chown -R switchkit:switchkit /app /output

USER switchkit

VOLUME ["/plex", "/output"]

HEALTHCHECK --interval=30s --timeout=3s --retries=1 \
    CMD switchkit --version || exit 1

ENTRYPOINT ["switchkit"]
CMD ["inspect", "--help"]
