# Security Policy

## Scope

File Observer is an **observation-only** tool. It reads files and emits metadata. It never:
- Executes file content
- Modifies source files
- Opens network connections
- Runs embedded scripts, macros, or code found in scanned files

File Observer does not execute file content. Its attack surface is limited to parsing. A malformed file can cause a specialist to raise an exception or return incorrect metadata. Because the scanner relies on native dependencies (e.g., libmagic), parsing of untrusted input carries residual risk from dependency vulnerabilities. Keep dependencies updated and consider sandboxing when scanning untrusted files.

## Reporting Vulnerabilities

If you discover a security issue, please report it privately:

- **Email:** security@russalo.com
- **Do not** open a public GitHub issue for security vulnerabilities

We will acknowledge receipt within 48 hours and provide an initial assessment within 7 days.

## Dependency Security

| Dependency | Role | Risk mitigation |
|---|---|---|
| `python-magic` / `libmagic` | MIME detection | Read-only, no execution. Fallback to extension-based detection if unavailable. |
| `chardet` | Encoding detection | Read-only. Fallback to encoding cascade if unavailable. |
| `olefile` | OLE2 parsing (.msg/.doc/.xls) | Read-only stream access. Files opened via path (not buffer) for OLE2 FAT chain traversal. |
| `defusedxml` | XML parsing | Used when available to block entity expansion attacks. Falls back to stdlib `xml.etree.ElementTree` when not installed (documented risk — entity expansion not mitigated in fallback mode). |
| `PyYAML` | Frontmatter parsing | `safe_load` only. Fallback to string splitting if unavailable. |

## Bounded Observation

All specialist extractors operate within declared bounds:
- **Default sample:** 8KB read from file head
- **OOXML deviation:** 128KB for ZIP-based formats (DOCX, XLSX) — declared, bounded
- **OLE2 deviation:** full file via path for .msg/.doc/.xls — declared, bounded by file size on disk
- **ZIP traversal:** path components validated against traversal attacks (`_is_safe_zip_entry`), decompressed size capped at 1MB (`_safe_zip_read`)

## Safety Flags

The scanner detects structural indicators that may represent security concerns:
- `has_javascript` — PDF contains JavaScript markers
- `has_macros` — DOCX contains VBA macro binary
- `has_ole_objects` — RTF contains embedded OLE objects
- `has_external_references` — XML contains external entity declarations

These are **observations, not assessments**. The scanner reports what it sees. Consumers apply their own threat model.

## Supported Versions

| Version | Supported |
|---|---|
| 0.11.x | Yes |
| 0.10.x | Until 0.11 ships |
| < 0.10 | No |
