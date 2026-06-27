# file-observer — deterministic file-observation tool.
# Scan a mounted directory, get a JSON manifest on stdout:
#
#   docker run --rm -v "$PWD:/data:ro" ghcr.io/russalo/file-observer > manifest.json
#
# (the default command is `--stdout .`, so it scans the mounted /data and prints the
# manifest; pass your own args to override, e.g. `… ghcr.io/russalo/file-observer /data --specialists --stdout`.)
FROM python:3.12-slim

# libmagic1 sharpens content-based MIME detection. file-observer runs WITHOUT it (the
# pure-Python fallback, since v1.3), but this is the widest-coverage install — and small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 \
 && rm -rf /var/lib/apt/lists/*

# Install the published package with the optional specialists: OLE2 (.msg/.doc/.xls/.ppt),
# object-stream PDF, hardened XML, --watch, and YAML frontmatter. FO_VERSION pins the build
# to a release (the publish workflow passes the tag); unset = latest on PyPI.
ARG FO_VERSION=
RUN pip install --no-cache-dir "file-observer[msg,security,pdf,watch,yaml]${FO_VERSION:+==$FO_VERSION}"

# Run unprivileged.
RUN useradd --create-home --uid 1000 observer
USER observer
WORKDIR /data

# Default: scan the working dir (mount your data at /data) and print the manifest to stdout.
ENTRYPOINT ["file-observer"]
CMD ["--stdout", "."]
