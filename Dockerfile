# file-observer — deterministic file-observation tool.
# Scan a mounted directory, get a JSON manifest on stdout:
#
#   docker run --rm -v "/path/to/scan:/data:ro" ghcr.io/russalo/file-observer > manifest.json
#
# (the default command is `--stdout .`, so it scans the mounted /data and prints the
# manifest; pass your own args to override, e.g. `… ghcr.io/russalo/file-observer /data --specialists --stdout`.)
FROM python:3.12-slim

# libmagic1 sharpens content-based MIME detection. file-observer runs WITHOUT it (the
# pure-Python fallback, since v1.3), but this is the widest-coverage install — and small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 \
 && rm -rf /var/lib/apt/lists/*

# Build from the checked-out source (NOT from PyPI) — so the image is reproducible from the
# tag and there is no race with the PyPI-publish workflow on a fresh release (leg-4/Codex).
# Install with the optional specialists: OLE2 (.msg/.doc/.xls/.ppt), object-stream PDF,
# hardened XML, --watch, YAML frontmatter. `.dockerignore` keeps the build context small.
COPY . /src
RUN pip install --no-cache-dir "/src[msg,security,pdf,watch,yaml]" && rm -rf /src

# Run unprivileged. WORKDIR is declared (and created by root) BEFORE the USER switch
# (leg-4/gemini) so it can't fail under rootless/BuildKit.
RUN useradd --create-home --uid 1000 observer
WORKDIR /data
USER observer

# Default: scan the working dir (mount your data at /data) and print the manifest to stdout.
ENTRYPOINT ["file-observer"]
CMD ["--stdout", "."]
