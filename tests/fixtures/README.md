# Test Fixtures

This directory contains sample files for testing the scanner. The included fixtures are **representative examples** covering the supported file types and common edge cases. They use generic, public-domain content.

## What's included

- `sample_*` — Clean replacement fixtures for each major file type (PNG, PDF, TXT, MD, DOCX, HTML, CSV, YAML, JSON)
- `csv_*`, `json_*`, `md_*`, `mdx_*` — Generated test data sets with construction domain content
- `edge_cases/` — Synthetic files testing anomalies, security scenarios, and format edge cases
- `rtf/` — RTF and nested binary format fixtures (PDF, DOCX within subdirectories)
- `text/` — Text and YAML fixture sets

## Contributing your own fixtures

If you're contributing to the scanner, **add your own test files** that reflect your use case. The included fixtures cover the baseline, but real-world data always has surprises.

Guidelines:
- Do not commit files containing personal information, credentials, or proprietary content
- Synthetic or public-domain files only
- Name files descriptively (e.g., `sample_invoice.pdf`, not `test1.pdf`)
- Add edge case fixtures to `edge_cases/` with a comment in the generation script explaining what they test

Personal and project-specific fixtures are gitignored — you can add them locally for testing without them appearing in the repository.
