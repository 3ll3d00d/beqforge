# The beqforge designer as a container: `beqforge serve-designer` for a beqdesigner pipeline service
# beside it. Build from the repository root:
#
#     docker build -f packaging/designer/Dockerfile -t beqforge-designer .
#
# Configuration is the server's own environment variables (README, "beqdesigner integration").
# The defaults here listen on every interface, take audio by reference under /work (mount the
# pipeline's work directory there) and keep the stage cache in /cache (mount a volume).
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENCE.md ./
COPY beq_common beq_common
COPY beqforge beqforge
COPY beqforge_device_check beqforge_device_check
COPY beqoptimiser beqoptimiser
COPY tools tools
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
RUN uv sync --frozen --no-dev --extra designer --no-editable \
    && /opt/venv/bin/beqforge serve-designer --help > /dev/null

FROM python:3.13-slim
ARG PUID=1000
ARG PGID=1000
ARG VERSION=unknown
ARG REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/3ll3d00d/beqforge" \
      org.opencontainers.image.title="beqforge designer" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
RUN groupadd -g "${PGID}" beqforge && useradd -m -u "${PUID}" -g beqforge beqforge \
    && mkdir -p /work /cache /records \
    && chown beqforge:beqforge /work /cache /records
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 MPLBACKEND=Agg MPLCONFIGDIR=/tmp/matplotlib \
    BEQFORGE_HOST=0.0.0.0 BEQFORGE_PORT=8420 BEQFORGE_SHARED_ROOT=/work BEQFORGE_CACHE_DIR=/cache
USER beqforge
EXPOSE 8420
VOLUME ["/cache"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"BEQFORGE_PORT\"]}/health', timeout=3).close()" || exit 1
ENTRYPOINT ["beqforge", "serve-designer"]
