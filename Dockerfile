FROM python:3.11-slim

LABEL org.opencontainers.image.title="Switch Kit"
LABEL org.opencontainers.image.description="Plex → Jellyfin migration readiness inspector"
LABEL org.opencontainers.image.licenses="AGPL-3.0"
LABEL org.opencontainers.image.version="0.1.3"
LABEL org.opencontainers.image.source="https://github.com/switchkit-app/switchkit"

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
