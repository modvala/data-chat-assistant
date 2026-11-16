# The image of the CLI for a reviewer (#40). It is not the image of the hosted mode (#5).
# It contains the app and the Google Cloud CLI, so the host needs only Docker.
# Build and run it with compose.yaml: docker compose run --rm dca <command>.
FROM ghcr.io/astral-sh/uv:0.12.24-python3.12-trixie-slim

# gcloud and bq: for the login, scripts/setup-gcp.sh and setup-bq.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    > /etc/apt/sources.list.d/google-cloud-sdk.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends google-cloud-cli \
 && rm -rf /var/lib/apt/lists/*

# The app runs as a user that is not root. The named volume gcloud-config keeps the
# credentials of gcloud and of ADC in CLOUDSDK_CONFIG.
RUN useradd --create-home --uid 1000 dca \
 && mkdir -p /home/dca/.config/gcloud /app/data \
 && chown -R dca:dca /home/dca/.config /app
ENV CLOUDSDK_CONFIG=/home/dca/.config/gcloud
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ENV PATH=/app/.venv/bin:$PATH

USER dca
WORKDIR /app

# The dependencies first, so that a code change does not install them again.
COPY --chown=dca:dca pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=dca:dca . .
RUN uv sync --frozen --no-dev

CMD ["chat"]
