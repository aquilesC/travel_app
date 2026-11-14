# ---- CSS: Tailwind standalone CLI (no Node anywhere), v4 #29 ------------------
FROM debian:trixie-slim AS css
ARG TAILWIND_VERSION=4.3.5
ARG TAILWIND_SHA256=e47695cee3f0d90623a91f3939b08bdee610eb5ad99340adff9d4145b284d6cc
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSLo /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && echo "${TAILWIND_SHA256}  /usr/local/bin/tailwindcss" | sha256sum -c - \
    && chmod +x /usr/local/bin/tailwindcss \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# Only what Tailwind scans for class names, so code changes don't rebuild the CSS layer.
COPY static ./static
COPY templates ./templates
COPY trips/templates ./trips/templates
COPY trips/templatetags ./trips/templatetags
COPY trips/forms.py ./trips/forms.py
COPY accounts/templates ./accounts/templates
COPY accounts/forms.py ./accounts/forms.py
RUN tailwindcss -i static/src/app.css -o static/css/tailwind.css --minify

# ---- App -----------------------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg for video/audio processing; postgresql-client-18 (from the PGDG repo,
# matching the server's major version) for nightly pg_dump.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN useradd --create-home --uid 1000 app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
COPY --from=css --chown=app:app /src/static/css/tailwind.css /app/static/css/tailwind.css
RUN chmod +x entrypoint.sh \
    && mkdir -p /app/staticfiles /app/media \
    && chown app:app /app/staticfiles /app/media

USER app

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "4", "--timeout", "120", "--access-logfile", "-"]
