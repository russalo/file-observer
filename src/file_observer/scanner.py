"""
scanner.py — File Observer

Observation layer for document pipelines. Recursively discovers files,
extracts metadata and signals, emits a deterministic JSON manifest.

    Package:    file_observer
    Version:    1.22.1
    Schema:     1.13
    Python:     >= 3.12
    Spec:       docs/v1.22.0_RFC_Specification.md (current)
    Repository: https://github.com/russalo/file-observer

Design pillars:
    - Capability-locked determinism (ScanContext)
    - Signal layering (raw / derived / semantic-local)
    - Structured provenance (per-field derivation map)
    - Bounded observation (sample_size default 8KB, deviations declared)

Domains are products. Subdomains are responsibilities. Paths are capabilities.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from fnmatch import fnmatch
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
import json
import mimetypes
import os
import platform
import re
import io
import struct
import sys
import zlib
import uuid

try:
    import chardet
except ImportError:
    chardet = None  # type: ignore[assignment]

try:
    import magic
except ImportError:
    magic = None  # type: ignore[assignment]

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    import olefile
except ImportError:
    olefile = None  # type: ignore[assignment]

try:
    import pypdf  # v1.8: optional PDF parser (tier 1) for object-stream page_count/Info
except ImportError:
    pypdf = None  # type: ignore[assignment]

try:
    import tomllib
except ImportError:
    tomllib = None  # type: ignore[assignment]

try:
    from defusedxml.ElementTree import fromstring as xml_fromstring
    _defusedxml_available = True
except ImportError:
    from xml.etree.ElementTree import fromstring as xml_fromstring
    _defusedxml_available = False


SCANNER_VERSION = "1.22.1"
LOGIC_VERSION = "1.12.1"   # v1.22.1 — `.eml` MIME-guard relaxation: accept text/plain & text/html for .eml (libmagic types body-dominated mail as text, not message/rfc822, so the email specialist was wrongly skipped); extension-gated so a lying text `.msg` stays distrusted. Same class as v1.15.2. Prior 1.12.0 = v1.22.0 — content-aware recognition extended to BINARY: unsupported_extension fires ONLY when content didn't identify the file (octet-stream / extension-fallback / unreadable), NOT when identified-but-no-specialist. Recognition-only, no new extraction. supported counter now single-source (not-flagged AND not-stat-failed). Prior 1.11.0 = v1.21.0 — content-aware recognition (Option B) for TEXT: same diagnostic, text-only (text/* or known text-app MIME); supported/unsupported counters shifted. Prior 1.10.0 = v1.20.0 — video.creation_date_qt (Apple QuickTime creationdate key, capture moment WITH timezone, separate from mvhd creation_date — observe-don't-reconcile). Prior 1.9.0 = v1.19.0 — human-readable summary refresh: _build_summary surfaces provenance/capture-metadata/named-safety-flags/preservation + comments on ambiguity (the summary string feeds manifest_checksum). + new --schema --format summary (prose self-description, separate surface). Prior 1.8.0 — video capture device + GPS-presence: make/model (Apple QuickTime keys via moov→meta→keys/ilst) + gps_present/gps_source (location.ISO6709, presence not coordinates) → geotagged fires for video. New extraction + safety_flag routing. Prior 1.7.0 = v1.17.0 video container half.
SCHEMA_VERSION = "1.13"   # unchanged in v1.21 (recognition is LOGIC, no new field). v1.20.0 — new field video.creation_date_qt (additive). Prior 1.12 = v1.18.0 — video namespace gains make/model/gps_present/gps_source (additive); geotagged description broadens image→image+video

# v1.5 PDF specialist read sizes. MARKER_BUDGET is the head+tail window used for
# text/image markers (text_detected AND requires_vision — kept identical across
# both tiers so they can't contradict each other). FULL_READ_CAP bounds the
# whole-file read used for page_count + /Info, so the root page tree and trailer
# Info are found wherever they sit (not just within a tail window).
PDF_MARKER_BUDGET = 131072
PDF_FULL_READ_CAP = 67108864  # 64 MB; larger PDFs fall back to head+tail

# v1.7 structural-anchor reader. A PDF keeps its index at the file END: `startxref`
# → cross-reference section → trailer (/Root, /Info, /Prev). Follow the pointer to
# the exact region instead of scanning a window (v1.5). Bounds: cap the /Prev chain
# (incremental updates) and per-object reads so a malformed file can't run away.
PDF_XREF_PREV_HOPS = 32          # max incremental-update revisions to follow
PDF_ANCHOR_OBJ_CAP = 65536       # bytes read per resolved object (dict region)
PDF_STARTXREF_TAIL = 2048        # bytes of file tail scanned for the last `startxref`
PDF_INFLATE_CAP = 67108864       # 64 MB cap on a single decompressed PDF stream —
                                 # bounds a decompression bomb (a small flate stream
                                 # that expands to GBs); legit xref/ObjStm are far
                                 # smaller. Same discipline as _ZIP_MAX_DECOMPRESS.
# Declared structural anchors, keyed off the v1.3 format identification. PDF is the
# v1.7 adopter; ZIP/OLE2 are documented as already-structural (zipfile finds the
# EOCD, olefile walks the FAT) — no behavior change to them in v1.7.
STRUCTURAL_ANCHORS: dict[str, str] = {
    "pdf": "trailer_pointer",   # startxref → xref/trailer (v1.7, followed)
    "zip": "eocd",              # end-of-central-directory (zipfile already follows)
    "ole2": "fat",              # FAT sector chains (olefile already walks)
}


# v0.8: register markdown extensions in stdlib mimetypes so that when libmagic
# is unavailable, the extension-fallback path in detect_mime() returns a real
# text MIME type for .md / .mdx instead of None → application/octet-stream.
# Without this, .mdx files in a no-libmagic environment would be marked
# binary, skip the text decode, and never get chatlog detection.
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/markdown", ".mdx")
mimetypes.add_type("application/jsonl", ".jsonl")
# v1.15: stdlib mimetypes doesn't know .toml — without this, the extension-fallback
# tier (no-libmagic path, e.g. Windows) returns octet-stream → the file is treated as
# BINARY (no preview/structural/toml-keys). Registered as text/plain (NOT the IANA
# application/toml): libmagic reads toml as text/plain, so text/plain keeps
# mime_analysis.matches_extension True — application/toml would make every .toml a
# false content-vs-extension mismatch on libmagic systems. extension_mime feeds
# guess_type, so this is the deliberate, correct cross-platform reading.
mimetypes.add_type("text/plain", ".toml")
# v1.15: stdlib mimetypes knows .yaml/.yml on Linux (application/yaml) but NOT on
# macOS (returns None) — a real determinism wart the OS matrix surfaced. Pin the
# value Linux already produces so extension_mime is identical across platforms
# (no-op on Linux; fills the macOS null). Matches the canonical IANA type.
mimetypes.add_type("application/yaml", ".yaml")
mimetypes.add_type("application/yaml", ".yml")
# v1.15: Windows stdlib mimetypes doesn't know the Office formats (returns None for
# .xlsx etc.) while Linux does — another extension_mime determinism wart the OS matrix
# surfaced. Pin the canonical IANA values Linux already produces (no-op on Linux; fills
# the macOS/Windows nulls) so a supported extension always has an extension_mime.
mimetypes.add_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")
mimetypes.add_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")
mimetypes.add_type("application/vnd.ms-excel", ".xls")
mimetypes.add_type("application/msword", ".doc")
mimetypes.add_type("application/rtf", ".rtf")
# v1.15.1: HEIC/HEIF/AVIF — stdlib mimetypes may not know them on every platform /
# Python version (extension_mime null where it doesn't). Pin the canonical types
# deterministically across OSes, matching the
# brand→MIME sniff (heic→image/heic, generic heif/mif1/msf1→image/heif, avif→image/avif)
# so a recognized image extension always has an extension_mime.
mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")
mimetypes.add_type("image/avif", ".avif")


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".mdx", ".pdf", ".docx", ".rtf", ".csv", ".json", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".toml", ".png", ".msg",
    ".jpg", ".jpeg", ".css", ".vx", ".eml", ".xlsx",
    ".doc", ".xls", ".jsonl",
    ".heic", ".heif", ".avif",   # v1.16: image EXIF specialist (recognized since v1.15.1)
    ".mp4", ".mov", ".m4v",      # v1.17: video container specialist (ISOBMFF)
}

HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_\-/]+)")
HEX_COLOR_RE = re.compile(r"^[0-9a-fA-F]{3,8}$")
TAG_STOP_WORDS = {"tags", "tag", "hashtag", "hashtags"}
CODE_STRIP_RE = re.compile(
    r"```.*?```"           # fenced code blocks
    r"|<code>.*?</code>"   # HTML code elements
    r"|`[^`]+`",           # inline code spans
    re.DOTALL,
)
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
FRONTMATTER_OPEN_RE = re.compile(r"\A---\r?\n", re.DOTALL)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f]")
ASSET_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FILENAME_DATE_RE = re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})")
HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# v0.8 chatlog detection — see docs/v0.8.0_RFC_Specification.md §2.3
# Speaker label pattern: line starts with a capitalized identifier, colon, space.
# The 16-char cap on the identifier rules out runaway false positives on prose
# that happens to start with `Word: ...` while still catching real speaker
# labels like `Assistant:`, `User:`, `DM:`, `Russell:`, `Player_2:`.
CHATLOG_SPEAKER_LABEL_RE = re.compile(r"^([A-Z][a-zA-Z0-9_]{0,15}):\s", re.MULTILINE)
# Section divider activation: a line containing 3+ dashes with only whitespace
# around it. Matches the exact wording of spec §2.3 rule 3 ("3+ `---` section
# dividers"). Other divider characters (`===`, `***`, `###`) are captured
# by the EXTRACTION regex below when reporting section_marker_styles, but
# do NOT participate in content-based detection activation.
CHATLOG_SECTION_DIVIDER_RE = re.compile(r"^-{3,}\s*$", re.MULTILINE)
# Markdown H3 header activation: line-anchored so that inline mentions of
# `### ` in prose or code blocks do not falsely trigger detection. Spec §2.3
# rule 2 says "3+ `###` headers in the sample"; a header is a line, not a
# substring. Prose containing the characters `### ` inline does not count.
CHATLOG_H3_HEADER_RE = re.compile(r"^### ", re.MULTILINE)
# v1.4.0: content-shape detection. Captures label + post-colon CONTENT (the
# label regex above captures only the label). A speaker turn is an *utterance*
# (a phrase); a data/header/config label's value is *atomic*. utterance_ratio
# over these lines is the v1.4 content-shape gate (RFC §2) layered over the
# count rule. NOTE: the inter-token class is `[ \t]+` (HORIZONTAL whitespace),
# NOT `\s+` — `\s` matches newlines, so `\s+` would let an empty-content label
# (`Foo: \n`) swallow the *next* line as its content and drop that line's own
# label (review finding 2026-06-02). Empty content stays paired to its label.
CHATLOG_LABEL_CONTENT_RE = re.compile(r"^([A-Z][a-zA-Z0-9_]{0,15}):[ \t]+(.*)$", re.MULTILINE)
# §3.2 structure vote-against: a dense run of VERSION-TAGGED section headers is
# the signature of a changelog / release-notes, NOT a transcript. 2+ vote against.
# Tightened (review 2026-06-02): match only version-TAG shapes — bracketed
# (`## [1.2.0] - 2026-03-01`), `v`-prefixed (`## v1.2.0`), or 3-part semver
# (`## 1.2.3`). Bare 2-part numbered headings (`## 2.1`) and ISO-dated journal
# headers (`## 2024-01-01 session`) are NOT versions and must NOT vote against —
# a dated journal of dialogue is a legitimate chatlog (the dated-CHANGELOG case
# is already caught by the FP-lexicon dominance rule via its `Added:`/`Fixed:`).
CHATLOG_VERSION_HEADER_RE = re.compile(
    r"^#{1,6}[ \t]*(?:\[v?\d+\.\d+[^\]]*\]|v\d+\.\d+|\d+\.\d+\.\d+)", re.MULTILINE)
# v0.8 chatlog extraction — used by _extract_chatlog_metadata. The detection
# regexes above test for the presence of patterns; these capture them.
# Single-character pure-divider line: same character class repeated 3+ times.
# Captured group is the divider character; styles are normalized to a 3-char
# representation in the output (e.g. "---", "===", "***", "###").
CHATLOG_PURE_DIVIDER_RE = re.compile(r"^([-=*#])\1{2,}\s*$", re.MULTILINE)
# Markdown header line: 1-6 hashes followed by whitespace then text.
# Captured group is the hashes; styles are output with a trailing space
# (e.g. "# ", "## ", "### ") to match the spec example in §2.4.
CHATLOG_MD_HEADER_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)
# Capitalized tokens: an uppercase letter followed by 2+ word chars (length 3+
# total). The leading-uppercase + length-3-minimum filter is per spec §2.6.
CHATLOG_CAPITALIZED_TOKEN_RE = re.compile(r"\b[A-Z][a-zA-Z0-9_]{2,}\b")
# Lowercase word tokens for vocabulary size estimation. Operates on
# text.lower(), so this catches all word-shaped tokens regardless of original
# case, including single-character tokens like "a" and "i". Gives a richer
# "vocabulary size" signal than only counting tokens that were originally
# lowercase and fewer undercounts on natural prose.
CHATLOG_LOWERCASE_WORD_RE = re.compile(r"\b[a-z][a-z0-9]*\b")
# Reference token patterns (per spec §2.5).
CHATLOG_AT_MENTION_RE = re.compile(r"@[a-zA-Z0-9_]+")
CHATLOG_WIKI_LINK_RE = re.compile(r"\[\[.+?\]\]")
CHATLOG_URL_RE = re.compile(r"https?://\S+")

TECHNOLOGY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # CSS frameworks
    ("tailwind", re.compile(r'\bclass="[^"]*\b(?:bg-(?:gray|red|blue|green|white|black|slate|zinc|neutral|stone|amber|yellow|emerald|teal|cyan|sky|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}|text-(?:xs|sm|base|lg|xl|2xl)|rounded-(?:sm|md|lg|xl|2xl|full)|shadow-(?:sm|md|lg)|hover:)')),
    ("tailwind", re.compile(r"tailwindcss|tailwind\.css|cdn\.tailwindcss\.com")),
    ("bootstrap", re.compile(r"bootstrap\.min\.(css|js)|cdn\.jsdelivr\.net/npm/bootstrap")),
    ("bootstrap", re.compile(r'\bclass="[^"]*\b(?:btn\s+btn-|container-fluid|col-md-|navbar-)\b')),
    # JS frameworks
    ("react", re.compile(r"\breact-dom\b|data-reactroot|React\.createElement|createRoot")),
    ("vue", re.compile(r"\bv-bind\b|\bv-if\b|\bv-model\b|\bv-show\b|vue\.(?:min\.)?js|createApp")),
    ("alpine", re.compile(r"\bx-data\b|\bx-show\b|\bx-bind\b|\bx-on:")),
    ("htmx", re.compile(r"\bhx-get\b|\bhx-post\b|\bhx-swap\b|\bhx-trigger\b")),
    ("jquery", re.compile(r"\$\(document\)|\$\(['\"]|jquery\.min\.js")),
    ("svelte", re.compile(r"svelte\.(?:min\.)?js|__svelte")),
    ("angular", re.compile(r"\bng-app\b|\bng-model\b|angular\.(?:min\.)?js|\*ngIf")),
    # Charting / visualization
    ("chart.js", re.compile(r"chart\.min\.js|new\s+Chart\(")),
    ("d3", re.compile(r"d3\.min\.js|d3\.select")),
    ("mermaid", re.compile(r"mermaid\.min\.js|mermaid\.initialize")),
    # Infra / config
    ("docker-compose", re.compile(r"^services:\s*$", re.MULTILINE)),
    ("terraform", re.compile(r'\bresource\s+"[^"]+"\s+"[^"]+"')),
    ("ansible", re.compile(r"^\s*-\s+hosts:\s", re.MULTILINE)),
    ("github-actions", re.compile(r"^on:\s.*\bjobs:\s", re.DOTALL)),
    # Fonts / CDN
    ("google-fonts", re.compile(r"fonts\.googleapis\.com")),
]

SPECIALIST_TOOLS: dict[str, str] = {
    ".pdf": "pdf_extraction",
    ".docx": "document_extraction",
    ".doc": "document_extraction",
    ".rtf": "document_extraction",
    ".png": "image_structure",
    ".jpg": "image_structure",
    ".jpeg": "image_structure",
    ".heic": "image_structure",
    ".heif": "image_structure",
    ".avif": "image_structure",
    ".mp4": "video_structure",
    ".mov": "video_structure",
    ".m4v": "video_structure",
    ".msg": "email_envelope",
    ".eml": "email_envelope",
    ".xlsx": "spreadsheet_structure",
    ".xls": "spreadsheet_structure",
}

# Error code constants
ERR_UNIVERSAL_STAT_FAILED = "universal_stat_failed"
ERR_UNIVERSAL_READ_FAILED = "universal_read_failed"   # v1.8.1: open/read failed (permissions, etc.)
ERR_UNSUPPORTED_EXTENSION = "unsupported_extension"
ERR_MIME_TYPE_FALLBACK = "mime_type_fallback"
ERR_BASELINE_DECODE_FAILED = "baseline_decode_failed"
ERR_SPECIALIST_PROBE_FAILED = "specialist_probe_failed"
ERR_JSON_PARSE_FAILED = "json_parse_failed"
ERR_PDF_ENCRYPTION_UNSUPPORTED = "pdf_encryption_unsupported"  # v1.12: AES decrypt failed (cryptography missing)
ERR_XML_PARSE_FAILED = "xml_parse_failed"    # v1.12.2: was an inline literal; centralized
ERR_TOML_PARSE_FAILED = "toml_parse_failed"  # v1.12.2: was an inline literal; centralized
# v1.12 round-2 leg-1 #11/#12: error codes that count as a specialist-stage
# FAILURE for aggregate counters (ScanQuality.specialist_failures,
# per_directory specialist_failures, specialist_stats[tool].failed).
# Centralised so a future specialist-failure code is one edit away from being
# observable in every counter.
SPECIALIST_FAILURE_CODES = frozenset({ERR_SPECIALIST_PROBE_FAILED, ERR_PDF_ENCRYPTION_UNSUPPORTED})

# v1.13: ERROR_CODES — the complete error-code surface, enumerable from one
# place for `--schema`. Each ERR_* constant + a one-line description of what
# emits it. Guard test (test_v1_13) asserts every ErrorRecord code is a key
# here AND that no inline literal escapes (the v1.12.2 guard, AST-based).
ERROR_CODES: dict[str, str] = {
    ERR_UNIVERSAL_STAT_FAILED: "file stat() failed (deleted mid-scan / permissions / TOCTOU)",
    ERR_UNIVERSAL_READ_FAILED: "file open/read failed after stat succeeded (permissions, handle errors)",
    ERR_UNSUPPORTED_EXTENSION: "could not identify the file — extension not in SUPPORTED_EXTENSIONS AND content not identified (octet-stream / extension-fallback / unreadable); v1.22 content-aware, text or binary",
    ERR_MIME_TYPE_FALLBACK: "MIME detection fell back to the extension guess (libmagic absent/null)",
    ERR_BASELINE_DECODE_FAILED: "text decoding failed across the full charset cascade",
    ERR_SPECIALIST_PROBE_FAILED: "a specialist probe or extraction raised / returned null",
    ERR_JSON_PARSE_FAILED: "JSON parse error during the .json specialist probe",
    ERR_PDF_ENCRYPTION_UNSUPPORTED: "AES-encrypted PDF and the cryptography package is absent",
    ERR_XML_PARSE_FAILED: "XML parse failed during structural key extraction",
    ERR_TOML_PARSE_FAILED: "TOML parse failed during structural key extraction",
}

# v1.13: SAFETY_FLAGS — the complete safety_flags vocabulary, enumerable from
# one place for `--schema`. Structural indicators, NOT threat assessments
# (see PUBLIC_CONTRACT.md §1.7). Guard test asserts detect_safety_flags emits
# only keys present here.
SAFETY_FLAGS: dict[str, str] = {
    "has_javascript": "PDF contains /JS or /JavaScript markers",
    "has_macros": "DOCX contains a vbaProject.bin (requires enable_specialists)",
    "has_ole_objects": "RTF contains \\objemb or \\objlink",
    "has_external_references": "XML contains <!ENTITY with SYSTEM or PUBLIC",
    "extraction_permission_bypassed": "owner-locked encrypted PDF: EXTRACT permission not set but metadata extracted anyway (v1.12)",
    "geotagged": "image EXIF (GPS IFD) or video (ISO-6709 location box) carries location; presence only, coordinates NOT extracted (v1.16 image, v1.18 video)",
}

# v1.13: PROVENANCE_TRIGGERS — the complete signal_provenance trigger surface,
# enumerable from one place for `--schema`. Each trigger → {layer, method,
# description}. This is the registry that replaces the scattered inline
# trigger= literals as the source of truth (the literals remain at the emit
# sites for readability; the AST guard test asserts every literal trigger
# value is a key here, and the corpus cross-check asserts the dynamically-
# computed triggers are registered too). Same "enumerable from one place"
# discipline as ERROR_CODES + SAFETY_FLAGS.
PROVENANCE_TRIGGERS: dict[str, dict[str, str]] = {
    # MIME detection (detect_mime)
    "libmagic":                 {"layer": "raw",     "method": "detect_mime",      "description": "MIME from libmagic (primary tier)"},
    "magic_signature_fallback": {"layer": "derived", "method": "detect_mime",      "description": "MIME from the pure-Python magic-signature sniff (libmagic absent/null)"},
    "extension_fallback":       {"layer": "derived", "method": "detect_mime",      "description": "MIME guessed from the extension (both content tiers failed)"},
    # MIME-vs-extension analysis
    "mismatch":                 {"layer": "derived", "method": "analyze_mime",     "description": "detected MIME differs from the extension-implied MIME"},
    "match":                    {"layer": "derived", "method": "analyze_mime",     "description": "detected MIME matches the extension-implied MIME"},
    # specialist tool registry routing
    "registry_match":           {"layer": "derived", "method": "specialist_tools_registry", "description": "extension has a registered specialist tool"},
    "registry_none":            {"layer": "derived", "method": "specialist_tools_registry", "description": "extension has no registered specialist tool"},
    # chatlog content detection
    "content_pattern_match":    {"layer": "derived", "method": "_detect_chatlog_pattern", "description": "content matched the chatlog detection rules"},
    "content_pattern_none":     {"layer": "derived", "method": "_detect_chatlog_pattern", "description": "content did not match the chatlog detection rules"},
    "chatlog_activation":       {"layer": "derived", "method": "content_detected_specialist", "description": "chatlog specialist activated on a content-detected match"},
    # baseline text eligibility
    "text_eligible":            {"layer": "derived", "method": "_extract_reference_tokens", "description": "file routed into the baseline text-analysis tier"},
    # structural extraction
    "markdown_h1":              {"layer": "derived", "method": "extract_md_title",  "description": "title from a Markdown H1"},
    "html_title_tag":           {"layer": "derived", "method": "extract_html_title", "description": "title from an HTML <title> tag"},
    "yaml_line_parse":          {"layer": "derived", "method": "extract_yaml_keys", "description": "document keys from YAML line parsing"},
    "json_loads":               {"layer": "derived", "method": "extract_json_keys", "description": "document keys from json.loads"},
    "xml_etree":                {"layer": "derived", "method": "extract_xml_keys",  "description": "document keys from XML ElementTree"},
    "tomllib":                  {"layer": "derived", "method": "extract_toml_keys", "description": "document keys from tomllib"},
    # specialist metadata extraction (dynamic: method is f"_{ext}_specialist",
    # trigger chosen per is_deviation / null — method varies by extension)
    "bounded_sample":           {"layer": "derived", "method": "_<ext>_specialist", "description": "specialist field extracted within the bounded sample"},
    "bounded_deviation":        {"layer": "derived", "method": "_<ext>_specialist", "description": "specialist field extracted via a declared deviation read (e.g. ZIP central directory)"},
    "missing_from_bounds":      {"layer": "derived", "method": "_<ext>_specialist", "description": "specialist field not observed within bounds (null, not absent)"},
    "bounded_text":             {"layer": "derived", "method": "_extract_chatlog_metadata", "description": "specialist text field extracted within bounds"},
    "email_body_crosscut":      {"layer": "derived", "method": "_extract_chatlog_metadata", "description": "email body cross-cut through the chatlog vector"},
    # binary detection (detect_binary)
    "unicode_bom":              {"layer": "derived", "method": "detect_binary",    "description": "treated as text via a UTF-16/UTF-32 BOM at offset 0"},
    "nul_byte":                 {"layer": "derived", "method": "detect_binary",    "description": "binary: NUL byte in the sample"},
    "mime_prefix_binary":       {"layer": "derived", "method": "detect_binary",    "description": "binary: image/ audio/ video/ MIME prefix"},
    "known_binary_mime":        {"layer": "derived", "method": "detect_binary",    "description": "binary: a known-binary MIME type"},
    "text_ratio_failure":       {"layer": "derived", "method": "detect_binary",    "description": "binary: printable-character ratio below threshold"},
    "text_ratio_ok":            {"layer": "derived", "method": "detect_binary",    "description": "text: printable-character ratio above threshold"},
    # requires_vision (detect_requires_vision)
    "image_mime":               {"layer": "derived", "method": "detect_requires_vision", "description": "requires vision: image MIME"},
    "pdf_text_detected":        {"layer": "derived", "method": "detect_requires_vision", "description": "PDF with detectable text — does NOT require vision"},
    "pdf_image_only":           {"layer": "derived", "method": "detect_requires_vision", "description": "PDF with image markers and no text — requires vision"},
    "pdf_no_markers":           {"layer": "derived", "method": "detect_requires_vision", "description": "PDF with no text or image markers in the window"},
    # encoding (decode_text)
    "chardet_confident":        {"layer": "derived", "method": "decode_text",      "description": "encoding from chardet at confidence >= 0.5"},
    "cascade_utf_8":            {"layer": "derived", "method": "decode_text",      "description": "encoding from the utf-8 cascade step"},
    "cascade_utf_8_sig":        {"layer": "derived", "method": "decode_text",      "description": "encoding from the utf-8-sig cascade step"},
    "cascade_cp1252":           {"layer": "derived", "method": "decode_text",      "description": "encoding from the cp1252 cascade step"},
    "cascade_latin_1":          {"layer": "derived", "method": "decode_text",      "description": "encoding from the latin-1 cascade step"},
    "replace":                  {"layer": "derived", "method": "decode_text",      "description": "encoding cascade exhausted — utf-8 with errors=replace"},
    # shared / multi-method
    "not_applicable":           {"layer": "derived", "method": "(various)",        "description": "the derivation does not apply to this file (e.g. binary skips encoding; non-PDF skips vision)"},
}

BINARY_MIME_PREFIXES = ("image/", "audio/", "video/")
BINARY_MIME_TYPES = {
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/octet-stream",
}

TEXT_APP_MIMES = {
    "application/json",
    "application/rtf",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
}

# v1.21: content-aware recognition (RFC §6 = Option B). A file is RECOGNIZED (not
# `unsupported_extension`) when its CONTENT is text — `text/*` or a known structured-text
# application type — even if its extension isn't in SUPPORTED_EXTENSIONS. So
# `unsupported_extension` means "couldn't identify it", not "extension not in our list".
# (libmagic types source as text/x-script.python / text/x-java / text/x-c …, and JS/TS/SVG
# as the application/* + image/svg+xml entries below.)
RECOGNIZED_TEXT_APP_MIMES = TEXT_APP_MIMES | {
    "application/javascript",
    "application/x-javascript",
    "application/ecmascript",
    "image/svg+xml",
    # libmagic types a zero-byte file `inode/x-empty` — a POSITIVE identification, not
    # "unidentifiable". An empty file decodes cleanly as the empty string (trivially text,
    # never binary), so it's recognized, not flagged. (e.g. empty `__init__.py` / `py.typed`.)
    "inode/x-empty",
}


def _is_recognized_text(mime_type: str | None) -> bool:
    """v1.21: True when the content MIME marks the file as text (so it's recognized, not
    `unsupported_extension`). Content-first; null/unknown → False (genuinely unidentified)."""
    return bool(mime_type) and (mime_type.startswith("text/")
                                or mime_type in RECOGNIZED_TEXT_APP_MIMES)

# Unicode byte-order marks. Order matters: UTF-32 LE (ff fe 00 00) shares its
# first two bytes with UTF-16 LE (ff fe), so 4-byte BOMs MUST be checked first.
UNICODE_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
)


def _detect_unicode_bom(sample: bytes) -> str | None:
    """Return the Unicode encoding name if `sample` begins with a BOM, else None."""
    for bom, enc in UNICODE_BOMS:
        if sample.startswith(bom):
            return enc
    return None


@dataclass
class ProvenanceEntry:
    layer: str          # "raw", "derived", or "semantic_local"
    method: str         # stable token for the logic block
    trigger: str        # specific condition that fired
    inputs: list[str] = field(default_factory=list)
    detail: dict[str, Any] | str | None = None


@dataclass
class ScanContext:
    logic_version: str
    scanner_version: str
    python_version: str
    platform: str
    dependencies: dict[str, dict[str, Any]]


@dataclass
class ErrorRecord:
    code: str
    message: str
    stage: str
    # v1.2: optional structured diagnostic (stable, promoted v1.10). Default None so all
    # existing ErrorRecord construction is unaffected.
    detail: dict[str, Any] | None = None


@dataclass
class FrontmatterRecord:
    exists: bool = False
    keys: list[str] = field(default_factory=list)
    raw: str | None = None


@dataclass
class MimeAnalysisRecord:
    detected_mime: str | None
    extension_mime: str | None
    matches_extension: bool


@dataclass
class StructuralRecord:
    title: str | None = None
    heading_structure: list[str] = field(default_factory=list)
    csv_headers: list[str] = field(default_factory=list)
    document_keys: list[str] = field(default_factory=list)
    technology_hints: list[str] = field(default_factory=list)
    filename_date: str | None = None


@dataclass
class FileRecord:
    path: str
    filename: str
    extension: str
    mime_type: str
    size_bytes: int
    created_at: str | None
    modified_at: str
    checksum_sha256: str
    stage_folder: str
    directory_depth: int
    encoding: str | None
    is_binary: bool
    requires_vision: bool
    requires_specialist_tool: bool
    specialist_tool: str | None
    sidecar_exists: bool
    frontmatter: FrontmatterRecord
    tags: list[str]
    asset_matches: list[str]
    content_preview: str | None
    structural: StructuralRecord
    mime_analysis: MimeAnalysisRecord
    specialist_metadata: dict[str, Any] | None
    file_signature: dict[str, Any] | None = None
    format_signatures: list[dict[str, Any]] = field(default_factory=list)
    is_polyglot: bool = False
    # v0.8: content-detected chatlog flag (set when text patterns suggest
    # conversational or document-evolution structure). Always present, runs
    # even when enable_specialists=False because detection is cheap.
    is_chatlog: bool = False
    # v0.9: reference token counts across seven subcategories. Present on
    # every text-decoded file (null on binary). See spec §3.2.
    reference_tokens: dict[str, int] | None = None
    # v0.10: filename pattern detection — boolean per subcategory, every file
    filename_patterns: dict[str, bool] | None = None
    # v1.10 (provisional): format-preservation signal — {format_obsolescence, migration_recommended}
    preservation: dict[str, Any] | None = None
    safety_flags: list[str] = field(default_factory=list)
    signal_provenance: dict[str, Any] = field(default_factory=dict)
    errors: list[ErrorRecord] = field(default_factory=list)


@dataclass
class ScanMeta:
    scan_id: str
    generated_at: str
    source_dir: str
    config: dict[str, Any]


@dataclass
class ScanStats:
    total_files: int
    supported_files: int
    unsupported_files: int
    text_files: int
    binary_files: int
    requires_vision: int
    requires_specialist_tool: int


@dataclass
class RoutingSummary:
    baseline_ready: int
    binary_only: int
    requires_vision: int
    requires_specialist_tool: int


@dataclass
class DeltaRecord:
    previous_scan_id: str
    previous_manifest_checksum: str | None
    added: list[str]
    modified: list[str]
    unchanged: list[str]
    removed: list[str]
    rescan_candidates: list[str] = field(default_factory=list)


@dataclass
class VectorRecord:
    """One entry in vectors_collected[]. Represents a vector that ran in a scan."""
    vector_id: str
    method_version: int
    scope: str  # "file" or "corpus"
    rules_hash: str
    static_tuning_hash: str
    dynamic_tuning_hash: str | None  # Reserved, null in v0.9
    dictionary_id: str | None  # Reserved, null in v0.9
    identity_digest: str
    applied_to_count: int
    summary: dict[str, Any]


def compute_vector_identity_digest(
    vector_id: str,
    method_version: int,
    rules_hash: str,
    static_tuning_hash: str,
    dynamic_tuning_hash: str | None = None,
    dictionary_id: str | None = None,
) -> str:
    """Compute SHA-256 identity digest per v0.9 spec §2.4.

    Preimage: vector_id|method_version|rules_hash|static_tuning_hash|dynamic_tuning_hash|dictionary_id
    with null represented as the literal string "null".
    """
    preimage = "|".join([
        vector_id,
        str(method_version),
        rules_hash,
        static_tuning_hash,
        dynamic_tuning_hash or "null",
        dictionary_id or "null",
    ])
    return sha256(preimage.encode("utf-8")).hexdigest()


def compute_rules_hash(rules_definition: str) -> str:
    """Compute SHA-256 hash of a vector's rule set definition."""
    return sha256(rules_definition.encode("utf-8")).hexdigest()


def compute_tuning_hash(tuning: dict[str, Any]) -> str:
    """Compute SHA-256 hash of a vector's static tuning configuration."""
    canonical = json.dumps(tuning, sort_keys=True, ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


class VectorRegistry:
    """Collects vectors that ran during a scan and produces vectors_collected[]."""

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    def register(self, record: VectorRecord) -> None:
        self._records[record.vector_id] = record

    def to_list(self) -> list[dict[str, Any]]:
        """Return vectors_collected[] sorted alphabetically by vector_id."""
        return [asdict(self._records[vid]) for vid in sorted(self._records)]


@dataclass
class ScanQuality:
    total_files: int
    clean_files: int
    degraded_files: int
    error_files: int
    mime_mismatches: int
    polyglots_detected: int
    specialist_failures: int
    unsupported_extensions: int
    safety_flags: int
    # v0.8: number of files where the chatlog content-detection rules
    # fired (is_chatlog == True). Defaulted so older code paths and
    # tests that construct ScanQuality without this field still work.
    chatlog_files: int = 0
    # v0.9: per-directory aggregation — one entry per top-level subdirectory
    per_directory_summary: list[dict[str, Any]] = field(default_factory=list)
    # v1.1 (stable, promoted v1.10): duplicate detection — files grouped by identical
    # checksum_sha256 (count >= 2). Each cluster: {checksum_sha256, size_bytes,
    # count, paths}. Sorted by count desc then checksum asc; paths sorted asc.
    duplicate_clusters: list[dict[str, Any]] = field(default_factory=list)
    duplicate_cluster_count: int = 0
    redundant_file_count: int = 0  # sum(count - 1) — copies a dedup pass could remove
    # v1.1 (stable, promoted v1.10): per-specialist quality — {tool: {attempted, succeeded,
    # failed}}, keyed by semantic tool name, sorted keys. Empty when specialists
    # are disabled. The aggregate specialist_failures (above) is retained.
    specialist_stats: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class ScanManifest:
    schema_version: str
    context: ScanContext
    meta: ScanMeta
    stats: ScanStats
    quality: ScanQuality
    routing_summary: RoutingSummary
    delta: DeltaRecord | None
    manifest_checksum: str
    manifest_signature: dict[str, str] | None
    files: list[FileRecord]
    # v0.9: vector collection — one entry per vector that ran
    vectors_collected: list[dict[str, Any]] = field(default_factory=list)
    # v0.10: human-readable scan summary — deterministic Markdown text
    summary: str = ""


# Extension-to-specialist-namespace mapping
SPECIALIST_NAMESPACE: dict[str, str] = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".heic": "image",
    ".heif": "image",
    ".avif": "image",
    ".mp4": "video",
    ".mov": "video",
    ".m4v": "video",
    ".msg": "email",
    ".eml": "email",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".docx": "document",
    ".doc": "document",
    ".rtf": "document",
}

# v1.13: SPECIALIST_FIELDS — the metadata fields each specialist namespace can
# emit, enumerable from one place for `--schema`. Keyed by namespace (the value
# in SPECIALIST_NAMESPACE / CHATLOG_NAMESPACE). This documents the specialist
# output surface for consumers; a guard test asserts every field a specialist
# actually emits on the training corpus is listed here (no undocumented field).
# Fields not observed within bounds come back null (null = not seen, not absent).
SPECIALIST_FIELDS: dict[str, list[str]] = {
    "pdf": [
        "has_text_streams", "encrypted", "xref_type", "page_count", "title",
        "author", "producer", "creator", "creation_date", "pdf_version",
        "text_detected", "sample_text_marker_density", "parser",
    ],
    "image": [
        "width", "height", "bit_depth", "make", "model", "orientation",
        "datetime_original", "gps_present", "xmp_present",
    ],
    "video": ["codec", "duration_s", "width", "height", "creation_date", "creation_date_qt",
              "make", "model", "gps_present", "gps_source"],
    "document": ["title", "author", "word_count", "heading_count", "application"],
    "spreadsheet": ["sheet_names", "header_rows", "format", "application"],
    "email": ["subject", "from", "to", "date", "message_id", "has_attachments",
              "body_chatlog"],  # v0.9 cross-cut: emitted when an email body is chatlog-shaped (v1.13 leg-1 #4)
    "chatlog": [
        "turn_count", "speaker_labels", "speaker_turn_counts",
        "speaker_turn_chars", "alternation", "content_shape",
        "section_marker_count", "section_marker_styles", "avg_turn_chars",
        "max_turn_chars", "min_turn_chars", "reference_tokens",
        "top_capitalized_tokens", "capitalized_token_count",
        "vocabulary_size_estimate",
    ],
}


# v1.14: the PROVISIONAL surface — everything else enumerable in `--schema` is
# STABLE. Sourced from PUBLIC_CONTRACT §2.4; a guard test (test_v1_14) keeps this
# in sync with the contract. v1.14 promoted `pdf.parser`,
# `{document,spreadsheet}.application`, and the `provenance` vector → stable; what
# remains provisional is the chatlog family (alpha-locked, pending the non-count
# redesign) and `preservation` (still gathering value-evidence).
PROVISIONAL_SPECIALIST_FIELDS: frozenset[tuple[str, str]] = frozenset({
    ("chatlog", "content_shape"),
    ("chatlog", "speaker_turn_counts"),
    ("chatlog", "speaker_turn_chars"),
    ("chatlog", "alternation"),
    # v1.21.1: the v1.16 image-EXIF fields are provisional (recent; promotion-pass
    # candidates). They emitted as stable only because they were never registered here
    # — an intake oversight; corrected. The OLD image dimensions (width/height/bit_depth,
    # stable since 0.5) are intentionally NOT listed. Manifest byte-identical (stability
    # lives only in `--schema`, not the manifest).
    ("image", "make"),
    ("image", "model"),
    ("image", "orientation"),
    ("image", "datetime_original"),
    ("image", "gps_present"),
    ("image", "xmp_present"),
    # v1.21.1: the whole `video` namespace is recent (v1.17–1.20) → all provisional
    # (promotion-pass candidates), same intake-oversight correction.
    ("video", "codec"),
    ("video", "duration_s"),
    ("video", "width"),
    ("video", "height"),
    ("video", "creation_date"),
    ("video", "creation_date_qt"),
    ("video", "make"),
    ("video", "model"),
    ("video", "gps_present"),
    ("video", "gps_source"),
})
PROVISIONAL_VECTORS: frozenset[str] = frozenset({"preservation"})
PROVISIONAL_MANIFEST_FIELDS: frozenset[tuple[str, str]] = frozenset({
    ("FileRecord", "preservation"),
    ("FileRecord", "format_signatures"),  # PUBLIC_CONTRACT §2.4 — internal magic scan results
    ("FileRecord", "is_polyglot"),         # PUBLIC_CONTRACT §2.4 — derived from format_signatures
})


def _field_stability(namespace: str, field: str) -> str:
    """v1.14: stability of a specialist-metadata field for `--schema`."""
    return "provisional" if (namespace, field) in PROVISIONAL_SPECIALIST_FIELDS else "stable"


# Magic byte signatures for polyglot/multi-format detection
# (pattern, offset, format_mime) — offset=None means scan entire sample
# v1.3: each entry is (constraints, label) where constraints is a tuple of
# (offset, pattern); ALL must match for the signature to fire. offset is an int
# (anchored) or None (pattern occurs anywhere in the head sample). Tested in
# order — more specific signatures (RIFF sub-types) MUST precede general ones.
# Labels that are valid MIME types (contain "/") are usable by detect_mime's
# pure-Python fallback; the one non-MIME label ("riff_container") is
# format_signatures-only and skipped by _sniff_mime.
MAGIC_SIGNATURES: list[tuple[tuple[tuple[int | None, bytes], ...], str]] = [
    (((0, b"\x89PNG\r\n\x1a\n"),), "image/png"),
    (((0, b"\xff\xd8\xff"),), "image/jpeg"),
    (((None, b"%PDF-"),), "application/pdf"),
    (((0, b"GIF87a"),), "image/gif"),
    (((0, b"GIF89a"),), "image/gif"),
    # RIFF container — sub-types (marker at offset 8) MUST precede the generic
    # RIFF entry below; scan_signatures suppresses the generic when a sub-type
    # matched, so a WAV emits exactly one signature (no false polyglot).
    (((0, b"RIFF"), (8, b"WEBP")), "image/webp"),
    (((0, b"RIFF"), (8, b"WAVE")), "audio/wav"),
    (((0, b"RIFF"), (8, b"AVI ")), "video/x-msvideo"),
    # generic RIFF retained for format_signatures (non-MIME → _sniff_mime skips
    # it). scan_signatures suppresses it when a sub-type above matched, so a
    # known RIFF emits one signature (no false polyglot) and an unknown RIFF
    # (e.g. ACON cursor) still gets a format_signature. Per v1.3.0 RFC §4.
    (((0, b"RIFF"),), "riff_container"),
    # archives / compression
    (((0, b"PK\x03\x04"),), "application/zip"),
    (((0, b"\x1f\x8b"),), "application/gzip"),
    # bzip2: "BZh" + level digit + block magic — the second constraint rules out
    # prose like "BZh is not..." (review: bare "BZh" matched text).
    (((0, b"BZh"), (4, b"1AY&SY")), "application/x-bzip2"),
    (((0, b"\xfd7zXZ\x00"),), "application/x-xz"),
    (((0, b"7z\xbc\xaf\x27\x1c"),), "application/x-7z-compressed"),
    (((0, b"\x28\xb5\x2f\xfd"),), "application/zstd"),
    (((0, b"Rar!\x1a\x07"),), "application/vnd.rar"),
    # images / data
    (((0, b"II*\x00"),), "image/tiff"),
    (((0, b"MM\x00*"),), "image/tiff"),
    (((0, b"SQLite format 3\x00"),), "application/vnd.sqlite3"),
    (((0, b"PAR1"),), "application/vnd.apache.parquet"),
    # OLE2 / documents / executables
    (((0, b"\xd0\xcf\x11\xe0"),), "application/x-ole-storage"),
    (((0, b"{\\rtf"),), "application/rtf"),
    (((0, b"\x7fELF"),), "application/x-elf"),
    (((0, b"%!PS"),), "application/postscript"),
    # media — ISO-BMFF `ftyp` box (offset 4). The brand at offset 8 disambiguates
    # image (HEIC/HEIF/AVIF — incl. the iPhone default photo format) from video
    # (mp4/mov). MORE-SPECIFIC image brands MUST precede the generic ftyp→video/mp4
    # below, or the no-libmagic fallback mislabels every iPhone photo as video/mp4
    # (v1.15 fix; signatures are tested in order).
    (((4, b"ftyp"), (8, b"heic")), "image/heic"),   # HEVC-coded HEIF
    (((4, b"ftyp"), (8, b"heix")), "image/heic"),   # HEVC-coded HEIF (10-bit)
    # v1.15.1: generic HEIF brands report image/heif, NOT image/heic — observe-don't-
    # interpret (the brand doesn't assert HEVC coding, so don't claim it).
    (((4, b"ftyp"), (8, b"heif")), "image/heif"),   # generic HEIF
    (((4, b"ftyp"), (8, b"mif1")), "image/heif"),   # generic HEIF still image
    (((4, b"ftyp"), (8, b"msf1")), "image/heif"),   # HEIF image sequence
    (((4, b"ftyp"), (8, b"avif")), "image/avif"),
    (((4, b"ftyp"), (8, b"avis")), "image/avif"),   # AVIF image sequence
    (((4, b"ftyp"),), "video/mp4"),
    (((0, b"\x1aE\xdf\xa3"),), "video/x-matroska"),
    # ID3v2: require a real major-version byte (2/3/4) so prose like "ID3 tags"
    # (space at offset 3) doesn't match (review).
    (((0, b"ID3\x02"),), "audio/mpeg"),
    (((0, b"ID3\x03"),), "audio/mpeg"),
    (((0, b"ID3\x04"),), "audio/mpeg"),
    (((0, b"fLaC"),), "audio/flac"),
    (((0, b"OggS"),), "audio/ogg"),
]

# MIME types a specialist namespace accepts — skip if mime_type doesn't match
SPECIALIST_MIME_GUARD: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "image": {"image/png", "image/jpeg", "image/gif", "image/webp",
              "image/heic", "image/heif", "image/avif"},
    "video": {"video/mp4", "video/quicktime", "video/x-m4v", "application/mp4",
              "application/octet-stream"},
    "email": {"message/rfc822", "application/vnd.ms-outlook", "application/x-ole-storage", "application/CDFV2"},
    "spreadsheet": {"application/zip", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     "application/vnd.ms-excel", "application/x-ole-storage", "application/CDFV2",
                     "application/vnd.ms-office",  # v1.15.2: libmagic's generic OLE2-office MIME
                     "application/octet-stream"},
    "document": {"application/zip", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "application/msword", "application/x-ole-storage", "text/rtf", "application/rtf",
                 "application/CDFV2", "application/vnd.ms-office",  # v1.15.2: generic OLE2-office
                 "application/octet-stream"},
    # v0.8: chatlog is the first content-detected (not extension-driven)
    # specialist. Its MIME guard accepts text/plain and the markdown variants.
    "chatlog": {"text/plain", "text/markdown", "text/x-markdown", "application/json", "application/jsonl", "application/x-ndjson"},
}

# v1.15.2: MIME types that are TEXT-based (no magic byte signature exists even for a
# genuine file) AND whose specialist self-validates on bad input. For these, an
# extension-derived MIME is trustworthy WITHOUT a corroborating format_signature (a
# BINARY format would have one; its absence is suspicious only for binary formats).
# Gate by the specific MIME, NOT the namespace: `.eml` → message/rfc822 (text, parsed by
# stdlib email.parser, graceful on non-email), but `.msg` → application/vnd.ms-outlook is
# BINARY OLE2 (same `email` namespace) and must STAY distrusted when unsigned — a lying
# text `.msg` would otherwise bypass the guard (leg-2/Gemini HIGH). Keep this set TINY.
EXTENSION_TRUSTED_MIMES: set[str] = {"message/rfc822"}

# v1.22.1: per-EXTENSION guard augmentation, for when libmagic gives a CONTENT MIME the
# namespace guard doesn't list but the extension legitimately implies. `.eml` is a TEXT email
# format — libmagic types body-dominated mail (HTML bodies, quirky leading headers) as
# `text/plain` / `text/html`, NOT `message/rfc822`, which the OLE2-shaped `email` guard
# rejected → the specialist was skipped on ~38% of real `.eml`. Accept text for `.eml` ONLY,
# so a lying text-typed `.msg` (binary OLE2, same `email` namespace) STAYS distrusted — the
# same extension-gated discipline as EXTENSION_TRUSTED_MIMES (the v1.15.2 sibling fix). The
# stdlib email.parser self-validates; a misnamed text `.eml` yields whatever it finds
# (observe-don't-interpret). Keep this map TINY + extension-specific.
EXTENSION_EXTRA_GUARD_MIMES: dict[str, set[str]] = {
    ".eml": {"text/plain", "text/html"},
}

# v0.8: identifiers for the chatlog specialist. Not registered in
# SPECIALIST_TOOLS / SPECIALIST_NAMESPACE because those are extension-keyed
# and chatlog is content-detected — adding fake-extension keys would risk
# accidental routing if a real file ever happened to use such an extension.
# These constants are the single source of truth for the chatlog tool name
# and namespace; the runtime dispatch in scan_file() consumes them directly.
CHATLOG_NAMESPACE = "chatlog"
CHATLOG_TOOL = "chatlog_signals"

# v0.9: Chatlog vector identity constants. The rules definition string
# captures the three detection rules + extraction logic version. Changing
# any detection regex or extraction algorithm requires bumping METHOD_VERSION
# and updating the rules definition string.
CHATLOG_VECTOR_ID = "chatlog"
CHATLOG_METHOD_VERSION = 9  # v1.4.0: content-shape gate over the count rule — utterance_ratio (function-word/punct/length arms) + FP-lexicon dominance + version-tag structure-vote + FAQ complete-set; density surfaced but not gated
CHATLOG_RULES_DEFINITION = (
    "detect:prose_composite(stop_list_filtered,floor[distinct>=2,total>=3,recurring>=1],"
    "faq_complete_set{question,answer,q,a,faq}->reject,"
    "utterance_ratio>=0.6[utterance=function_word|sentence_punct|words>=4|chars>=25],"
    "fp_lexicon_dominated(>=half distinct)->reject,"
    "version_tag_header(>=2)->reject),"
    "h3_header_re(5+)|section_divider_re(3+)[require nonstoplist_cosignal_distinct>=2],"
    "json_conversation(role_keys{type,role,from,speaker,author}+content_keys{text,value,content,message,body},"
    "line/array/tree,embedded_speaker_labels(prose_composite),require msgs>=3 AND distinct_speakers>=2);"
    "extract:turn_count,speaker_labels(freq>=3,nonspeaker_ci),section_markers,"
    "turn_char_stats,speaker_turn_counts,speaker_turn_chars,alternation,content_shape{utterance_ratio,density},"
    "reference_tokens(at_mentions,wiki_links,code_fence_blocks,url_count),"
    "top_capitalized_tokens(freq>=3,top20),vocabulary_size_estimate;"
    # fp_lexicon_ci = CHATLOG_FP_LABEL_LEXICON (the §3.3 dominance rule) — admonition
    # conventions + Keep-a-Changelog verbs ONLY. FAQ tokens are a SEPARATE set
    # (faq_set, the §4 complete-set rule), not part of the FP lexicon.
    "fp_lexicon_ci:added,caution,changed,deprecated,error,example,examples,fixed,fixme,"
    "important,note,removed,result,security,tip,todo,warning;"
    "faq_set:answer,faq,q,question;"
    # nonspeaker_ci = CHATLOG_SPEAKER_STOP_LIST_CF — labels filtered from detection
    # AND extraction. Enumerated so the rules_hash reflects the actual stop-list
    # (a change to it changes detection/extraction output, so it must change the hash).
    "nonspeaker_ci:allow,answer,arguments,authorization,bcc,caution,cc,command,commands,"
    "copyright,date,description,disallow,distribution,documentation,error,example,examples,"
    "fixme,format,from,important,license,lines,message,newsgroups,note,options,organization,"
    "parameters,password,path,question,references,result,returns,sender,subject,summary,"
    "synopsis,tip,to,todo,usage,version,warning"
)
# NOTE: these literals MUST equal the live CHATLOG_* threshold constants defined
# below (they feed static_tuning_hash, the constants gate detection). A guard
# test (test_v1_4) asserts equality so an edit to one without the other — which
# would let the vector identity miss a real logic change — fails CI.
CHATLOG_STATIC_TUNING = {
    "detection_threshold": 3,
    "h3_detection_threshold": 5,
    "utterance_min_ratio": 0.6,
    "utterance_min_words": 4,
    "utterance_min_chars": 25,
    "fp_lexicon_dominance": 0.5,
    "structure_header_threshold": 2,
    "top_capitalized_tokens_n": 20,
    "json_role_field_keys": ["type", "role", "from", "speaker", "author"],
    "json_content_field_keys": ["text", "value", "content", "message", "body"],
}
# v0.10.1 / v1.2: conversational role VALUES (for the legacy type:user/assistant
# fast path and embedded-label heuristics). Detection no longer requires these
# specific values — see CHATLOG_ROLE_FIELD_KEYS for the generalized check.
CHATLOG_JSONL_ROLE_KEYS = {"user", "assistant", "human"}
# v1.2: generalized conversational-JSON keys. A "message-like" object has a
# role-field key (names the speaker) AND a content-field key (holds the text).
# Ordered tuples (not sets): first-match selection must be deterministic —
# set iteration order is hash-randomized across processes, which would make
# speaker selection (and the manifest checksum) non-reproducible.
CHATLOG_ROLE_FIELD_KEYS = ("type", "role", "from", "speaker", "author")
CHATLOG_CONTENT_FIELD_KEYS = ("text", "value", "content", "message", "body")
CHATLOG_ROLE_FIELD_KEYSET = frozenset(CHATLOG_ROLE_FIELD_KEYS)
CHATLOG_CONTENT_FIELD_KEYSET = frozenset(CHATLOG_CONTENT_FIELD_KEYS)
# v1.2.1: `type` is ambiguous — it names a speaker only in some schemas
# (Claude: type:user/assistant) and is otherwise a wrapper (type:"message"), a
# log level (type:"info"/"error"), or a content-block kind (type:"text"). Accept
# `type` as the speaker ONLY when its value is a conversational role; the other
# role keys (role/from/speaker/author) accept any value. This kills log /
# rich-content / envelope false positives without a denylist.
CHATLOG_CONVERSATIONAL_TYPE_VALUES = frozenset({
    "user", "assistant", "human", "system", "model", "bot", "gpt", "ai",
    "prompter", "tool", "function",
})
# v1.2: regex fallback for truncated/large single-JSON samples (e.g. a multi-MB
# ShareGPT file whose bounded sample won't json.loads). Matches a flat object
# carrying both a role-field and a content-field key, in either order.
CHATLOG_JSON_MESSAGE_RE = re.compile(
    r'\{[^{}]*"(?:type|role|from|speaker|author)"\s*:\s*"[^"]{1,40}"[^{}]*'
    r'"(?:text|value|content|message|body)"\s*:'
    r'|\{[^{}]*"(?:text|value|content|message|body)"\s*:[^{}]*'
    r'"(?:type|role|from|speaker|author)"\s*:\s*"[^"]{1,40}"'
)
# v1.2.1: capture the role-field VALUE so detection can require >=2 DISTINCT
# speakers. A conversation alternates (user/assistant, u0/u1, human/gpt); a
# structured log is all "type":"info" (1 distinct) and a changelog has none.
# This single requirement fixes the v1.2.0 false positives on logs, single-role
# JSONL, and Claude rich-content blocks (all <2 distinct roles).
CHATLOG_JSON_ROLE_VALUE_RE = re.compile(
    r'"(?:type|role|from|speaker|author)"\s*:\s*"([^"]{1,40})"')
# v1.4.0 content-shape thresholds (RFC §2.1, §3.1). The content-shape signal is
# an ADDITIVE layer over the v1.2.4 machinery (stop-list + floor + structure) —
# real-data falsification showed the stop-list is load-bearing and cannot be
# replaced (it suppresses doc-section labels the content signal can't). What
# content-shape ADDS: it rejects cyclic data tables (Item:/Price:, recurring but
# atomic) that the count rule false-positived, and it lets terse-but-real
# dialogue through via the function-word / punctuation arms. A label's post-colon
# content is an *utterance* when it has a function word, ends in sentence
# punctuation, has >=4 words, OR is >=25 chars; utterance_ratio is the fraction
# of (non-stop-list) label lines that clear that bar. Tuned on the v1.4
# adversarial corpus (scratch/review/v1_4_corpus.py): atomic data lands at 0.0,
# dialogue (incl. terse RPG) at >=0.6. density = label lines / non-blank lines.
CHATLOG_UTTERANCE_MIN_WORDS = 4
CHATLOG_UTTERANCE_MIN_CHARS = 25
CHATLOG_UTTERANCE_MIN_RATIO = 0.6
CHATLOG_FP_LEXICON_DOMINANCE = 0.5  # reject when >= this fraction of distinct labels are FP-lexicon
CHATLOG_STRUCTURE_HEADER_MIN = 2    # 2+ version-tag headers vote against (§3.2)
# density is computed and surfaced (content_shape) but is NOT a detection gate —
# a density floor was prototyped and falsified in review (it FN'd multi-line-turn
# dialogue; see _prose_dialogue). No CHATLOG_DENSITY_MIN constant exists.

# v1.4.0: function words — the signal that separates terse dialogue ("hi *there*
# friend", "*how are you*") from atomic data values ("John Smith", "1.00",
# "localhost"), which contain none. A closed standard-English class (articles,
# pronouns, prepositions, conjunctions, aux/wh-words), not a curated denylist.
CHATLOG_FUNCTION_WORDS: frozenset[str] = frozenset("""
a an the i you he she it we they me him her us them my your his its our their
this that these those is are was were be been being am do does did have has had
to of in on at for with from by about as into like through after over between
out up down off and or but so if then than because while when where how what why
who which whom not no yes can could will would should may might must shall
here there now back yet still just only also too very
don't won't can't didn't doesn't isn't aren't wasn't weren't hasn't haven't
hadn't wouldn't couldn't shouldn't i'm you're we're they're it's what's that's
i'll we'll you'll they'll i've we've you've they've let's
""".split())
CHATLOG_WORD_RE = re.compile(r"[a-z']+")

# v1.4.0: the FP-label lexicon (RFC §3.3) — labels that carry sentence content
# (so utterance_ratio can't reject them) but are never conversation participants.
# CLOSED by two real specs (admonition conventions + Keep a Changelog), not
# corpus accretion. Applied as a DOMINANCE rule in _prose_dialogue (reject when
# the lexicon dominates the distinct labels), catching `Added:`-style changelogs.
CHATLOG_FP_LABEL_LEXICON: frozenset[str] = frozenset({
    "note", "warning", "tip", "caution", "important", "example", "examples",
    "todo", "fixme", "result", "error",
    "added", "changed", "deprecated", "removed", "fixed", "security",
})
# v1.4.0: FAQ complete-set exclusion (RFC §4). A FAQ's *entire* distinct label
# set is {Question, Answer} (or {Q, A}); an interview labels turns with
# identities. Reject only when the distinct set is a SUBSET — so `A:`/`B:`
# anonymized dialogue survives (`B` is not a member) while `Q:`/`A:` FAQ is
# excluded. Cost: `Q:`/`A:`-labeled published interviews become an FN (LIMITATIONS).
CHATLOG_FAQ_LABELS: frozenset[str] = frozenset({"question", "answer", "q", "a", "faq"})
# Non-speaker labels — the full v1.2.4 stop-list, RETAINED (real-data
# falsification proved it load-bearing: it suppresses doc-section labels
# (Usage:/Options:/Authorization:) that the content-shape signal cannot, in both
# Rule 1's label collection and the Rules 2/3 markdown co-signal). Case-folded.
CHATLOG_SPEAKER_STOP_LIST_CF: frozenset[str] = frozenset({
    # documentation / admonition labels
    "note", "example", "examples", "result", "warning", "error",
    "disallow", "allow", "todo", "fixme", "tip", "important", "caution",
    # email/usenet headers, man-page sections, legal notices, form fields.
    # `user` is intentionally absent (a legit speaker in many transcripts).
    "from", "to", "cc", "bcc", "date", "subject", "sender", "references",
    "message", "newsgroups", "organization", "lines", "distribution", "path",
    "version", "usage", "options", "command", "commands", "format", "synopsis",
    "description", "arguments", "parameters", "returns", "summary",
    "authorization", "documentation", "license", "copyright", "password",
    # FAQ labels (Question:/Answer: — the single letters Q/A are handled by the
    # FAQ complete-set rule, not here, so `A:`/`B:` dialogue is preserved).
    "question", "answer",
})

# v0.9: Reference tokens vector identity constants.
REFERENCE_TOKENS_VECTOR_ID = "reference_tokens"
REFERENCE_TOKENS_METHOD_VERSION = 2
REFERENCE_TOKENS_RULES_DEFINITION = (
    "count:at_mentions(@[a-zA-Z0-9_]+),wiki_links([[.+?]]),"
    "code_fence_blocks(```pairs),url_count(https?://\\S+),"
    "email_mentions(addr_re),path_references(unix+windows,3+segments,url_stripped),"
    "numeric_id_patterns(#dd+,semver,PROJECT-dd+)"
)
REFERENCE_TOKENS_STATIC_TUNING = {
    "enabled_subcategories": [
        "at_mentions", "wiki_links", "code_fence_blocks", "url_count",
        "email_mentions", "path_references", "numeric_id_patterns",
    ]
}
# Activation set for reference_tokens: text files with these extensions
REFERENCE_TOKENS_EXTENSIONS = {
    ".txt", ".md", ".mdx", ".html", ".htm", ".csv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".xml", ".css", ".vx",
}
# Reference token regex patterns (v0.9 spec §3.2)
# v0.10: filename_patterns vector constants
FILENAME_PATTERNS_VECTOR_ID = "filename_patterns"
FILENAME_PATTERNS_METHOD_VERSION = 1
FILENAME_PATTERNS_RULES_DEFINITION = (
    "match:date_prefix(^\\d{4}[-_]\\d{2}[-_]\\d{2}),"
    "version_marker(v\\d+[._]\\d+),"
    "numbered_revision([-_ ]\\(\\d+\\)|[-_ ]\\d+$),"
    "template_name(Document1|Book1|Sheet1|Untitled|New Document|temp|tmp),"
    "uuid_filename([0-9a-f]{8}-[0-9a-f]{4}-),"
    "copy_suffix(Copy of|Copy|copy)"
)
FILENAME_PATTERNS_STATIC_TUNING = {
    "enabled_subcategories": [
        "date_prefix", "version_marker", "numbered_revision",
        "template_name", "uuid_filename", "copy_suffix",
    ]
}

# v1.10 (PROVISIONAL): format-preservation signal — a per-file obsolescence read
# driven by a CLOSED, versioned table keyed on extension. Lookup-only (no parsing,
# no new IO surface). Observe-only: it reports the *format's* preservation tier, not
# a judgment about the file (same discipline as safety_flags). PREMIS-inspired.
PRESERVATION_VECTOR_ID = "preservation"
PRESERVATION_METHOD_VERSION = 1
# Closed obsolescence table: extension → tier. Absent ⇒ "current". An edit MUST move
# the rules_hash (→ identity_digest) — the table is the rule data (provenance pattern).
FORMAT_OBSOLESCENCE: dict[str, str] = {
    # obsolete — superseded, little/no modern tooling
    ".wpd": "obsolete", ".wp": "obsolete",            # WordPerfect
    ".wks": "obsolete", ".wq1": "obsolete",           # Lotus / Quattro Pro
    ".sxw": "obsolete", ".sxc": "obsolete",           # OpenOffice.org 1.x
    ".swf": "obsolete",                                # Flash (EOL 2020)
    ".rm": "obsolete", ".ram": "obsolete",             # RealMedia
    # at_risk — proprietary / legacy but still encountered in real corpora
    ".doc": "at_risk", ".xls": "at_risk", ".ppt": "at_risk",   # legacy OLE2 Office
    ".dwg": "at_risk", ".dgn": "at_risk",              # proprietary CAD
    ".eps": "at_risk",                                 # legacy encapsulated PostScript
    ".pub": "at_risk", ".cdr": "at_risk",              # MS Publisher / CorelDRAW
}
# rules definition derived from the LIVE table so it cannot drift out of sync.
def preservation_rules_fingerprint() -> str:
    """v1.10: derive the preservation rules string from the LIVE FORMAT_OBSOLESCENCE
    table on each call — matches the v1.6 provenance_rules_fingerprint pattern, so a
    runtime table edit moves the rules_hash → identity_digest (the determinism contract
    for rule-driven fields; in-house review v1.10)."""
    return "preservation:format_obsolescence:" + ",".join(
        f"{k}={v}" for k, v in sorted(FORMAT_OBSOLESCENCE.items())
    )
PRESERVATION_STATIC_TUNING: dict[str, Any] = {"tiers": ["current", "at_risk", "obsolete"]}
FILENAME_DATE_PREFIX_RE = re.compile(r"^\d{4}[-_]\d{2}[-_]\d{2}")
FILENAME_VERSION_MARKER_RE = re.compile(r"(?:^|[._\- ])v\d+[._]\d+", re.IGNORECASE)
FILENAME_NUMBERED_REVISION_RE = re.compile(r"[-_ ]\(\d+\)|[-_ ]\d+$")
FILENAME_TEMPLATE_NAMES = {
    "document1", "book1", "sheet1", "untitled", "new document",
    "temp", "tmp", "unnamed", "noname",
}
FILENAME_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
FILENAME_COPY_SUFFIX_RE = re.compile(r"(?:^Copy of |[ _-]Copy|[ _-]copy|\(copy\))", re.IGNORECASE)

# v0.10: author_aggregate vector constants
AUTHOR_AGGREGATE_VECTOR_ID = "author_aggregate"
AUTHOR_AGGREGATE_METHOD_VERSION = 1
AUTHOR_AGGREGATE_RULES_DEFINITION = (
    "pull:document.author,email.from,pdf.author;"
    "normalize:strip,collapse_whitespace,case_insensitive,exclude_empty,exclude_legacydn;"
    "detect:template_default(multi_extension,threshold)"
)
AUTHOR_AGGREGATE_STATIC_TUNING = {"top_n": 20, "template_default_threshold": 0.4}
AUTHOR_AGGREGATE_EXCLUDED_VALUES = {"", "unknown", "user", "none", "null", "n/a"}

# v1.6: production-provenance vector. Complements author_aggregate (WHO authored);
# this is WHAT-TOOL / WHEN / digitization. Corpus-scoped, pure observation.
PROVENANCE_VECTOR_ID = "provenance"
PROVENANCE_METHOD_VERSION = 2   # v1.10: OLE2 .doc/.xls producing-app now feeds toolchains
PROVENANCE_RULES_DEFINITION = (
    "harvest:pdf.producer|pdf.creator|pdf.creation_date|{document,spreadsheet}.application;"
    "normalize:toolchain_table(closed,first_match,version_stripped_passthrough);"
    "digitization:ocr_producer->ocr_detected|requires_vision->scanned|text_detected->born_digital"
    "|authored_doc_ext->born_digital|else unknown;"
    "aggregate(corpus):toolchains(top_n),production_years,digitization,per_namespace"
)
PROVENANCE_STATIC_TUNING = {"top_n": 20}
# Closed, documented toolchain-normalization table (the vector's dictionary). Ordered:
# OCR + specific BEFORE generic; first match wins. `is_ocr` feeds digitization.
# (regex, normalized_name, is_ocr)
PROVENANCE_TOOLCHAIN_RULES: list[tuple[re.Pattern, str, bool]] = [
    (re.compile(r"paper\s*capture", re.I), "Adobe Acrobat (OCR / Paper Capture)", True),
    (re.compile(r"abbyy|finereader", re.I), "ABBYY FineReader", True),
    (re.compile(r"omnipage|tesseract|readiris", re.I), "OCR (OmniPage/Tesseract/Readiris)", True),
    (re.compile(r"adobe\s*pdf\s*library", re.I), "Adobe PDF Library", False),
    (re.compile(r"acrobat\s*distiller", re.I), "Adobe Acrobat Distiller", False),
    (re.compile(r"adobe\s*(acrobat|indesign|illustrator|photoshop|framemaker)", re.I), "Adobe (Acrobat/CS app)", False),
    (re.compile(r"\.hdi\b|pdfplot", re.I), "Autodesk (HDI plot driver)", False),
    (re.compile(r"autocad|autodesk", re.I), "Autodesk", False),
    (re.compile(r"bluebeam", re.I), "Bluebeam", False),
    (re.compile(r"microsoft.{0,6}print\s*to\s*pdf", re.I), "Microsoft Print to PDF", False),
    (re.compile(r"microsoft.{0,12}word|office\s*word", re.I), "Microsoft Word", False),
    (re.compile(r"microsoft.{0,12}excel", re.I), "Microsoft Excel", False),
    (re.compile(r"microsoft.{0,12}powerpoint", re.I), "Microsoft PowerPoint", False),
    (re.compile(r"libre?office|openoffice", re.I), "LibreOffice/OpenOffice", False),
    (re.compile(r"pdftex|pdflatex|xetex|luatex|dvips|\bla?tex\b", re.I), "TeX/LaTeX", False),
    (re.compile(r"ghostscript", re.I), "Ghostscript", False),
    (re.compile(r"wkhtmltopdf", re.I), "wkhtmltopdf", False),
    (re.compile(r"3-?heights", re.I), "PDF-Tools 3-Heights", False),
    (re.compile(r"itext|tcpdf|\bfpdf\b|reportlab|\bprince\b|weasyprint", re.I), "PDF library (iText/TCPDF/ReportLab/Prince/…)", False),
    (re.compile(r"quartz|\bcairo\b|coregraphics", re.I), "Quartz/Cairo", False),
    # Device-name terms only — word-anchored so it doesn't swallow product names
    # that merely contain "scan" (Scansoft, ScanGauge, PDFScanner) — v1.6 fix.
    (re.compile(r"\bscanner\b|\bcopier\b|imagerunner|workcentre|workcenter|digital\s*sending", re.I), "Scanner/MFP device", False),
]
# unknown producers: strip from the first version-ish token to end so versions
# group ("doPDF Ver 7.2 Build 367 (Windows … Version:" → "doPDF"). `.*$` (not a
# restricted char class) so colons/parens in a messy build string don't block it.
PROVENANCE_VERSION_SUFFIX_RE = re.compile(r"\s+(v(er)?\.?\s*)?\d.*$", re.I | re.S)
PROVENANCE_DIGITIZATION_KEYS = ("born_digital", "scanned", "ocr_detected", "unknown")
PROVENANCE_AUTHORED_DOC_EXT = {".docx", ".xlsx", ".doc", ".xls", ".rtf"}


def provenance_rules_fingerprint(
    table: list[tuple[re.Pattern, str, bool]] = PROVENANCE_TOOLCHAIN_RULES,
    suffix_re: re.Pattern = PROVENANCE_VERSION_SUFFIX_RE,
) -> str:
    """The string fed to `compute_rules_hash` for the provenance vector.

    The toolchain table and the version-suffix regex ARE the normalization rules —
    editing either changes the vector's output, so they MUST feed the rules_hash
    (and thus the identity digest). The prose PROVENANCE_RULES_DEFINITION alone
    doesn't move when the table does (this is the determinism bug chatlog's
    enumerated fp_lexicon already fixed). Derived from the live table so it can't
    drift; parameterized so a guard test can prove a table edit changes the hash."""
    # Include flags, not just .pattern — dropping re.I from a rule (or re.S from the
    # suffix regex) changes matching behavior without changing the source string, and
    # a flag-only edit MUST still move the digest (Codex review, PR #36).
    table_ser = ";".join(
        f"{p.pattern}|{int(p.flags)}=>{name}|{int(is_ocr)}" for p, name, is_ocr in table
    )
    return (f"{PROVENANCE_RULES_DEFINITION}"
            f";table[{table_ser}];version_suffix[{suffix_re.pattern}|{int(suffix_re.flags)}]")

REFERENCE_EMAIL_RE = re.compile(r"\b[\w._%+-]+@[\w.-]+\.[a-zA-Z]{2,}\b")
REFERENCE_PATH_UNIX_RE = re.compile(r"(?:/[\w.]+){3,}")
REFERENCE_PATH_WIN_RE = re.compile(r"[A-Za-z]:\\(?:[\w.]+\\){2,}[\w.]*")
REFERENCE_TICKET_RE = re.compile(r"#\d{2,}")
REFERENCE_SEMVER_RE = re.compile(r"\bv\d+\.\d+\b")
REFERENCE_PROJECT_ID_RE = re.compile(r"\b[A-Z]{2,}-\d+\b")


SCAN_PROFILES: dict[str, dict[str, Any]] = {
    "fast_sort": {
        "baseline_max_bytes": 8192,
        "enable_specialists": False,
    },
    "general": {
        "baseline_max_bytes": 65536,
        "enable_specialists": False,
    },
    "deep_extract": {
        "baseline_max_bytes": 1048576,
        "specialist_budget": 524288,
        "enable_specialists": True,
    },
}


@dataclass
class ScannerConfig:
    preview_max_chars: int = 1000
    sample_size: int = 8192
    baseline_max_bytes: int = 65536
    specialist_budget: int = 131072
    enable_specialists: bool = False
    exclude_hidden: bool = False
    format: str = "json"
    ignore_file: str | None = None
    previous_manifest: str | None = None
    extension_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    signing_key: str | None = None
    signing_key_id: str | None = None
    workers: int = 1   # v1.9: parallel per-file scan worker processes (1 = serial).
                       # Runtime-only — NOT recorded in the manifest (no causal link to
                       # output; excluded from meta.config in scan(), like signing_key).
    progress: bool = False   # v1.9: force the stderr progress indicator (else TTY-auto).
                             # Runtime-only — stderr only, never touches the manifest.
    watch: bool = False             # v1.11: enable the watch loop (trigger rescan on FS events).
    watch_debounce_ms: int = 200    # v1.11: debounce window for batching FS events.
    watch_include_files: bool = False  # v1.11: include files[] in each stream emit.
                                    # All three: runtime-only — NOT in meta.config.

    def effective_for(self, extension: str) -> dict[str, Any]:
        """Resolve effective config values for a given extension."""
        base = {
            "preview_max_chars": self.preview_max_chars,
            "baseline_max_bytes": self.baseline_max_bytes,
            "specialist_budget": self.specialist_budget,
        }
        overrides = self.extension_overrides.get(extension, {})
        for key in ("preview_max_chars", "baseline_max_bytes", "specialist_budget"):
            if key in overrides:
                base[key] = overrides[key]
        # Enforce: baseline_max_bytes >= sample_size
        base["baseline_max_bytes"] = max(base["baseline_max_bytes"], self.sample_size)
        return base


# --- v1.9 parallel scan: module-level worker plumbing (must be importable so a
# ProcessPoolExecutor worker can reference it). Each worker process builds ONE
# Scanner via the initializer (a clean libmagic cookie per process) and runs the
# pure scan_file; results pickle back to the parent in input order. ---
_WORKER_SCANNER: "Scanner | None" = None


def _worker_init(source_dir: Path, config: "ScannerConfig") -> None:
    global _WORKER_SCANNER
    _WORKER_SCANNER = Scanner(source_dir=source_dir, config=config)


def _worker_scan_file(path_str: str) -> "FileRecord":
    if _WORKER_SCANNER is None:   # explicit (not assert — survives python -O)
        raise RuntimeError("worker Scanner not initialized")
    return _WORKER_SCANNER.scan_file(Path(path_str))


def _main_is_importable() -> bool:
    """True if __main__ can be re-imported by a spawn/forkserver worker (it has a
    module spec or a file). False for stdin/notebook/interactive entry points, where
    a non-fork pool would fail noisily — the caller degrades to serial quietly."""
    import __main__
    return getattr(__main__, "__spec__", None) is not None or hasattr(__main__, "__file__")


# --- v1.11 watch driver: a continuous trigger loop. Each iteration runs ONE
# Scanner.scan() against the current filesystem state; emitting the manifest as
# one JSONL line on stdout. Determinism contract carried through: each emitted
# scan is byte-identical to a one-shot file-observer invocation against the same
# FS state (verified in tests/test_v1_11.py). ---

def _strip_files_for_stream(manifest_dict: dict, include_files: bool) -> dict:
    """Default emit excludes files[] to keep the stream small; the `delta` block
    is the load-bearing field. `--watch-include-files` opts back in."""
    if not include_files:
        manifest_dict = {**manifest_dict, "files": []}
    return manifest_dict


def run_watch(source_dir: Path, config: "ScannerConfig") -> int:
    """v1.11: --watch driver. Returns the exit code (0 on clean shutdown via
    SIGTERM/SIGINT; non-zero only on startup failure)."""
    import json as _json
    import signal
    import sys
    import tempfile
    import threading
    from dataclasses import asdict
    from concurrent.futures import ProcessPoolExecutor

    try:
        from watchfiles import watch as _watchfiles_watch
    except ImportError:
        print("file-observer: --watch requires the [watch] extra "
              "(install: pip install 'file-observer[watch]')", file=sys.stderr)
        return 2

    stop = threading.Event()
    def _on_signal(signum, frame):
        stop.set()
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # Kept-warm pool: build ONCE if workers > 1, reuse across rescans (avoids the
    # ProcessPoolExecutor cold-spawn cost per event the RFC §3.1/4.3 calls out).
    workers = max(1, int(config.workers or 1))
    pool = None
    if workers > 1:
        import multiprocessing as _mp
        if _mp.get_start_method() == "fork" or _main_is_importable():
            pool = ProcessPoolExecutor(
                max_workers=workers,
                initializer=_worker_init,
                initargs=(source_dir, config),
            )

    def _one_scan(prev_manifest_path: str | None) -> tuple[dict, str]:
        """Run one Scanner.scan() with optional kept-warm pool; write the manifest
        to a tempfile (the next iteration's previous_manifest), return the dict."""
        cfg = ScannerConfig(**{**asdict(config), "previous_manifest": prev_manifest_path})
        s = Scanner(source_dir=source_dir, config=cfg)
        if pool is not None:
            s._external_pool = pool  # _scan_paths_parallel will pick this up
        m = s.scan()
        # serialise via manifest_to_json (handles dataclass tree)
        full_json = manifest_to_json(m)
        full_dict = _json.loads(full_json)
        # write the FULL manifest to a tempfile for the next iteration's delta source;
        # the stream emit (below) strips files[] per the include flag.
        # encoding=utf-8 explicit (manifest_to_json uses ensure_ascii=False; Windows
        # default locale CP1252 would otherwise raise on non-ASCII — gemini PR #51).
        # try/except so a write/close failure doesn't leak a delete=False tempfile
        # on disk (gemini PR #51).
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                          prefix="watch_manifest_", encoding="utf-8")
        try:
            tmp.write(full_json); tmp.close()
        except Exception:
            try: tmp.close()
            except Exception: pass
            try: Path(tmp.name).unlink()
            except OSError: pass
            raise
        return full_dict, tmp.name

    def _emit(manifest_dict: dict, force_include_files: bool = False) -> None:
        # force_include_files: anchor the initial emit with files[] so consumers see
        # pre-existing state at watch-start (the RFC §4.2 "anchor the stream" intent;
        # without it the first emit carries neither files[] nor an added:[] delta
        # because there's no previous_manifest to diff against — codex PR #51).
        include = config.watch_include_files or force_include_files
        out = _strip_files_for_stream(manifest_dict, include)
        sys.stdout.write(_json.dumps(out, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    prev_path: str | None = None  # delta-vs-empty on the initial emit (§4.2)
    last_tmp: str | None = None
    try:
        # Initial scan: anchors the stream so consumers see world-state at watch-start.
        # force_include_files=True so the first emit carries the full FileRecord set
        # even when --watch-include-files isn't passed (codex PR #51 — without this,
        # the first emit has no files[] AND no `delta.added` because there's nothing
        # to diff against, leaving consumers blind to pre-existing files).
        try:
            md, last_tmp = _one_scan(prev_path)
            _emit(md, force_include_files=True)
            prev_path = last_tmp
        except Exception as exc:
            print(f"file-observer: initial scan failed: {exc!r}", file=sys.stderr)
            return 3

        # The event loop. watchfiles debounces internally (we pass the configured ms).
        # rust_timeout=int(debounce*5) gives us a periodic wake even when no events fire
        # so SIGTERM is honoured promptly.
        debounce_ms = max(50, int(config.watch_debounce_ms))
        for changes in _watchfiles_watch(
            str(source_dir),
            stop_event=stop,
            debounce=debounce_ms,
            rust_timeout=max(500, debounce_ms * 5),
            yield_on_timeout=True,
        ):
            if stop.is_set():
                break
            if not changes:
                continue
            new_tmp = None
            try:
                md, new_tmp = _one_scan(prev_path)
                _emit(md)
                # rotate: delete the previous tempfile, swap in the new one
                if last_tmp:
                    try: Path(last_tmp).unlink()
                    except OSError: pass
                prev_path = new_tmp
                last_tmp = new_tmp
            except Exception as exc:
                # never-crash: per-rescan error → stderr log, continue.
                # If _one_scan succeeded but _emit (or anything after) raised,
                # new_tmp was created but never swapped in — unlink it here so a
                # long-running watch doesn't accumulate orphaned tempfiles
                # (gemini PR #51, e.g. BrokenPipeError on stdout close).
                if new_tmp:
                    try: Path(new_tmp).unlink()
                    except OSError: pass
                print(f"file-observer: rescan failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                continue
        return 0
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        if last_tmp:
            try: Path(last_tmp).unlink()
            except OSError: pass


# --- v1.16: capture-metadata parse helpers (stdlib only, no Pillow). EXIF in JPEG
# (APP1) and HEIC (meta→iinf/iloc→'Exif' item) → TIFF/IFD0 + GPS-presence; HEIC image
# dimensions via the `ispe` box; XMP-presence via the Adobe namespace marker. Validated
# against a real corpus (iPhone HEIC + camera jpgs) before integration. All bounded:
# callers pass a head-capped buffer (EXIF/meta live near the file front). ---
_EXIF_IFD0_TAGS = {0x010F: "make", 0x0110: "model", 0x0112: "orientation", 0x0132: "datetime"}
_EXIF_SUB_ASCII = {0x9003: "datetime_original"}
_EXIF_SUB_NUM = {0xA002: "pixel_x", 0xA003: "pixel_y"}  # authoritative image dims
_EXIF_GPS_IFD_PTR = 0x8825
_EXIF_SUB_IFD_PTR = 0x8769
_EXIF_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
_XMP_MARKER = b"http://ns.adobe.com/xap/1.0/"


def _exif_ascii(b: bytes) -> str:
    return b.split(b"\x00")[0].decode("latin-1", "replace").strip()


def _parse_exif_tiff(buf: bytes) -> dict | None:
    """Parse a TIFF/EXIF block (starts at the II*/MM* header). Returns make/model/
    orientation/datetime_original + gps_present, or None if not a TIFF block."""
    if len(buf) < 8 or buf[:2] not in (b"II", b"MM"):
        return None
    bo = "<" if buf[:2] == b"II" else ">"
    out: dict = {}
    try:
        def read_ifd(off):
            if off < 0 or off + 2 > len(buf):
                return {}
            n = struct.unpack(bo + "H", buf[off:off+2])[0]
            entries = {}
            for i in range(n):
                e = off + 2 + i * 12
                if e + 12 > len(buf):
                    break
                tag, typ, cnt = struct.unpack(bo + "HHI", buf[e:e+8])
                valoff = buf[e+8:e+12]
                size = _EXIF_TYPE_SIZE.get(typ, 1) * cnt
                if size <= 4:
                    raw = valoff
                else:
                    p = struct.unpack(bo + "I", valoff)[0]
                    raw = buf[p:p+size] if 0 <= p and p + size <= len(buf) else b""
                entries[tag] = (typ, cnt, raw)
            return entries
        ifd0 = read_ifd(struct.unpack(bo + "I", buf[4:8])[0])
        for tag, name in _EXIF_IFD0_TAGS.items():
            if tag in ifd0:
                typ, _cnt, raw = ifd0[tag]
                if typ == 2:
                    out[name] = _exif_ascii(raw)
                elif typ == 3 and len(raw) >= 2:
                    out[name] = struct.unpack(bo + "H", raw[:2])[0]
                else:
                    out[name] = None
        out["gps_present"] = _EXIF_GPS_IFD_PTR in ifd0
        if _EXIF_SUB_IFD_PTR in ifd0 and ifd0[_EXIF_SUB_IFD_PTR][0] == 4:
            sub = read_ifd(struct.unpack(bo + "I", ifd0[_EXIF_SUB_IFD_PTR][2])[0])
            for tag, name in _EXIF_SUB_ASCII.items():
                if tag in sub and sub[tag][0] == 2:
                    out[name] = _exif_ascii(sub[tag][2])
            for tag, name in _EXIF_SUB_NUM.items():
                if tag in sub:
                    typ, _cnt, raw = sub[tag]
                    if typ == 3 and len(raw) >= 2:      # SHORT
                        out[name] = struct.unpack(bo + "H", raw[:2])[0]
                    elif typ == 4 and len(raw) >= 4:    # LONG
                        out[name] = struct.unpack(bo + "I", raw[:4])[0]
    except Exception:
        return out or None
    return out or None


def _exif_tiff_from_jpeg(data: bytes) -> bytes | None:
    """Locate the EXIF TIFF block via the JPEG APP1 marker (bounded by the buffer)."""
    i = 2
    while i + 4 < len(data):
        if data[i] != 0xFF:
            break
        marker = data[i+1]
        if marker == 0xDA:                       # start of scan — metadata done
            break
        seglen = struct.unpack(">H", data[i+2:i+4])[0]
        seg = data[i+4: i+2+seglen]
        if marker == 0xE1 and seg[:6] == b"Exif\x00\x00":
            return seg[6:]
        i += 2 + seglen
    return None


def _iter_isobmff(data: bytes, start: int = 0, end: int | None = None):
    """Yield (type, offset, size) for ISOBMFF boxes in [start, end)."""
    end = len(data) if end is None else min(end, len(data))
    o = start
    while o + 8 <= end:
        size = struct.unpack(">I", data[o:o+4])[0]
        typ = data[o+4:o+8].decode("latin-1", "replace")
        if size == 1:
            if o + 16 > end:
                break
            size = struct.unpack(">Q", data[o+8:o+16])[0]
        if size == 0:
            size = end - o
        yield typ, o, size
        if size < 8:
            break
        o += size


def _heif_exif_tiff(data: bytes) -> bytes | None:
    """From a (head-capped) HEIF buffer: locate the 'Exif' item via meta→iinf/iloc and
    return its TIFF block (best-effort, None on any parse miss). Image dimensions are
    deliberately NOT read from the `ispe` box — iPhone/HEIC images are tiled, so the
    first `ispe` is a 512px tile, not the full picture; authoritative dims come from
    EXIF PixelXDimension/PixelYDimension instead (resolving the primary item via
    pitm→ipma→grid is deferred — honest-null beats a wrong tile size)."""
    meta = next((o for t, o, s in _iter_isobmff(data) if t == "meta"), None)
    if meta is None:
        return None
    try:
        msize = struct.unpack(">I", data[meta:meta+4])[0]
        # Two passes' worth of state in one walk: ISO 14496-12 does NOT mandate that
        # `iinf` precede `iloc` among `meta`'s children (leg-4/Codex). Collect both the
        # Exif item-ID and the iloc box offset, then resolve after the walk — so EXIF is
        # found regardless of child order. Bounds-guard every offset (leg-4/Gemini): the
        # walk runs on a head-capped buffer, so o+8 / o2+20 can exceed it on truncation.
        exif_id = None
        iloc_o = None
        for t, o, s in _iter_isobmff(data, meta+12, meta+msize):
            if t == "iinf":
                # iinf FullBox: 12-byte header + entry_count (2 bytes if version 0, else 4)
                child0 = o + 16 if (o + 8 < len(data) and data[o+8]) else o + 14
                for t2, o2, s2 in _iter_isobmff(data, child0, o+s):
                    if t2 == "infe" and o2 + 20 <= len(data) and data[o2+16:o2+20] == b"Exif":
                        exif_id = struct.unpack(">H", data[o2+12:o2+14])[0]
            elif t == "iloc":
                iloc_o = o
        if exif_id is not None and iloc_o is not None:
            blob = _heif_iloc_extent(data, iloc_o, exif_id)
            if blob and len(blob) >= 4:
                pre = struct.unpack(">I", blob[:4])[0]
                return blob[4+pre:] if 4 + pre < len(blob) else blob[4:]
    except Exception:
        pass
    return None


def _heif_iloc_extent(data: bytes, o: int, want_id: int) -> bytes | None:
    """Version-aware iloc parse (ISO 14496-12): return the byte range for want_id."""
    if o + 14 > len(data):           # leg-4/Gemini: guard the fixed header read on truncation
        return None
    ver = data[o+8]
    p = o + 12
    offsz, lensz = data[p] >> 4, data[p] & 0xF
    baseoffsz = data[p+1] >> 4
    indexsz = data[p+1] & 0xF if ver in (1, 2) else 0
    p += 2
    # Degenerate sizes (leg-2/Gemini): with offsz==0 or lensz==0 an extent record is
    # 0 bytes wide, so the inner extent loop never advances `p` and would spin `ecount`
    # (up to 65535) times per item regardless of the buffer bound. We also can't locate
    # a byte range without both sizes — so bail (honest null). Guarantees each extent
    # consumes ≥1 byte, keeping both loops bounded by the buffer.
    if not offsz or not lensz:
        return None
    def take(n):
        nonlocal p
        v = int.from_bytes(data[p:p+n], "big"); p += n; return v
    cnt = take(4) if ver == 2 else take(2)
    # Bounded observation: item_count / extent_count are attacker-controlled and can be
    # up to 2^32-1 — `take` returns 0 past the buffer end (never raises), so without a
    # buffer bound a crafted iloc would spin for billions of iterations (CPU-bound, NOT
    # catchable by the surrounding try/except — the v1.8.1 lesson). Bail the moment we
    # read past the buffer; a real iloc is exhausted long before then.
    for _ in range(cnt):
        if p >= len(data):
            break
        iid = take(4) if ver == 2 else take(2)
        cm = take(2) if ver in (1, 2) else 0     # construction_method
        take(2)                                  # data_reference_index
        base = take(baseoffsz)                   # base_offset
        ecount = take(2)
        for _e in range(ecount):
            if p >= len(data):
                break
            if ver in (1, 2) and indexsz:
                take(indexsz)
            eoff = take(offsz)
            elen = take(lensz)
            start = base + eoff if cm == 0 else eoff   # method 0 = base_offset + extent
            if iid == want_id and 0 <= start and start + elen <= len(data):
                return data[start:start+elen]
    return None


# --- v1.17: video container metadata (ISOBMFF moov/mvhd/trak/tkhd/hdlr/stsd, stdlib
# struct, no library). Container/track half only — codec / duration_s / dims /
# creation_date, oracle-validated against exiftool on 62 real .mov. The iPhone-specific
# Apple QuickTime keys (make/model) + GPS-presence are GATED on a real iPhone-.mov corpus
# (0/62 conformance files carry them) and land as an additive follow-up. ---
_QT_EPOCH_OFFSET = 2082844800  # seconds between 1904-01-01 and 1970-01-01 (QuickTime epoch)


def _box_find(data: bytes, typ: str, start: int, end: int) -> tuple[int, int] | None:
    """First direct child box of the given type in [start, end) → (offset, size)."""
    for t, o, s in _iter_isobmff(data, start, end):
        if t == typ:
            return o, s
    return None


def _parse_mvhd(data: bytes, o: int) -> dict:
    """movie header → creation_date (ISO 8601 UTC) + duration_s (float seconds)."""
    out: dict = {"creation_date": None, "duration_s": None}
    # Bounds-guard before every read (leg-4/Gemini): on a truncated mvhd, int.from_bytes
    # on a SHORT slice does not raise — it silently parses fewer bytes → a WRONG value.
    # Bail to honest-null instead.
    if o + 9 > len(data):
        return out
    ver = data[o+8]
    if ver == 1:
        if o + 40 > len(data):
            return out
        created = int.from_bytes(data[o+12:o+20], "big")
        timescale = int.from_bytes(data[o+28:o+32], "big")
        duration = int.from_bytes(data[o+32:o+40], "big")
        unset = 0xFFFFFFFFFFFFFFFF        # v1 duration is 64-bit (leg-1 #1)
    else:
        if o + 28 > len(data):
            return out
        created = int.from_bytes(data[o+12:o+16], "big")
        timescale = int.from_bytes(data[o+20:o+24], "big")
        duration = int.from_bytes(data[o+24:o+28], "big")
        unset = 0xFFFFFFFF
    if created:
        import datetime as _dt
        # Build from the 1904 epoch via timedelta (NOT fromtimestamp) so pre-1970
        # creation times convert identically on every platform (leg-1 #2 — Windows
        # raises on negative POSIX timestamps); explicit UTC keeps it locale-independent.
        try:
            dt = _dt.datetime(1904, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(seconds=created)
            out["creation_date"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, ValueError):
            out["creation_date"] = None
    if timescale and duration and duration != unset:
        out["duration_s"] = round(duration / timescale, 3)
    return out


def _parse_tkhd_dims(data: bytes, o: int) -> tuple[int | None, int | None]:
    """track header → (width, height) from the 16.16 fixed-point fields at the box tail."""
    if o + 9 > len(data):                 # leg-4/Gemini: guard the version-byte read
        return None, None
    ver = data[o+8]
    base = o + (96 if ver == 1 else 84)   # width offset: v0 = o+84, v1 = o+96 (8-byte times)
    if base + 8 > len(data):
        return None, None
    w = int.from_bytes(data[base:base+4], "big") >> 16
    h = int.from_bytes(data[base+4:base+8], "big") >> 16
    return (w or None), (h or None)


def _video_track(data: bytes, moov_o: int, moov_end: int) -> dict:
    """Find the 'vide'-handler trak; return its dims (tkhd) + codec fourCC (stsd)."""
    out: dict = {"width": None, "height": None, "codec": None}
    for t, o, s in _iter_isobmff(data, moov_o+8, moov_end):
        if t != "trak":
            continue
        mdia = _box_find(data, "mdia", o+8, o+s)
        if not mdia:
            continue
        mo, ms = mdia
        hdlr = _box_find(data, "hdlr", mo+8, mo+ms)
        if not hdlr or data[hdlr[0]+16:hdlr[0]+20] != b"vide":
            continue
        tkhd = _box_find(data, "tkhd", o+8, o+s)
        if tkhd:
            out["width"], out["height"] = _parse_tkhd_dims(data, tkhd[0])
        minf = _box_find(data, "minf", mo+8, mo+ms)
        stbl = _box_find(data, "stbl", minf[0]+8, minf[0]+minf[1]) if minf else None
        stsd = _box_find(data, "stsd", stbl[0]+8, stbl[0]+stbl[1]) if stbl else None
        if stsd and stsd[0] + 24 <= len(data):
            # stsd: version/flags(4) + entry_count(4) + first sample entry [size(4)+format(4)]
            out["codec"] = data[stsd[0]+20:stsd[0]+24].decode("latin-1", "replace").strip() or None
        return out
    return out


_QT_GPS_KEY = b"com.apple.quicktime.location.ISO6709"
# child box types that begin a `meta` box — used to detect the QuickTime-vs-ISO form.
_META_CHILDREN = {b"hdlr", b"keys", b"ilst", b"iinf", b"iloc", b"pitm",
                  b"dinf", b"iref", b"iprp", b"idat", b"ipro"}


def _meta_child_start(data: bytes, o: int, end: int) -> int:
    """A `meta` box comes in two forms (leg-2/Gemini): QuickTime `.mov` `meta` is NOT a
    FullBox → first child at o+8 (its type at o+12); ISO `.mp4` `meta` IS a FullBox (4-byte
    version/flags) → first child at o+12 (its type at o+16). Detect by which offset yields a
    known meta-child box type, so make/model/GPS are found on BOTH .mov and .mp4 (else an
    ISO-meta MP4 silently drops everything). Default QuickTime."""
    if o + 16 <= end and data[o + 12:o + 16] in _META_CHILDREN:   # QuickTime: child type at o+12
        return o + 8
    if o + 20 <= end and data[o + 16:o + 20] in _META_CHILDREN:   # ISO FullBox: child type at o+16
        return o + 12
    return o + 8


def _qt_keys(moov: bytes, meta_o: int, meta_end: int) -> dict[bytes, bytes]:
    """v1.18: Apple QuickTime metadata — `meta`→`keys` (ordered key table) + `ilst`
    (values, items typed by 1-based index into the key table) → {key: value_bytes}.
    Handles BOTH `meta` forms via `_meta_child_start` (QuickTime `.mov` children at +8,
    ISO `.mp4` at +12). All reads bounds-guarded; never-crash."""
    out: dict[bytes, bytes] = {}
    keys: list[bytes] = []
    child = _meta_child_start(moov, meta_o, meta_end)
    kb = _box_find(moov, "keys", child, meta_end)
    lb = _box_find(moov, "ilst", child, meta_end)
    if not kb or not lb:
        return out
    ko, ks = kb
    kend = min(ko + ks, len(moov))
    if ko + 16 > kend:
        return out
    n = int.from_bytes(moov[ko + 12:ko + 16], "big")
    p = ko + 16
    for _ in range(n):
        if p + 8 > kend:                       # bounded by the box, not n (attacker count)
            break
        ksz = int.from_bytes(moov[p:p + 4], "big")
        if ksz < 8 or p + ksz > kend:
            break
        keys.append(moov[p + 8:p + ksz])       # entry: size(4) + namespace(4) + key string
        p += ksz
    lo, ls = lb
    for _t, io, isz in _iter_isobmff(moov, lo + 8, lo + ls):
        if io + 8 > len(moov):
            break
        idx = int.from_bytes(moov[io + 4:io + 8], "big")   # item box "type" = 1-based key index
        db = _box_find(moov, "data", io + 8, min(io + isz, len(moov)))
        if not db or not (0 < idx <= len(keys)):
            continue
        do, ds = db
        out[keys[idx - 1]] = moov[do + 16:min(do + ds, len(moov))]   # data: size+type+ver+locale, value at +16
    return out


def _qt_text(val: bytes | None) -> str | None:
    """Decode an Apple-key UTF-8 string value, as-is (observe-don't-interpret)."""
    if not val:
        return None
    return val.decode("utf-8", "replace").strip("\x00").strip() or None


def _parse_moov(moov: bytes) -> dict:
    """Parse a standalone moov box buffer (offset 0). Container/track + (v1.18) Apple
    capture device + GPS-presence."""
    out: dict = {"codec": None, "duration_s": None, "width": None, "height": None,
                 "creation_date": None, "creation_date_qt": None, "make": None, "model": None,
                 "gps_present": False, "gps_source": None}
    msize = struct.unpack(">I", moov[:4])[0] if len(moov) >= 4 else len(moov)
    end = min(msize, len(moov))
    mvhd = _box_find(moov, "mvhd", 8, end)
    if mvhd:
        out.update(_parse_mvhd(moov, mvhd[0]))
    out.update(_video_track(moov, 0, end))
    # v1.18: Apple QuickTime keys (make/model) + GPS-presence. Apple-first (Android
    # udta/©xyz deferred until a sample validates it — §8 Q1).
    meta = _box_find(moov, "meta", 8, end)
    if meta:
        try:
            keys = _qt_keys(moov, meta[0], min(meta[0] + meta[1], len(moov)))
            out["make"] = _qt_text(keys.get(b"com.apple.quicktime.make"))
            out["model"] = _qt_text(keys.get(b"com.apple.quicktime.model"))
            # v1.20: the QuickTime creationdate key — capture moment WITH timezone (the
            # truer capture time; mvhd `creation_date` is file-finalization, UTC). Surfaced
            # AS-IS, SEPARATE from creation_date — never reconciled (observe-don't-interpret).
            out["creation_date_qt"] = _qt_text(keys.get(b"com.apple.quicktime.creationdate"))
            if keys.get(_QT_GPS_KEY):   # NON-EMPTY value — a tombstone/empty box is not a location (leg-2/Gemini)
                out["gps_present"] = True
                out["gps_source"] = _QT_GPS_KEY.decode("ascii")   # the exact mechanism (presence, not coords)
        except Exception:
            pass
    return out


class Scanner:
    def __init__(self, source_dir: Path, config: ScannerConfig | None = None) -> None:
        self.source_dir = source_dir.resolve()
        self.config = config or ScannerConfig()
        # python-magic may IMPORT yet fail to construct when the libmagic C library
        # is absent (the common Windows case) — degrade to the pure-Python MIME
        # fallback instead of crashing the whole scan at init (v1.15 cross-platform).
        self._magic = None
        if magic is not None:
            try:
                self._magic = magic.Magic(mime=True)
            except Exception:
                self._magic = None
        self._ignore_patterns = self._load_ignore_patterns()

    def _load_ignore_patterns(self) -> list[str]:
        patterns: list[str] = []
        # Check explicit --ignore-file first, then default .scannerignore
        ignore_path: Path | None = None
        if self.config.ignore_file:
            ignore_path = Path(self.config.ignore_file)
        else:
            default = self.source_dir / ".scannerignore"
            if default.is_file():
                ignore_path = default
        if ignore_path and ignore_path.is_file():
            for line in ignore_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        return patterns

    def _is_ignored(self, rel_path: Path) -> bool:
        rel_str = rel_path.as_posix()
        for pattern in self._ignore_patterns:
            # Directory pattern (ends with /)
            if pattern.endswith("/"):
                dir_pattern = pattern.rstrip("/")
                # Match each individual component (e.g. "node_modules/")
                if any(fnmatch(part, dir_pattern) for part in rel_path.parts[:-1]):
                    return True
                # Match path-scoped patterns (e.g. "src/generated/")
                # Build cumulative directory prefixes and match against the pattern
                dir_parts = rel_path.parts[:-1]
                for i in range(len(dir_parts)):
                    prefix = "/".join(dir_parts[: i + 1])
                    if fnmatch(prefix, dir_pattern):
                        return True
            # File pattern
            if fnmatch(rel_path.name, pattern):
                return True
            if fnmatch(rel_str, pattern):
                return True
        return False

    def scan(self) -> ScanManifest:
        self._vector_registry = VectorRegistry()
        self._chatlog_applied_count: int = 0
        self._chatlog_summary_turns: int = 0
        self._chatlog_summary_speakers: set[str] = set()
        self._chatlog_summary_marker_count: int = 0
        self._chatlog_summary_styles: set[str] = set()
        self._reference_tokens_applied_count: int = 0
        self._reference_tokens_sums: dict[str, int] = {
            "at_mentions": 0, "wiki_links": 0, "code_fence_blocks": 0,
            "url_count": 0, "email_mentions": 0, "path_references": 0,
            "numeric_id_patterns": 0,
        }
        self._reference_tokens_files_with_any: int = 0
        self._filename_patterns_applied_count: int = 0
        self._filename_patterns_sums: dict[str, int] = {
            "date_prefix": 0, "version_marker": 0, "numbered_revision": 0,
            "template_name": 0, "uuid_filename": 0, "copy_suffix": 0,
        }
        self._filename_patterns_files_with_any: int = 0
        self._preservation_applied_count: int = 0
        self._preservation_tier_sums: dict[str, int] = {"current": 0, "at_risk": 0, "obsolete": 0}
        # v1.9: the per-file pass (scan_file) is pure and parallelizable. Discovery
        # yields a deterministic (sorted) path order; the records come back in that
        # SAME order (serial preserves it; ProcessPoolExecutor.map preserves input
        # order regardless of completion). The corpus counters + chatlog accumulation
        # are then derived here, serially, over that ordered record list — so the
        # manifest is byte-identical for any worker count.
        import sys as _sys
        self._progress_on = bool(self.config.progress) or (
            hasattr(_sys.stderr, "isatty") and _sys.stderr.isatty())
        paths = list(self.iter_files(self.source_dir))
        records = self._scan_paths(paths)
        self._aggregate_file_counters(records)
        for rec in records:
            # Track chatlog vector applied set: both is_chatlog files and email body hits
            if rec.is_chatlog:
                self._chatlog_applied_count += 1
                if rec.specialist_metadata and CHATLOG_NAMESPACE in rec.specialist_metadata:
                    self._accumulate_chatlog_summary(rec.specialist_metadata[CHATLOG_NAMESPACE])
            if rec.specialist_metadata and "email" in rec.specialist_metadata and "body_chatlog" in rec.specialist_metadata.get("email", {}):
                self._chatlog_applied_count += 1
                self._accumulate_chatlog_summary(rec.specialist_metadata["email"]["body_chatlog"])

        # Register file-scoped vectors from accumulated state
        self._register_chatlog_vector()
        self._register_reference_tokens_vector()
        self._register_filename_patterns_vector()
        self._register_preservation_vector()

        # Run corpus-scoped vectors after the file walk completes
        self._run_corpus_vectors(records)

        context = self._build_context()
        meta = ScanMeta(
            scan_id=str(uuid.uuid4()),
            generated_at=self.now_iso(),
            source_dir=str(self.source_dir),
            config={k: v for k, v in asdict(self.config).items() if k not in ("signing_key", "signing_key_id", "workers", "progress", "watch", "watch_debounce_ms", "watch_include_files")},
        )
        stats = self._compute_stats(records)
        quality = self._compute_quality(records)
        routing = self._compute_routing_summary(records)
        delta = self._compute_delta(records)

        # Build manifest without checksum first, then compute it
        manifest = ScanManifest(
            schema_version=SCHEMA_VERSION,
            context=context,
            meta=meta,
            stats=stats,
            quality=quality,
            routing_summary=routing,
            delta=delta,
            manifest_checksum="",
            manifest_signature=None,
            files=records,
            vectors_collected=self._vector_registry.to_list(),
            summary="",
        )
        manifest.summary = self._build_summary(manifest)
        manifest.manifest_checksum = compute_manifest_checksum(manifest)
        # Optional HMAC signing
        if self.config.signing_key:
            import hmac
            sig = hmac.new(
                self.config.signing_key.encode("utf-8"),
                manifest.manifest_checksum.encode("utf-8"),
                "sha256",
            ).hexdigest()
            manifest.manifest_signature = {
                "algorithm": "hmac-sha256",
                "key_id": self.config.signing_key_id or "default",
                "value": sig,
            }
        return manifest

    def _scan_paths(self, paths: list[Path]) -> list[FileRecord]:
        """Scan each path → FileRecord, preserving input order. v1.9: serial by
        default; a process pool runs the pure per-file pass when ``config.workers`` > 1.
        Either way the record list is identical (``scan_file`` is pure; the pool
        preserves input order) — the byte-identical-across-workers contract."""
        workers = max(1, int(self.config.workers or 1))
        total = len(paths)
        if workers > 1 and total > 1:
            return self._scan_paths_parallel(paths, workers, total, external_pool=getattr(self, "_external_pool", None))
        out: list[FileRecord] = []
        for i, p in enumerate(paths, 1):
            out.append(self.scan_file(p))
            self._emit_progress(i, total)
        self._emit_progress(total, total, final=True)
        return out

    def _scan_paths_parallel(self, paths: list[Path], workers: int, total: int,
                              external_pool=None) -> list[FileRecord]:
        """Process-pool the pure per-file pass. ``ProcessPoolExecutor.map`` yields
        results in input order regardless of completion order, so the record list
        equals the serial one. Never-crash: any pool failure (a worker death, or a
        sandboxed env that forbids fork/exec) falls back to a serial rescan, where
        ``scan_file``'s in-band ErrorRecord handles the offending file. Progress is
        emitted by the PARENT as results arrive (workers never print).

        v1.11: ``external_pool`` (a long-lived ``ProcessPoolExecutor``) reuses one
        warm pool across many calls (e.g. ``--watch``). When provided, this method
        neither builds nor shuts down the pool; the caller owns its lifecycle."""
        from concurrent.futures import ProcessPoolExecutor
        import multiprocessing as _mp
        # Portability guard (PR #46 / codex): a non-fork start method (spawn/forkserver
        # on Windows/macOS) re-imports __main__ in each worker; from an unimportable
        # entry point (stdin/notebook) that fails noisily. Skip the pool quietly →
        # serial (correct output, just not parallel). Linux defaults to fork → proceeds.
        if _mp.get_start_method() != "fork" and not _main_is_importable():
            return [self.scan_file(p) for p in paths]
        path_strs = [str(p) for p in paths]
        chunksize = max(1, total // (workers * 8))
        out: list[FileRecord] = []
        try:
            if external_pool is not None:
                # v1.11: caller-managed kept-warm pool; don't construct/destroy.
                ex = external_pool
                try:
                    for i, rec in enumerate(ex.map(_worker_scan_file, path_strs, chunksize=chunksize), 1):
                        out.append(rec)
                        self._emit_progress(i, total)
                except Exception:
                    # don't shut down the caller's pool — they own it; let them deal
                    raise
            else:
                with ProcessPoolExecutor(max_workers=workers,
                                         initializer=_worker_init,
                                         initargs=(self.source_dir, self.config)) as ex:
                    try:
                        for i, rec in enumerate(ex.map(_worker_scan_file, path_strs, chunksize=chunksize), 1):
                            out.append(rec)
                            self._emit_progress(i, total)
                    except Exception:
                        ex.shutdown(wait=False, cancel_futures=True)  # don't block on a broken pool
                        raise
            self._emit_progress(total, total, final=True)
            return out
        except Exception:
            # never-crash: ex.map yields in input order, so the records already in `out`
            # match paths[:len(out)] exactly — finish the REMAINDER serially → the result
            # is byte-identical to a full serial scan, without rescanning what succeeded.
            return out + [self.scan_file(p) for p in paths[len(out):]]

    def _emit_progress(self, done: int, total: int, final: bool = False) -> None:
        """v1.9: a throttled ``done/total`` line to STDERR only — never stdout, the
        manifest, or any checksummed value (determinism-safe by construction). Shown
        when ``config.progress`` or stderr is a TTY; throttled to ~1% steps."""
        if not getattr(self, "_progress_on", False) or total <= 0:
            return
        step = max(1, total // 100)
        if not final and done % step != 0:
            return
        import sys
        print(f"  scanning {done}/{total} files…",
              end=("\n" if final else "\r"), file=sys.stderr, flush=True)

    def _aggregate_file_counters(self, records: list[FileRecord]) -> None:
        """Derive the per-file corpus counters (filename_patterns + reference_tokens)
        from the completed records. v1.9: these were incremented inside ``scan_file``;
        moving them here makes ``scan_file`` pure (parallel-safe) without changing any
        value — the sums/counts are order-independent and read identical fields."""
        for rec in records:
            fp = rec.filename_patterns
            if fp is not None:
                self._filename_patterns_applied_count += 1
                if any(fp.values()):
                    self._filename_patterns_files_with_any += 1
                for subcat, matched in fp.items():
                    if matched:
                        self._filename_patterns_sums[subcat] = self._filename_patterns_sums.get(subcat, 0) + 1
            rt = rec.reference_tokens
            if rt is not None:
                self._reference_tokens_applied_count += 1
                has_any = False
                for subcat, count in rt.items():
                    self._reference_tokens_sums[subcat] = self._reference_tokens_sums.get(subcat, 0) + count
                    if count > 0:
                        has_any = True
                if has_any:
                    self._reference_tokens_files_with_any += 1
            pres = rec.preservation
            if pres is not None:
                self._preservation_applied_count += 1
                tier = pres.get("format_obsolescence", "current")
                self._preservation_tier_sums[tier] = self._preservation_tier_sums.get(tier, 0) + 1

    def _register_preservation_vector(self) -> None:
        """v1.10 (provisional): register the preservation vector. The obsolescence
        TABLE feeds the rules_hash (derived from the live table) so a table edit moves
        the identity_digest — the determinism contract for rule-driven fields."""
        rules_hash = compute_rules_hash(preservation_rules_fingerprint())
        tuning_hash = compute_tuning_hash(PRESERVATION_STATIC_TUNING)
        identity_digest = compute_vector_identity_digest(
            PRESERVATION_VECTOR_ID, PRESERVATION_METHOD_VERSION, rules_hash, tuning_hash,
        )
        self._vector_registry.register(VectorRecord(
            vector_id=PRESERVATION_VECTOR_ID,
            method_version=PRESERVATION_METHOD_VERSION,
            scope="file",
            rules_hash=rules_hash,
            static_tuning_hash=tuning_hash,
            dynamic_tuning_hash=None,
            dictionary_id=None,
            identity_digest=identity_digest,
            applied_to_count=self._preservation_applied_count,
            summary=dict(self._preservation_tier_sums),
        ))

    def _accumulate_chatlog_summary(self, meta: dict[str, Any]) -> None:
        """Accumulate chatlog metadata into corpus-level summary accumulators."""
        self._chatlog_summary_turns += meta.get("turn_count", 0)
        self._chatlog_summary_speakers.update(meta.get("speaker_labels", []))
        self._chatlog_summary_marker_count += meta.get("section_marker_count", 0)
        self._chatlog_summary_styles.update(meta.get("section_marker_styles", []))

    def _register_chatlog_vector(self) -> None:
        """Register the chatlog vector in the registry with corpus-level summary."""
        rules_hash = compute_rules_hash(CHATLOG_RULES_DEFINITION)
        tuning_hash = compute_tuning_hash(CHATLOG_STATIC_TUNING)
        identity_digest = compute_vector_identity_digest(
            CHATLOG_VECTOR_ID, CHATLOG_METHOD_VERSION, rules_hash, tuning_hash,
        )
        summary: dict[str, Any] = {
            "matched_files": self._chatlog_applied_count,
            "total_turns": self._chatlog_summary_turns,
            "distinct_speakers": sorted(self._chatlog_summary_speakers),
            "section_marker_count": self._chatlog_summary_marker_count,
            "section_marker_styles": sorted(self._chatlog_summary_styles),
        }
        self._vector_registry.register(VectorRecord(
            vector_id=CHATLOG_VECTOR_ID,
            method_version=CHATLOG_METHOD_VERSION,
            scope="file",
            rules_hash=rules_hash,
            static_tuning_hash=tuning_hash,
            dynamic_tuning_hash=None,
            dictionary_id=None,
            identity_digest=identity_digest,
            applied_to_count=self._chatlog_applied_count,
            summary=summary,
        ))

    def _register_reference_tokens_vector(self) -> None:
        """Register the reference_tokens vector with corpus-level summary."""
        rules_hash = compute_rules_hash(REFERENCE_TOKENS_RULES_DEFINITION)
        tuning_hash = compute_tuning_hash(REFERENCE_TOKENS_STATIC_TUNING)
        identity_digest = compute_vector_identity_digest(
            REFERENCE_TOKENS_VECTOR_ID, REFERENCE_TOKENS_METHOD_VERSION,
            rules_hash, tuning_hash,
        )
        summary = dict(self._reference_tokens_sums)
        summary["files_with_any_reference"] = self._reference_tokens_files_with_any
        self._vector_registry.register(VectorRecord(
            vector_id=REFERENCE_TOKENS_VECTOR_ID,
            method_version=REFERENCE_TOKENS_METHOD_VERSION,
            scope="file",
            rules_hash=rules_hash,
            static_tuning_hash=tuning_hash,
            dynamic_tuning_hash=None,
            dictionary_id=None,
            identity_digest=identity_digest,
            applied_to_count=self._reference_tokens_applied_count,
            summary=summary,
        ))

    def _register_filename_patterns_vector(self) -> None:
        """Register the filename_patterns vector with corpus-level summary."""
        rules_hash = compute_rules_hash(FILENAME_PATTERNS_RULES_DEFINITION)
        tuning_hash = compute_tuning_hash(FILENAME_PATTERNS_STATIC_TUNING)
        identity_digest = compute_vector_identity_digest(
            FILENAME_PATTERNS_VECTOR_ID, FILENAME_PATTERNS_METHOD_VERSION,
            rules_hash, tuning_hash,
        )
        summary = dict(self._filename_patterns_sums)
        summary["files_with_any_pattern"] = self._filename_patterns_files_with_any
        self._vector_registry.register(VectorRecord(
            vector_id=FILENAME_PATTERNS_VECTOR_ID,
            method_version=FILENAME_PATTERNS_METHOD_VERSION,
            scope="file",
            rules_hash=rules_hash,
            static_tuning_hash=tuning_hash,
            dynamic_tuning_hash=None,
            dictionary_id=None,
            identity_digest=identity_digest,
            applied_to_count=self._filename_patterns_applied_count,
            summary=summary,
        ))

    def _run_corpus_vectors(self, records: list[FileRecord]) -> None:
        """Run corpus-scoped vectors after the file walk completes."""
        self._run_author_aggregate(records)
        self._run_provenance(records)

    def _run_author_aggregate(self, records: list[FileRecord]) -> None:
        """v0.10: author_aggregate corpus vector. Pulls authors from specialists."""
        if not self.config.enable_specialists:
            return
        authors: list[tuple[str, str]] = []  # (normalized, original)
        per_ext: dict[str, list[str]] = {}  # ext -> [normalized authors]
        all_ext_counts: dict[str, int] = {}  # ext -> total files (for template default denominator)
        ns_counts: dict[str, int] = {"document": 0, "email": 0, "pdf": 0}

        for rec in records:
            all_ext_counts[rec.extension] = all_ext_counts.get(rec.extension, 0) + 1
            if not rec.specialist_metadata:
                continue
            raw_author: str | None = None
            ns_source: str | None = None
            if "document" in rec.specialist_metadata:
                raw_author = rec.specialist_metadata["document"].get("author")
                ns_source = "document"
            elif "email" in rec.specialist_metadata:
                raw_author = rec.specialist_metadata["email"].get("from")
                ns_source = "email"
            elif "pdf" in rec.specialist_metadata:
                raw_author = rec.specialist_metadata["pdf"].get("author")
                ns_source = "pdf"

            if not raw_author or not isinstance(raw_author, str):
                continue
            # Normalize
            normalized = " ".join(raw_author.strip().split())
            if normalized.lower() in AUTHOR_AGGREGATE_EXCLUDED_VALUES:
                continue
            if normalized.startswith(("/o=", "/O=")):
                continue

            authors.append((normalized.lower(), raw_author.strip()))
            if ns_source:
                ns_counts[ns_source] = ns_counts.get(ns_source, 0) + 1
            per_ext.setdefault(rec.extension, []).append(normalized.lower())

        if not authors:
            # Register with zero counts
            rules_hash = compute_rules_hash(AUTHOR_AGGREGATE_RULES_DEFINITION)
            tuning_hash = compute_tuning_hash(AUTHOR_AGGREGATE_STATIC_TUNING)
            identity_digest = compute_vector_identity_digest(
                AUTHOR_AGGREGATE_VECTOR_ID, AUTHOR_AGGREGATE_METHOD_VERSION,
                rules_hash, tuning_hash,
            )
            self._vector_registry.register(VectorRecord(
                vector_id=AUTHOR_AGGREGATE_VECTOR_ID,
                method_version=AUTHOR_AGGREGATE_METHOD_VERSION,
                scope="corpus",
                rules_hash=rules_hash,
                static_tuning_hash=tuning_hash,
                dynamic_tuning_hash=None,
                dictionary_id=None,
                identity_digest=identity_digest,
                applied_to_count=0,
                summary={"distinct_authors": 0, "top_authors": [], "template_default_candidates": [], "per_namespace_counts": ns_counts, "per_extension_distinct_authors": {}},
            ))
            return

        # Build frequency map: normalized_lower -> (best_casing, count)
        casing_counts: dict[str, dict[str, int]] = {}
        total_counts: dict[str, int] = {}
        for norm_lower, original in authors:
            casing_counts.setdefault(norm_lower, {})
            casing_counts[norm_lower][original] = casing_counts[norm_lower].get(original, 0) + 1
            total_counts[norm_lower] = total_counts.get(norm_lower, 0) + 1

        # Pick best casing per normalized name
        best_casing: dict[str, str] = {}
        for norm_lower, casings in casing_counts.items():
            best = max(casings.items(), key=lambda x: (x[1], x[0]))
            best_casing[norm_lower] = best[0]

        # Top authors
        top_n = AUTHOR_AGGREGATE_STATIC_TUNING["top_n"]
        sorted_authors = sorted(total_counts.items(), key=lambda x: (-x[1], x[0]))
        top_authors = [[best_casing[norm], count] for norm, count in sorted_authors[:top_n]]

        # Template default detection
        threshold = AUTHOR_AGGREGATE_STATIC_TUNING["template_default_threshold"]
        template_candidates: list[str] = []
        for norm_lower in total_counts:
            exts_with_author = set()
            for ext, ext_authors in per_ext.items():
                if norm_lower in ext_authors:
                    exts_with_author.add(ext)
            if len(exts_with_author) >= 2:
                for ext in exts_with_author:
                    ext_total = all_ext_counts.get(ext, 0)
                    ext_author_count = sum(1 for a in per_ext[ext] if a == norm_lower)
                    if ext_total > 0 and ext_author_count / ext_total > threshold:
                        template_candidates.append(best_casing[norm_lower])
                        break
        template_candidates.sort()

        # Per-extension distinct authors
        per_ext_distinct = {ext: len(set(authors_list)) for ext, authors_list in sorted(per_ext.items())}

        rules_hash = compute_rules_hash(AUTHOR_AGGREGATE_RULES_DEFINITION)
        tuning_hash = compute_tuning_hash(AUTHOR_AGGREGATE_STATIC_TUNING)
        identity_digest = compute_vector_identity_digest(
            AUTHOR_AGGREGATE_VECTOR_ID, AUTHOR_AGGREGATE_METHOD_VERSION,
            rules_hash, tuning_hash,
        )
        self._vector_registry.register(VectorRecord(
            vector_id=AUTHOR_AGGREGATE_VECTOR_ID,
            method_version=AUTHOR_AGGREGATE_METHOD_VERSION,
            scope="corpus",
            rules_hash=rules_hash,
            static_tuning_hash=tuning_hash,
            dynamic_tuning_hash=None,
            dictionary_id=None,
            identity_digest=identity_digest,
            applied_to_count=len(authors),
            summary={
                "distinct_authors": len(total_counts),
                "top_authors": top_authors,
                "template_default_candidates": template_candidates,
                "per_namespace_counts": {k: v for k, v in ns_counts.items() if v > 0},
                "per_extension_distinct_authors": per_ext_distinct,
            },
        ))

    @staticmethod
    def _normalize_toolchain(raw: str) -> tuple[str, bool]:
        """Normalize a producer/creator string to a canonical toolchain name and an
        is_ocr flag (v1.6). Closed table, first match wins; OCR + specific rules
        precede generic. Unknown producers are passed through with a trailing
        version/build suffix stripped so versions group ("doPDF Ver 7.2 …" → "doPDF")."""
        s = " ".join(raw.split())
        for pattern, name, is_ocr in PROVENANCE_TOOLCHAIN_RULES:
            if pattern.search(s):
                return (name, is_ocr)
        cleaned = PROVENANCE_VERSION_SUFFIX_RE.sub("", s).strip()
        return (cleaned or s, False)

    def _classify_digitization(self, rec: 'FileRecord', is_ocr: bool) -> str | None:
        """born_digital / scanned / ocr_detected / unknown — reuses v1.5 signals.
        Returns None for files where digitization is not a meaningful axis (so the
        counts cover only PDFs + authored documents)."""
        if is_ocr:
            return "ocr_detected"
        pdf = (rec.specialist_metadata or {}).get("pdf")
        if pdf:
            if rec.requires_vision:
                return "scanned"
            if pdf.get("text_detected"):
                return "born_digital"
            return "unknown"
        if rec.extension in PROVENANCE_AUTHORED_DOC_EXT:
            return "born_digital"
        return None

    def _run_provenance(self, records: list[FileRecord]) -> None:
        """v1.6: corpus-scoped production-provenance vector — normalized toolchain,
        production era, digitization origin. Pure observation (no LOGIC change).
        Gated on enable_specialists (provenance lives in specialist metadata)."""
        if not self.config.enable_specialists:
            return
        toolchains: list[str] = []
        years: dict[str, int] = {}
        digitization: dict[str, int] = {}
        per_ns: dict[str, int] = {}

        for rec in records:
            sm = rec.specialist_metadata or {}
            producer: str | None = None
            ns_source: str | None = None
            pdf = sm.get("pdf")
            if pdf:
                producer = pdf.get("producer") or pdf.get("creator")
                ns_source = "pdf"
            else:
                for ns in ("document", "spreadsheet"):
                    app = sm.get(ns, {}).get("application") if isinstance(sm.get(ns), dict) else None
                    if app:
                        producer, ns_source = app, ns
                        break

            is_ocr = False
            if producer and isinstance(producer, str) and producer.strip():
                name, is_ocr = self._normalize_toolchain(producer.strip())
                if name:
                    toolchains.append(name)
                    if ns_source:
                        per_ns[ns_source] = per_ns.get(ns_source, 0) + 1

            if pdf:
                cd = pdf.get("creation_date")
                if cd and isinstance(cd, str):
                    ym = re.search(r"(\d{4})", cd)
                    if ym and 1980 <= int(ym.group(1)) <= 2099:
                        years[ym.group(1)] = years.get(ym.group(1), 0) + 1

            cls = self._classify_digitization(rec, is_ocr)
            if cls:
                digitization[cls] = digitization.get(cls, 0) + 1

        counts = Counter(toolchains)
        summary = {
            # canonical order: count desc, then name asc (matches author_aggregate;
            # Counter.most_common leaves ties in first-seen/path order → non-deterministic).
            "toolchains": [{"name": k, "count": c}
                           for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
                           [:PROVENANCE_STATIC_TUNING["top_n"]]],
            "distinct_toolchains": len(counts),
            "production_years": dict(sorted(years.items())),
            "production_year_range": ([min(years), max(years)] if years else []),
            "digitization": {k: digitization.get(k, 0) for k in PROVENANCE_DIGITIZATION_KEYS},
            "per_namespace_counts": dict(sorted(per_ns.items())),
        }
        rules_hash = compute_rules_hash(provenance_rules_fingerprint())
        tuning_hash = compute_tuning_hash(PROVENANCE_STATIC_TUNING)
        identity_digest = compute_vector_identity_digest(
            PROVENANCE_VECTOR_ID, PROVENANCE_METHOD_VERSION, rules_hash, tuning_hash,
        )
        self._vector_registry.register(VectorRecord(
            vector_id=PROVENANCE_VECTOR_ID,
            method_version=PROVENANCE_METHOD_VERSION,
            scope="corpus",
            rules_hash=rules_hash,
            static_tuning_hash=tuning_hash,
            dynamic_tuning_hash=None,
            dictionary_id=None,
            identity_digest=identity_digest,
            applied_to_count=len(toolchains),
            summary=summary,
        ))

    def _extract_filename_patterns(self, filename: str) -> dict[str, bool]:
        """v0.10: detect structural patterns in filenames."""
        stem = Path(filename).stem
        stem_lower = stem.lower()
        return {
            "date_prefix": bool(FILENAME_DATE_PREFIX_RE.search(filename)),
            "version_marker": bool(FILENAME_VERSION_MARKER_RE.search(stem)),
            "numbered_revision": bool(FILENAME_NUMBERED_REVISION_RE.search(stem)),
            "template_name": stem_lower in FILENAME_TEMPLATE_NAMES,
            "uuid_filename": bool(FILENAME_UUID_RE.search(filename)),
            "copy_suffix": bool(FILENAME_COPY_SUFFIX_RE.search(stem)),
        }

    def _extract_preservation(self, extension: str) -> dict[str, Any]:
        """v1.10 (provisional): closed-table format-obsolescence lookup by extension.
        Pure, lookup-only (no parsing, no IO). Absent ⇒ 'current'. Observe-only — it
        reports the format's preservation tier, never a verdict about the file."""
        tier = FORMAT_OBSOLESCENCE.get(extension.lower(), "current")
        return {"format_obsolescence": tier, "migration_recommended": tier == "obsolete"}

    def _build_summary(self, manifest: 'ScanManifest') -> str:
        """v0.10: build a human-readable scan summary from manifest data."""
        s = manifest.stats
        q = manifest.quality
        dir_count = len(q.per_directory_summary)

        lines: list[str] = []

        # Line 1: file counts
        lines.append(
            f"Scanned {s.total_files:,} files "
            f"({s.text_files:,} text, {s.binary_files:,} binary) "
            f"in {dir_count} {'directory' if dir_count == 1 else 'directories'}."
        )

        # Line 2: support and quality
        specialist_count = sum(
            1 for f in manifest.files
            if f.specialist_metadata is not None
        )
        quality_parts = [f"{q.clean_files:,} clean"]
        if q.degraded_files:
            quality_parts.append(f"{q.degraded_files:,} degraded")
        if q.error_files:
            quality_parts.append(f"{q.error_files:,} errors")
        quality_line = ", ".join(quality_parts)
        # v1.19: aggregate safety flags by NAME (not a bare count) — deterministic.
        flag_counts: dict[str, int] = {}
        for r in manifest.files:
            for fl in r.safety_flags:
                flag_counts[fl] = flag_counts.get(fl, 0) + 1
        extras: list[str] = []
        if flag_counts:
            named = ", ".join(f"{name} ×{c}" for name, c in sorted(flag_counts.items()))
            extras.append(f"safety flags: {named}")
        # v1.19: comment on the ambiguous — content-vs-extension MIME mismatches + polyglots
        # are honest signals of uncertainty, not failures; surface them, don't paper over.
        if q.mime_mismatches:
            extras.append(f"{q.mime_mismatches} content-vs-extension MIME "
                          f"mismatch{'es' if q.mime_mismatches != 1 else ''}")
        if q.polyglots_detected:
            extras.append(f"{q.polyglots_detected} polyglot{'s' if q.polyglots_detected != 1 else ''}")
        if q.duplicate_cluster_count:
            extras.append(f"{q.duplicate_cluster_count} duplicate clusters "
                          f"({q.redundant_file_count} redundant copies)")
        extra_str = ". " + ", ".join(extras) + "." if extras else "."

        lines.append(
            f"{s.supported_files:,} supported "
            f"({specialist_count:,} with specialist metadata). "
            f"{s.unsupported_files:,} unsupported extensions. "
            f"Quality: {quality_line}{extra_str}"
        )

        # Line 3: vector summaries
        vec_parts: list[str] = []
        for v in manifest.vectors_collected:
            vid = v["vector_id"]
            summary = v["summary"]
            if vid == "chatlog":
                matched = summary.get("matched_files", 0)
                turns = summary.get("total_turns", 0)
                speakers = len(summary.get("distinct_speakers", []))
                vec_parts.append(f"chatlog matched {matched} files ({turns} turns, {speakers} speakers)")
            elif vid == "reference_tokens":
                applied = v["applied_to_count"]
                urls = summary.get("url_count", 0)
                paths = summary.get("path_references", 0)
                mentions = summary.get("at_mentions", 0)
                vec_parts.append(f"reference_tokens ran on {applied} files ({urls:,} URLs, {paths:,} paths, {mentions:,} @mentions)")
            elif vid == "author_aggregate":
                distinct = summary.get("distinct_authors", 0)
                applied = v["applied_to_count"]
                if distinct > 0:
                    vec_parts.append(f"author_aggregate found {distinct} distinct authors across {applied} files")
            elif vid == "filename_patterns":
                applied = v["applied_to_count"]
                any_count = summary.get("files_with_any_pattern", 0)
                if any_count > 0:
                    vec_parts.append(f"filename_patterns matched {any_count} of {applied} files")
            elif vid == "provenance":   # v1.19: the vector the old summary skipped
                toolchains = summary.get("toolchains", [])
                applied = v["applied_to_count"]
                if toolchains:
                    # TRUE total — toolchains[] is truncated to top_n (leg-4/Codex undercount)
                    total = summary.get("distinct_toolchains", len(toolchains))
                    top = toolchains[0]["name"]   # already count-sorted
                    vec_parts.append(f"provenance found {total} toolchain"
                                     f"{'s' if total != 1 else ''} across {applied} files (top: {top})")
        if vec_parts:
            lines.append("Vectors: " + ". ".join(vec_parts) + ".")

        # v1.19: capture metadata — geotagged count (from safety flags) + distinct capture
        # devices (image/video make+model). Surfaces the v1.16–v1.18 story the old summary missed.
        geo = flag_counts.get("geotagged", 0)
        devices = sorted({
            f"{(md.get('make') or '').strip()} {(md.get('model') or '').strip()}".strip()
            for r in manifest.files
            if r.specialist_metadata
            for ns in ("image", "video")
            for md in [r.specialist_metadata.get(ns)]
            if isinstance(md, dict) and (md.get("make") or md.get("model"))   # leg-4: guard non-dict
        })
        cap_parts: list[str] = []
        if geo:
            cap_parts.append(f"{geo} geotagged")
        if devices:
            shown = ", ".join(devices[:5]) + (f" +{len(devices) - 5} more" if len(devices) > 5 else "")
            cap_parts.append(f"captured by {shown}")
        if cap_parts:
            lines.append("Capture: " + "; ".join(cap_parts) + ".")

        # v1.19: preservation (provisional) — files in non-current formats, the migration signal.
        obs = sum(1 for r in manifest.files
                  if r.preservation and r.preservation.get("format_obsolescence") not in (None, "current"))
        if obs:
            mig = sum(1 for r in manifest.files
                      if r.preservation and r.preservation.get("migration_recommended"))
            note = f"Preservation: {obs} file{'s' if obs != 1 else ''} in non-current formats"
            lines.append(note + (f" ({mig} migration-recommended)." if mig else "."))

        # Line 4: top directories
        if q.per_directory_summary:
            top_dirs = sorted(q.per_directory_summary, key=lambda d: -d["total_files"])[:3]
            dir_strs = [f"{d['directory'] or '(root)'} ({d['total_files']:,})" for d in top_dirs]
            lines.append("Largest directories: " + ", ".join(dir_strs) + ".")

        # v1.10 (provisional): surface top authors — pure re-display of the
        # already-computed, already-sorted author_aggregate vector (no new data).
        aa = next((v for v in manifest.vectors_collected
                   if v.get("vector_id") == AUTHOR_AGGREGATE_VECTOR_ID), None)
        top_authors = (aa or {}).get("summary", {}).get("top_authors") or []
        if top_authors:
            who = ", ".join(f"{name} ({count})" for name, count in top_authors[:5])
            lines.append(f"Top authors: {who}.")

        return "\n\n".join(lines)

    def _build_context(self) -> ScanContext:
        # v1.12.1 red-team S5.3 + Codex P2 (PR #56): a dependency's `__version__`
        # attribute may be a non-string object (hostile install, monkeypatched test
        # env, packaging anomaly). Two issues:
        #   1. Storing it raw breaks `compute_manifest_checksum`'s `json.dumps` →
        #      Pillar-1 contract break (manifest emission fails).
        #   2. Coercing via `str()` is NOT sufficient — for Mock/bare-object cases,
        #      `str(v)` returns the default repr like "<Mock id='...'>" or
        #      "<class at 0x...>" which embeds a memory address. The address varies
        #      across processes → `manifest_checksum` becomes non-deterministic →
        #      same Pillar-1 break in a different shape.
        # The combined fix: try `str()`, but reject angle-bracket-bounded results
        # (the universal shape of default object reprs) and fall back to "unknown".
        def _dep_version_str(v: object) -> str:
            if v is None:
                return "unknown"
            try:
                s = str(v)
            except Exception:
                return "unknown"
            # Default object reprs are uniformly "<...>" — catches Mock, bare object(),
            # any class without a custom __str__. Real version strings ("1.2.3",
            # "48.0.0", "0.7.1-dev") never have this shape.
            if s.startswith("<") and s.endswith(">"):
                return "unknown"
            return s

        deps: dict[str, dict[str, Any]] = {}
        # magic / libmagic
        if magic:
            magic_ver: str | None = None
            try:
                magic_ver = str(magic.Magic(mime=True).from_buffer(b""))  # type: ignore
                # Try to get the actual libmagic version
                if hasattr(magic, '__version__'):
                    magic_ver = magic.__version__
                elif hasattr(magic, 'version'):
                    magic_ver = str(magic.version())
                else:
                    magic_ver = "unknown"
            except Exception:
                magic_ver = "unknown"
            deps["magic"] = {"available": True, "version": _dep_version_str(magic_ver)}
        else:
            deps["magic"] = {"available": False, "version": None}
        # chardet
        if chardet:
            chardet_ver = getattr(chardet, "__version__", "unknown")
            deps["chardet"] = {"available": True, "version": _dep_version_str(chardet_ver)}
        else:
            deps["chardet"] = {"available": False, "version": None}
        # PyYAML
        if yaml:
            yaml_ver = getattr(yaml, "__version__", "unknown")
            deps["yaml"] = {"available": True, "version": _dep_version_str(yaml_ver)}
        else:
            deps["yaml"] = {"available": False, "version": None}
        # olefile
        if olefile:
            olefile_ver = getattr(olefile, "__version__", "unknown")
            deps["olefile"] = {"available": True, "version": _dep_version_str(olefile_ver)}
        else:
            deps["olefile"] = {"available": False, "version": None}
        # defusedxml
        if _defusedxml_available:
            try:
                import defusedxml
                dxml_ver = getattr(defusedxml, "__version__", "unknown")
            except Exception:
                dxml_ver = "unknown"
            deps["defusedxml"] = {"available": True, "version": _dep_version_str(dxml_ver)}
        else:
            deps["defusedxml"] = {"available": False, "version": None}
        # pypdf (v1.8): its presence/version changes object-stream page_count/Info
        # (and the `pdf.parser` tier), so it MUST be in the context that explains
        # cross-environment variance — capability-locked determinism (review catch).
        if pypdf is not None:
            deps["pypdf"] = {"available": True, "version": _dep_version_str(getattr(pypdf, "__version__", "unknown"))}
        else:
            deps["pypdf"] = {"available": False, "version": None}
        # cryptography (v1.12): pypdf needs it to decrypt AES-256/V5 PDFs (the Caltrans
        # 2025 spec class). Without it, AES decrypt raises DependencyError → no producer
        # / page_count / extraction_permission_bypassed on those PDFs. Same Pillar-1
        # logic as pypdf — leg-1 review #3/#8.
        try:
            import cryptography as _crypto
            deps["cryptography"] = {"available": True, "version": _dep_version_str(getattr(_crypto, "__version__", "unknown"))}
        except ImportError:
            deps["cryptography"] = {"available": False, "version": None}

        return ScanContext(
            logic_version=LOGIC_VERSION,
            scanner_version=SCANNER_VERSION,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            platform=sys.platform,
            dependencies=deps,
        )

    def _compute_stats(self, records: list[FileRecord]) -> ScanStats:
        # supported ⟺ NOT flagged unsupported_extension AND NOT a stat-failure record. The single
        # source of truth: scan_file emits unsupported_extension iff content didn't identify the
        # file, so "not flagged" == "recognized (text or binary, v1.22) or extension-listed". The
        # ONLY not-flagged record that isn't supported is the v1.9.1 stat-failure early-return —
        # it skips the emission site (octet-stream mime, no flag), so it's carved out explicitly.
        # (v1.22 replaced the old `_is_recognized_text` re-derivation, which only knew TEXT and so
        # would under-count a recognized BINARY as unsupported — drift from the emission.)
        supported = sum(
            1 for r in records
            if not any(e.code == ERR_UNSUPPORTED_EXTENSION for e in r.errors)
            and not any(e.code == ERR_UNIVERSAL_STAT_FAILED for e in r.errors)
        )
        total = len(records)
        return ScanStats(
            total_files=total,
            supported_files=supported,
            unsupported_files=total - supported,
            text_files=sum(1 for r in records if not r.is_binary),
            binary_files=sum(1 for r in records if r.is_binary),
            requires_vision=sum(1 for r in records if r.requires_vision),
            requires_specialist_tool=sum(1 for r in records if r.requires_specialist_tool),
        )

    def _compute_quality(self, records: list[FileRecord]) -> ScanQuality:
        total = len(records)
        error_files = sum(1 for r in records if any(e.code == ERR_UNIVERSAL_STAT_FAILED for e in r.errors))
        mime_mismatches = sum(1 for r in records if not r.mime_analysis.matches_extension)
        polyglots = sum(1 for r in records if r.is_polyglot)
        specialist_failures = sum(1 for r in records if any(e.code in SPECIALIST_FAILURE_CODES for e in r.errors))
        unsupported = sum(1 for r in records if any(e.code == ERR_UNSUPPORTED_EXTENSION for e in r.errors))
        safety = sum(1 for r in records if r.safety_flags)
        chatlog_count = sum(1 for r in records if r.is_chatlog)
        degraded = sum(1 for r in records
                       if not any(e.code == ERR_UNIVERSAL_STAT_FAILED for e in r.errors)
                       and (r.errors or not r.mime_analysis.matches_extension))
        clean = total - degraded - error_files
        # v0.9: per-directory aggregation (spec §4.2)
        dir_groups: dict[str, list[FileRecord]] = {}
        for r in records:
            dir_groups.setdefault(r.stage_folder, []).append(r)
        per_dir_summary: list[dict[str, Any]] = []
        for dirname in sorted(dir_groups):
            group = dir_groups[dirname]
            per_dir_summary.append({
                "directory": dirname,
                "total_files": len(group),
                "chatlog_files": sum(1 for r in group if r.is_chatlog),
                "safety_flags_files": sum(1 for r in group if r.safety_flags),
                "mime_mismatches": sum(1 for r in group if not r.mime_analysis.matches_extension),
                "polyglots_detected": sum(1 for r in group if r.is_polyglot),
                "specialist_failures": sum(1 for r in group if any(e.code in SPECIALIST_FAILURE_CODES for e in r.errors)),
                "unsupported_extensions": sum(1 for r in group if any(e.code == ERR_UNSUPPORTED_EXTENSION for e in r.errors)),
            })

        # v1.1: duplicate clustering — group files by identical content checksum.
        # Reuses checksum_sha256 (also used by delta). count >= 2 only.
        checksum_groups: dict[str, list[FileRecord]] = {}
        for r in records:
            if not r.checksum_sha256:
                continue  # skip files that failed to stat/checksum (empty digest)
            checksum_groups.setdefault(r.checksum_sha256, []).append(r)
        duplicate_clusters: list[dict[str, Any]] = []
        for checksum, group in checksum_groups.items():
            if len(group) < 2:
                continue
            duplicate_clusters.append({
                "checksum_sha256": checksum,
                "size_bytes": group[0].size_bytes,
                "count": len(group),
                "paths": sorted(r.path for r in group),
            })
        # Deterministic order: count desc, then checksum asc (checksum is a
        # unique per-cluster tiebreaker, so the order is total).
        duplicate_clusters.sort(key=lambda c: (-c["count"], c["checksum_sha256"]))
        duplicate_cluster_count = len(duplicate_clusters)
        redundant_file_count = sum(c["count"] - 1 for c in duplicate_clusters)

        # v1.1: per-specialist stats — {tool: {attempted, succeeded, failed}}.
        # Only meaningful when specialists ran; empty object otherwise.
        specialist_stats: dict[str, dict[str, int]] = {}
        if self.config.enable_specialists:
            for r in records:
                if not r.requires_specialist_tool or not r.specialist_tool:
                    continue
                bucket = specialist_stats.setdefault(
                    r.specialist_tool, {"attempted": 0, "succeeded": 0, "failed": 0})
                bucket["attempted"] += 1
                if any(e.code in SPECIALIST_FAILURE_CODES for e in r.errors):
                    bucket["failed"] += 1
                else:
                    bucket["succeeded"] += 1
            specialist_stats = {k: specialist_stats[k] for k in sorted(specialist_stats)}

        return ScanQuality(
            total_files=total,
            clean_files=clean,
            degraded_files=degraded,
            error_files=error_files,
            mime_mismatches=mime_mismatches,
            polyglots_detected=polyglots,
            specialist_failures=specialist_failures,
            unsupported_extensions=unsupported,
            safety_flags=safety,
            chatlog_files=chatlog_count,
            per_directory_summary=per_dir_summary,
            duplicate_clusters=duplicate_clusters,
            duplicate_cluster_count=duplicate_cluster_count,
            redundant_file_count=redundant_file_count,
            specialist_stats=specialist_stats,
        )

    def _compute_routing_summary(self, records: list[FileRecord]) -> RoutingSummary:
        return RoutingSummary(
            baseline_ready=sum(1 for r in records if not r.is_binary and not r.requires_specialist_tool),
            binary_only=sum(1 for r in records if r.is_binary and not r.requires_vision and not r.requires_specialist_tool),
            requires_vision=sum(1 for r in records if r.requires_vision),
            requires_specialist_tool=sum(1 for r in records if r.requires_specialist_tool),
        )

    def _compute_delta(self, records: list[FileRecord]) -> DeltaRecord | None:
        if not self.config.previous_manifest:
            return None
        prev_path = Path(self.config.previous_manifest)
        if not prev_path.is_file():
            return None
        try:
            prev_data = json.loads(prev_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        prev_scan_id = prev_data.get("meta", {}).get("scan_id", "")
        prev_checksum = prev_data.get("manifest_checksum")
        prev_files: dict[str, str] = {}
        for f in prev_data.get("files", []):
            p = f.get("path")
            if p is not None:
                prev_files[p] = f.get("checksum_sha256", "")

        current_files: dict[str, str] = {r.path: r.checksum_sha256 for r in records}

        added = sorted(p for p in current_files if p not in prev_files)
        removed = sorted(p for p in prev_files if p not in current_files)
        modified = sorted(
            p for p in current_files
            if p in prev_files and current_files[p] != prev_files[p]
        )
        unchanged = sorted(
            p for p in current_files
            if p in prev_files and current_files[p] == prev_files[p]
        )

        # rescan_candidates: paths from previous manifest with specialist failures
        # that still exist in the current scan
        rescan_candidates: list[str] = []
        for f in prev_data.get("files", []):
            p = f.get("path")
            if p is None:
                continue
            if p not in current_files:
                continue
            errors = f.get("errors", [])
            if any(e.get("code") in SPECIALIST_FAILURE_CODES for e in errors):
                rescan_candidates.append(p)
        rescan_candidates.sort()

        return DeltaRecord(
            previous_scan_id=prev_scan_id,
            previous_manifest_checksum=prev_checksum,
            added=added,
            modified=modified,
            unchanged=unchanged,
            removed=removed,
            rescan_candidates=rescan_candidates,
        )

    def iter_files(self, root: Path) -> Iterable[Path]:
        root_resolved = root.resolve()
        # Sort by the posix string, NOT the Path object: WindowsPath sorts
        # case-INSENSITIVELY (via _str_normcase), so `sorted(rglob)` gives a different
        # file order on Windows than on Linux — a cross-platform determinism break
        # (Pillar 1). as_posix() is case-sensitive + forward-slash → identical order on
        # every OS (and byte-identical to the prior order on POSIX, where str==as_posix).
        for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
            if path.is_file():
                # rglob/is_file() FOLLOW symlinks. A symlink whose target resolves
                # OUTSIDE the scan tree would read that file's bytes/hash into the
                # manifest (a tree-escape — e.g. /etc/passwd) and can break
                # determinism if the target mutates. Enforce resolve()-containment,
                # mirroring _is_safe_zip_entry for ZIP paths (red-team #6).
                if path.is_symlink():
                    try:
                        if not path.resolve().is_relative_to(root_resolved):
                            continue
                    except OSError:
                        continue   # broken/looping symlink → skip, never raise
                rel = path.relative_to(root)
                if self.config.exclude_hidden and any(
                    part.startswith(".") for part in rel.parts
                ):
                    continue
                if self._ignore_patterns and self._is_ignored(rel):
                    continue
                yield path

    def scan_file(self, path: Path) -> FileRecord:
        errors: list[ErrorRecord] = []

        # v1.9.1: compute rel_path defensively and SEPARATELY from the stat I/O, so a
        # stat failure keeps the correct source-relative path (Gemini F2 — the old
        # combined-try flattened a subdir file's path to its bare filename, a bug, not
        # a §1.18 requirement). Only fall back to the bare filename if relative_to
        # itself fails (path genuinely not under source_dir).
        try:
            # source_dir is resolve()d-absolute in __init__ and iter_files yields
            # absolute paths, so .absolute() is a no-op for the production flow (zero
            # output change) — it only rescues a CWD-relative path passed directly to
            # scan_file from flattening (Gemini PR #48). No I/O (unlike resolve()).
            rel_path = path.absolute().relative_to(self.source_dir)
        except Exception:
            rel_path = Path(path.name)
        try:
            stat = path.stat()
        except Exception as exc:
            # Universal tier failure — return a minimal record per §1.18 (path preserved)
            errors.append(ErrorRecord(
                code=ERR_UNIVERSAL_STAT_FAILED,
                message=str(exc),
                stage="universal",
            ))
            # v0.10: filename_patterns still runs on error path (only needs filename)
            # v1.9: scan_file is PURE — corpus counters are derived from the records
            # afterwards (_aggregate_file_counters), so the per-file pass can parallelize.
            fp = self._extract_filename_patterns(path.name)
            return FileRecord(
                path=rel_path.as_posix(),
                filename=path.name,
                extension=path.suffix.lower(),
                mime_type="application/octet-stream",
                size_bytes=0,
                created_at=None,
                modified_at="",     # stat failed → mtime unknown. Deterministic "" (matches
                                    # checksum_sha256="" on this degraded record) — NOT wall-clock
                                    # now_iso, which broke manifest_checksum determinism. Stays a
                                    # non-null str so the frozen contract is unchanged (Gemini F2).
                checksum_sha256="",
                stage_folder="",
                directory_depth=0,
                encoding=None,
                is_binary=True,
                requires_vision=False,
                requires_specialist_tool=False,
                specialist_tool=None,
                sidecar_exists=False,
                frontmatter=FrontmatterRecord(),
                tags=[],
                asset_matches=[],
                content_preview=None,
                structural=StructuralRecord(),
                mime_analysis=MimeAnalysisRecord(
                    detected_mime=None,
                    extension_mime=None,
                    matches_extension=False,
                ),
                specialist_metadata=None,
                filename_patterns=fp,
                preservation=self._extract_preservation(path.suffix),
                signal_provenance={},
                errors=errors,
            )

        extension = path.suffix.lower()
        provenance: dict[str, Any] = {}
        eff = self.config.effective_for(extension)

        # read_sample / hash_file do bare open() — an unreadable file (permissions,
        # vanished, special file) must degrade to a FileRecord+ErrorRecord, not abort
        # the whole scan (red-team #5; these calls sit outside the stat try above).
        read_failed = False
        try:
            sample = self.read_sample(path)
        except OSError as exc:
            errors.append(ErrorRecord(ERR_UNIVERSAL_READ_FAILED, str(exc), "universal"))
            sample = b""
            read_failed = True
        mime_type, mime_prov = self.detect_mime(path, sample, errors)
        provenance["mime_type"] = asdict(mime_prov)
        mime_analysis = self.analyze_mime(path, mime_type, extension)
        provenance["mime_analysis.matches_extension"] = asdict(ProvenanceEntry(
            layer="derived", method="analyze_mime",
            trigger="mismatch" if not mime_analysis.matches_extension else "match",
            inputs=["mime_type"],
            detail={"detected": mime_analysis.detected_mime, "extension": mime_analysis.extension_mime},
        ))
        if read_failed:
            checksum = ""          # already known unreadable — don't re-open just to fail (gemini PR review)
        else:
            try:
                checksum = self.hash_file(path)
            except OSError as exc:
                errors.append(ErrorRecord(ERR_UNIVERSAL_READ_FAILED, str(exc), "universal"))
                checksum = ""
        created_at = self.safe_created_at(stat)
        modified_at = self.ts_to_iso(stat.st_mtime)
        stage_folder = rel_path.parts[0] if len(rel_path.parts) > 1 else ""
        directory_depth = max(len(rel_path.parts) - 1, 0)
        sidecar_exists = self.detect_sidecar(path)

        file_signature, format_signatures, is_polyglot = self.scan_signatures(sample)
        is_binary, binary_prov = self.detect_binary(sample, mime_type)
        provenance["is_binary"] = asdict(binary_prov)
        specialist_tool = SPECIALIST_TOOLS.get(extension)
        requires_specialist_tool = specialist_tool is not None
        provenance["requires_specialist_tool"] = asdict(ProvenanceEntry(
            layer="derived", method="specialist_tools_registry",
            trigger="registry_match" if requires_specialist_tool else "registry_none",
            detail=f"{extension} -> {specialist_tool}" if specialist_tool else None,
        ))
        requires_vision, vision_prov = self.detect_requires_vision(
            path, sample, mime_type, extension, is_binary
        )
        provenance["requires_vision"] = asdict(vision_prov)

        # v1.21→v1.22: recognized = CONTENT positively identified the file. `unsupported_extension`
        # fires ONLY when content detection genuinely failed — octet-stream, an extension-fallback
        # MIME (both content tiers failed → /etc/mime.types guess), or unreadable bytes. v1.21 did
        # this for TEXT; v1.22 generalizes it to BINARY (the candidate-scan finding: 944/1119 flags
        # were on positively-identified binary — video/x-msvideo, application/zip, audio/mpeg, …).
        # Recognition-only — recognition != extraction (a recognized .avi gets no specialist).
        #  - `content_identified`: non-octet, content-derived (trigger != extension_fallback), not
        #    read_failed. octet-stream / extension_fallback / read_failed = NOT identified. The
        #    §6.2a no-libmagic gap is KEPT: a binary the pure-Python sniff can't match falls to
        #    extension_fallback and stays flagged — recognition rests on OBSERVED content, never the
        #    platform mime database (/etc/mime.types varies cross-machine). [v1.21 leg-4 Codex P2]
        #  - TEXT MIMEs keep the v1.21 lying-text/plain veto (BOM or printable ratio): libmagic's
        #    `text/plain` is a loose catch-all over NUL-bearing bytes, and the BOM arm rescues
        #    UTF-16/32 text. BINARY MIMEs need no veto — a video/x-msvideo / application/zip is a
        #    content SIGNATURE match, a positive ID by construction (even a slightly-wrong binary
        #    MIME still means "identified as *something*", which is all the flag should care about).
        content_identified = (
            bool(mime_type)
            and mime_type != "application/octet-stream"
            and mime_prov.trigger != "extension_fallback"
            and not read_failed
        )
        recognized = content_identified and (
            not _is_recognized_text(mime_type)
            or _detect_unicode_bom(sample) is not None
            or self.looks_like_text(sample)
        )
        if extension not in SUPPORTED_EXTENSIONS and not recognized:
            errors.append(ErrorRecord(
                code=ERR_UNSUPPORTED_EXTENSION,
                message=f"Could not identify '{extension or path.name}' (extension not recognized and content not identified)",
                stage="universal",
            ))

        encoding: str | None = None
        preview: str | None = None
        tags: list[str] = []
        asset_matches: list[str] = []
        frontmatter = FrontmatterRecord()
        is_chatlog = False
        reference_tokens_result: dict[str, int] | None = None
        # v0.8: hoisted out of the specialist block so chatlog extraction
        # (which lives in the text-handling block above the extension-based
        # dispatch) can populate it directly.
        specialist_metadata: dict[str, Any] | None = None
        structural = StructuralRecord(
            filename_date=self.extract_filename_date(path.name),
        )

        if not is_binary:
            try:
                encoding, text, enc_prov = self.decode_text(sample, path, eff["baseline_max_bytes"])
                provenance["encoding"] = asdict(enc_prov)
                preview = self.make_preview(text, eff["preview_max_chars"])
                tags = self.extract_tags(text)
                structural.technology_hints = self.detect_technology(text)

                # v0.8 Phase 1: chatlog content-based detection.
                # Activates for .txt / .md / .mdx files when content patterns
                # suggest conversational or document-evolution structure. This
                # is the first content-detected (not extension-based) flag in
                # the scanner. Always runs when we have decoded text, even if
                # enable_specialists=False — detection is cheap.
                if extension in {".txt", ".md", ".mdx", ".jsonl", ".json"}:
                    is_chatlog = self._detect_chatlog_pattern(text)
                    provenance["is_chatlog"] = asdict(ProvenanceEntry(
                        layer="derived",
                        method="_detect_chatlog_pattern",
                        trigger="content_pattern_match" if is_chatlog else "content_pattern_none",
                        inputs=["encoding"],
                    ))
                    # v0.8 Phase 2: when chatlog activates, override the
                    # specialist_tool and requires_specialist_tool flags. The
                    # initial values came from the extension-keyed
                    # SPECIALIST_TOOLS lookup (which returns None for
                    # .txt/.md/.mdx); content-detected activation supersedes
                    # the extension-based registry.
                    if is_chatlog:
                        specialist_tool = CHATLOG_TOOL
                        requires_specialist_tool = True
                        provenance["requires_specialist_tool"] = asdict(ProvenanceEntry(
                            layer="derived",
                            method="content_detected_specialist",
                            trigger="chatlog_activation",
                            inputs=["is_chatlog"],
                            detail=f"{CHATLOG_TOOL} (content-detected)",
                        ))
                        # v0.8 Phase 2: extraction itself is gated by
                        # enable_specialists. The detection above runs always,
                        # but the chatlog metadata only populates when
                        # specialists are enabled and the MIME guard accepts
                        # the file's content type.
                        if self.config.enable_specialists:
                            chatlog_guard = SPECIALIST_MIME_GUARD.get(CHATLOG_NAMESPACE, set())
                            if mime_type not in chatlog_guard:
                                errors.append(ErrorRecord(
                                    code=ERR_SPECIALIST_PROBE_FAILED,
                                    message=f"mime_type {mime_type} does not match expected formats for {CHATLOG_NAMESPACE} specialist — skipped",
                                    stage="specialist",
                                    detail={"reason": "mime_guard_mismatch", "mime_type": mime_type,
                                            "expected": sorted(chatlog_guard)},
                                ))
                            else:
                                chatlog_meta = self._extract_chatlog_metadata(text)
                                if chatlog_meta is None:
                                    errors.append(ErrorRecord(
                                        code=ERR_SPECIALIST_PROBE_FAILED,
                                        message=f"specialist returned null for {CHATLOG_TOOL}",
                                        stage="specialist",
                                        detail={"reason": "empty or unparseable chatlog text",
                                                "text_chars": len(text)},
                                    ))
                                else:
                                    if specialist_metadata is None:
                                        specialist_metadata = {}
                                    specialist_metadata[CHATLOG_NAMESPACE] = chatlog_meta
                                    # Per-field provenance for each top-level
                                    # chatlog field. Mirrors the loop in the
                                    # extension-based dispatch below; chatlog
                                    # operates on the full bounded text rather
                                    # than the 8 KB sample, so the trigger is
                                    # `bounded_text` and the detail records the
                                    # text length consumed.
                                    text_len = len(text)
                                    for key in chatlog_meta:
                                        provenance[f"specialist_metadata.{CHATLOG_NAMESPACE}.{key}"] = asdict(ProvenanceEntry(
                                            layer="derived",
                                            method="_extract_chatlog_metadata",
                                            trigger="bounded_text",
                                            detail={"tool": CHATLOG_TOOL, "text_chars": text_len},
                                        ))

                # v0.9: reference_tokens vector — runs on every text-eligible file
                if extension in REFERENCE_TOKENS_EXTENSIONS:
                    ref_tokens = self._extract_reference_tokens(text)
                    # Will be set on the FileRecord below via reference_tokens_result
                    reference_tokens_result = ref_tokens
                    # v1.9: corpus counters derived later (_aggregate_file_counters) so
                    # scan_file stays pure — see the result on the FileRecord below.
                    provenance["reference_tokens"] = asdict(ProvenanceEntry(
                        layer="derived",
                        method="_extract_reference_tokens",
                        trigger="text_eligible",
                        detail={"vector_id": REFERENCE_TOKENS_VECTOR_ID},
                    ))
                else:
                    reference_tokens_result = None

                if extension in {".md", ".mdx"}:
                    frontmatter = self.extract_frontmatter(text)
                    asset_matches = self.extract_assets(text)
                    structural.title = self.extract_md_title(text)
                    structural.heading_structure = self.extract_heading_structure(text)
                    if frontmatter.exists:
                        tags = sorted(set(tags + self.tags_from_frontmatter(frontmatter.raw or "")))
                    provenance["structural.title"] = asdict(ProvenanceEntry(
                        layer="derived", method="extract_md_title",
                        trigger="markdown_h1",
                    ))

                elif extension in {".html", ".htm"}:
                    structural.title = self.extract_html_title(text)
                    provenance["structural.title"] = asdict(ProvenanceEntry(
                        layer="derived", method="extract_html_title",
                        trigger="html_title_tag",
                    ))

                elif extension == ".csv":
                    structural.csv_headers = self.extract_csv_headers(text)

                elif extension in {".yaml", ".yml"}:
                    structural.document_keys = self.extract_yaml_keys(text)
                    provenance["structural.document_keys"] = asdict(ProvenanceEntry(
                        layer="derived", method="extract_yaml_keys",
                        trigger="yaml_line_parse",
                    ))

                elif extension == ".json":
                    structural.document_keys = self.extract_json_keys(text)
                    provenance["structural.document_keys"] = asdict(ProvenanceEntry(
                        layer="derived", method="extract_json_keys",
                        trigger="json_loads",
                    ))

                elif extension in {".xml", ".vx"}:
                    structural.document_keys = self.extract_xml_keys(text)
                    # Only record parse error if file wasn't truncated by baseline cap
                    file_was_truncated = stat.st_size > max(eff["baseline_max_bytes"], self.config.sample_size)
                    if not structural.document_keys and not file_was_truncated:
                        try:
                            xml_fromstring(text)
                        except Exception as xml_exc:
                            errors.append(ErrorRecord(
                                code=ERR_XML_PARSE_FAILED,
                                message=f"XML parsing failed: {type(xml_exc).__name__}",
                                stage="structural",
                            ))
                    provenance["structural.document_keys"] = asdict(ProvenanceEntry(
                        layer="derived", method="extract_xml_keys",
                        trigger="xml_etree",
                    ))

                elif extension == ".toml":
                    structural.document_keys = self.extract_toml_keys(text)
                    file_was_truncated = stat.st_size > max(eff["baseline_max_bytes"], self.config.sample_size)
                    if not structural.document_keys and text.strip() and not file_was_truncated:
                        if tomllib:
                            try:
                                tomllib.loads(text)
                            except Exception as toml_exc:
                                errors.append(ErrorRecord(
                                    code=ERR_TOML_PARSE_FAILED,
                                    message=f"TOML parsing failed: {type(toml_exc).__name__}",
                                    stage="structural",
                                ))
                    provenance["structural.document_keys"] = asdict(ProvenanceEntry(
                        layer="derived", method="extract_toml_keys",
                        trigger="tomllib",
                    ))

            except Exception as exc:
                errors.append(ErrorRecord(
                    code=ERR_BASELINE_DECODE_FAILED,
                    message=str(exc),
                    stage="baseline",
                ))
        else:
            encoding = None
            provenance["encoding"] = asdict(ProvenanceEntry(
                layer="derived", method="decode_text",
                trigger="not_applicable",
                detail="binary_file",
            ))

        # Safety flags — checked before specialist, independent of MIME guard.
        # DOCX macro detection requires reading the ZIP central directory; this
        # is gated behind enable_specialists to avoid extra I/O on baseline scans.
        zip_entries = None
        if extension == ".docx" and self.config.enable_specialists:
            zip_entries = self._get_zip_entries(path, eff["specialist_budget"])
        safety_flags = self.detect_safety_flags(extension, sample, zip_entries)

        # v0.10: filename_patterns vector — runs on every file
        # v1.9: corpus counters derived later (_aggregate_file_counters); scan_file is pure.
        fp = self._extract_filename_patterns(path.name)

        if self.config.enable_specialists:
            try:
                self.run_specialist_probe(path, extension, errors)
            except Exception as exc:
                errors.append(ErrorRecord(
                    code=ERR_SPECIALIST_PROBE_FAILED,
                    message=str(exc),
                    stage="specialist",
                ))
            try:
                # MIME guard: skip specialist if content doesn't match expected format
                ns = SPECIALIST_NAMESPACE.get(extension)
                guard = SPECIALIST_MIME_GUARD.get(ns, set()) if ns else set()
                # v1.22.1: fold in any per-extension extra MIMEs (e.g. `.eml` accepts text/plain
                # & text/html — libmagic types body-dominated mail as text, not message/rfc822).
                # Extension-specific, so a lying text-typed `.msg` in the same namespace stays out.
                guard = guard | EXTENSION_EXTRA_GUARD_MIMES.get(extension, set())
                # When MIME was extension-derived (fallback), also verify via format_signatures
                mime_from_extension = provenance.get("mime_type", {}).get("trigger") == "extension_fallback"
                if mime_from_extension and guard and format_signatures:
                    # Check if any detected signature matches what the guard expects
                    detected_formats = {s["format"] for s in format_signatures}
                    if not detected_formats & guard:
                        guard_failed = True
                    else:
                        guard_failed = False
                elif mime_from_extension and guard and not format_signatures:
                    # Extension-derived MIME, no corroborating magic signature. A binary
                    # format (pdf/docx/xls) WOULD have a signature, so its absence is
                    # suspicious → distrust. But a TEXT-based, self-validating namespace
                    # (email: .eml message/rfc822) has no signature even when genuine —
                    # trust it when the resolved MIME is a known text-format MIME
                    # (v1.15.2). Gated by MIME, NOT namespace, so a lying text `.msg`
                    # (binary OLE2, same namespace, vnd.ms-outlook) stays distrusted.
                    # `sample` must be non-empty: an unreadable/TOCTOU file leaves
                    # sample=b'' (universal_read_failed) and parsing empty bytes would
                    # yield an all-null "successful" extraction — skip it (leg-4/codex).
                    if mime_type in EXTENSION_TRUSTED_MIMES and mime_type in guard and sample:
                        guard_failed = False
                    else:
                        guard_failed = True
                elif guard and mime_type not in guard:
                    guard_failed = True
                else:
                    guard_failed = False
                if guard_failed:
                    errors.append(ErrorRecord(
                        code=ERR_SPECIALIST_PROBE_FAILED,
                        message=f"mime_type {mime_type} does not match expected formats for {ns} specialist — skipped",
                        stage="specialist",
                    ))
                    raw_metadata = None
                else:
                    raw_metadata = self.extract_specialist_metadata(path, extension, sample, eff["specialist_budget"])
                if raw_metadata is None and extension in SPECIALIST_TOOLS and (not guard or mime_type in guard):
                    errors.append(ErrorRecord(
                        code=ERR_SPECIALIST_PROBE_FAILED,
                        message=f"specialist returned null for {extension}",
                        stage="specialist",
                    ))
                if raw_metadata is not None:
                    # Pop transient specialist markers BEFORE the metadata is registered
                    # in the manifest. (v1.12 leg-1 review #3/#8 + #12.)
                    # - `_safety_extras` → merged into FileRecord.safety_flags
                    #   (cross-format stable surface). v1.12 used it for the PDF
                    #   `extraction_permission_bypassed` disclosure; v1.16 reuses the same
                    #   channel for image `geotagged` — so the merge runs for ANY
                    #   specialist, not just `.pdf`.
                    for flag in raw_metadata.pop("_safety_extras", []) or []:
                        if flag not in safety_flags:
                            safety_flags.append(flag)
                    safety_flags = sorted(safety_flags)
                    # - `_pdf_encryption_unsupported` → emits an ErrorRecord per
                    #   v1.12 RFC §4.1 (cryptography-absent on AES-encrypted PDF).
                    if extension == ".pdf":
                        if raw_metadata.pop("_pdf_encryption_unsupported", False):
                            errors.append(ErrorRecord(
                                code=ERR_PDF_ENCRYPTION_UNSUPPORTED,
                                message="pypdf raised DependencyError on AES decrypt; install file-observer[pdf] (now includes cryptography) to recover producer/page_count on AES-256/V5 PDFs",
                                stage="specialist",
                            ))
                    ns = SPECIALIST_NAMESPACE.get(extension)
                    if ns:
                        specialist_metadata = {ns: raw_metadata}
                    else:
                        specialist_metadata = raw_metadata
                    tool = SPECIALIST_TOOLS.get(extension, "unknown")
                    # Specialists that read beyond the 8 KB sample declare it as a
                    # deviation so the per-field provenance can't claim the value came
                    # from the bounded sample (leg-4/Codex — provenance-honesty). OOXML
                    # reads the ZIP central directory; the image-EXIF path (v1.16) reads
                    # a bounded 1 MiB head (EXIF/XMP live past the sample).
                    if extension in {".xlsx", ".docx"}:
                        is_deviation = True
                        dev_reason, dev_budget = "zip_central_directory_required", eff["specialist_budget"]
                    elif extension in {".jpg", ".jpeg", ".heic", ".heif", ".avif"}:
                        is_deviation = True
                        dev_reason, dev_budget = "exif_metadata_beyond_sample", self.IMAGE_METADATA_MAX_BYTES
                    elif extension in {".mp4", ".mov", ".m4v"}:
                        is_deviation = True
                        dev_reason, dev_budget = "moov_box_beyond_sample", self.MOOV_MAX_BYTES
                    else:
                        is_deviation = False
                        dev_reason = dev_budget = None
                    ns_prefix = f"specialist_metadata.{ns}." if ns else "specialist_metadata."
                    for key in raw_metadata:
                        prov_key = f"{ns_prefix}{key}"
                        trigger = "bounded_deviation" if is_deviation else "bounded_sample"
                        if raw_metadata[key] is None:
                            trigger = "missing_from_bounds"
                        prov_detail: dict[str, Any] = {"tool": tool}
                        if is_deviation:
                            prov_detail["read_budget_bytes"] = dev_budget
                            prov_detail["reason"] = dev_reason
                        else:
                            prov_detail["sample_size"] = len(sample)
                        provenance[prov_key] = asdict(ProvenanceEntry(
                            layer="derived",
                            method=f"_{extension.lstrip('.')}_specialist",
                            trigger=trigger,
                            detail=prov_detail,
                        ))
            except Exception as exc:
                errors.append(ErrorRecord(
                    code=ERR_SPECIALIST_PROBE_FAILED,
                    message=f"specialist metadata extraction failed: {exc}",
                    stage="specialist",
                ))

            # v0.9: email body chatlog cross-cut (spec §4.1)
            # When email specialist ran successfully, extract body text and
            # test it against the chatlog vector's detection rules.
            if extension in {".eml", ".msg"} and specialist_metadata and "email" in specialist_metadata:
                try:
                    body_text = self._extract_email_body(path, extension, sample)
                    if body_text and self._detect_chatlog_pattern(body_text):
                        body_chatlog = self._extract_chatlog_metadata(body_text)
                        if body_chatlog is not None:
                            specialist_metadata["email"]["body_chatlog"] = body_chatlog
                            provenance["specialist_metadata.email.body_chatlog"] = asdict(ProvenanceEntry(
                                layer="derived",
                                method="_extract_chatlog_metadata",
                                trigger="email_body_crosscut",
                                detail={"vector_id": CHATLOG_VECTOR_ID, "body_chars": len(body_text)},
                            ))
                except Exception as exc:
                    errors.append(ErrorRecord(
                        code=ERR_SPECIALIST_PROBE_FAILED,
                        message=f"email body chatlog cross-cut failed: {exc}",
                        stage="specialist",
                    ))

        return FileRecord(
            path=rel_path.as_posix(),
            filename=path.name,
            extension=extension,
            mime_type=mime_type,
            size_bytes=stat.st_size,
            created_at=created_at,
            modified_at=modified_at,
            checksum_sha256=checksum,
            stage_folder=stage_folder,
            directory_depth=directory_depth,
            encoding=encoding,
            is_binary=is_binary,
            requires_vision=requires_vision,
            requires_specialist_tool=requires_specialist_tool,
            specialist_tool=specialist_tool,
            sidecar_exists=sidecar_exists,
            frontmatter=frontmatter,
            tags=tags,
            asset_matches=asset_matches,
            content_preview=preview,
            structural=structural,
            mime_analysis=mime_analysis,
            specialist_metadata=specialist_metadata,
            file_signature=file_signature,
            format_signatures=format_signatures,
            is_polyglot=is_polyglot,
            is_chatlog=is_chatlog,
            reference_tokens=reference_tokens_result,
            filename_patterns=fp,
            preservation=self._extract_preservation(path.suffix),
            safety_flags=safety_flags,
            signal_provenance=provenance,
            errors=errors,
        )

    def detect_mime(self, path: Path, sample: bytes, errors: list[ErrorRecord]) -> tuple[str, ProvenanceEntry]:
        # Tier 1: libmagic (content-based, primary). Unchanged.
        reason = "libmagic_unavailable"  # accurate label: absent / empty / exception
        if self._magic:
            try:
                detected = self._magic.from_file(str(path))
                if detected:
                    return detected, ProvenanceEntry(
                        layer="raw", method="detect_mime", trigger="libmagic")
                reason = "libmagic_empty"  # present but returned falsy (no exception)
            except Exception:
                reason = "libmagic_exception"
        # Tier 2 (v1.3): pure-Python content-based magic-signature sniff (no libmagic).
        sniffed = self._sniff_mime(sample)
        if sniffed:
            return sniffed, ProvenanceEntry(
                layer="raw", method="detect_mime",
                trigger="magic_signature_fallback", detail={"reason": reason})
        # Tier 3: extension-based inference — genuinely degraded; record exactly
        # one error here (Tier 1/2 do not append, so no duplicate). reason in detail.
        guessed, _ = mimetypes.guess_type(str(path))
        errors.append(ErrorRecord(
            code=ERR_MIME_TYPE_FALLBACK,
            message=f"content-based MIME detection unavailable ({reason}); used extension-based inference",
            stage="universal",
        ))
        return guessed or "application/octet-stream", ProvenanceEntry(
            layer="raw", method="detect_mime",
            trigger="extension_fallback", detail={"reason": reason})

    def analyze_mime(self, path: Path, detected_mime: str, extension: str) -> MimeAnalysisRecord:
        extension_mime, _ = mimetypes.guess_type(f"file{extension}")
        # detected_mime comes from detect_mime() which may be content-based or extension-based
        # For a meaningful comparison, we compare detected vs extension-derived
        if extension_mime is None:
            matches = True  # can't compare when extension has no known MIME
        else:
            matches = detected_mime == extension_mime
        return MimeAnalysisRecord(
            detected_mime=detected_mime,
            extension_mime=extension_mime,
            matches_extension=matches,
        )

    def extract_specialist_metadata(
        self, path: Path, extension: str, sample: bytes, budget: int = 131072
    ) -> dict[str, Any] | None:
        if extension == ".pdf":
            return self._extract_pdf_metadata(path, sample, budget)
        if extension == ".png":
            return self._extract_png_metadata(sample)
        if extension in {".jpg", ".jpeg"}:
            return self._extract_jpeg_metadata(path, sample)
        if extension in {".heic", ".heif", ".avif"}:
            return self._extract_heic_metadata(path, sample)
        if extension in {".mp4", ".mov", ".m4v"}:
            return self._extract_video_metadata(path, sample)
        if extension == ".msg":
            return self._extract_msg_metadata(path)
        if extension == ".eml":
            return self._extract_eml_metadata(sample)
        if extension == ".xlsx":
            meta = self._extract_xlsx_metadata(path, budget)
            if meta is not None:
                meta["format"] = "ooxml"
            return meta
        if extension == ".xls":
            return self._extract_xls_metadata(path)
        if extension == ".docx":
            return self._extract_docx_metadata(path, budget)
        if extension == ".doc":
            return self._extract_doc_metadata(path)
        if extension == ".rtf":
            return self._extract_rtf_metadata(sample)
        return None

    @staticmethod
    def _pdf_scan_region(path: Path, sample: bytes, budget: int) -> bytes:
        """Head sample + a bounded tail (the last ``budget`` bytes) — the regions
        where a PDF's page tree (`/Count`), `/Info` dict, and font/image markers
        live (v1.5). A PDF's xref/trailer/Info are at the file END, not the head,
        so the v1.4 head-only read returned null for nearly all real PDFs. The
        whole file is already read for the checksum, so the tail read is cheap.
        Bounded-observation deviation (head + `budget` tail), declared like the
        XLSX/DOCX 128 KB budget. The unread middle of very large PDFs is the
        accepted limit. Returns sample unchanged on any read error."""
        try:
            size = path.stat().st_size
            if size <= len(sample):
                return sample
            with open(path, "rb") as f:
                f.seek(max(len(sample), size - budget))  # no overlap with head
                tail = f.read(budget)
            return sample + b"\n" + tail
        except OSError:
            return sample

    @staticmethod
    def _pdf_full_or_region(path: Path, sample: bytes) -> bytes:
        """Whole file (≤ PDF_FULL_READ_CAP) for page_count + /Info — so the root
        page tree and trailer Info are found wherever they sit, eliminating the
        unread-middle undercount/null of a tail-only window. Falls back to
        head+tail for very large files. (Specialist tier is opt-in and the file
        is already read for the checksum.)"""
        try:
            if path.stat().st_size <= PDF_FULL_READ_CAP:
                with open(path, "rb") as f:
                    return f.read()
        except OSError:
            return sample
        return Scanner._pdf_scan_region(path, sample, PDF_MARKER_BUDGET)

    @staticmethod
    def _pdf_page_count(full: bytes) -> int | None:
        """Page count = the largest `/Count` belonging to a `/Type /Pages` dict.
        `/Count` is NOT unique to the page tree (`/Outlines`, annotations, AcroForms
        use it too), so it MUST be anchored to `/Type /Pages` — otherwise a
        bookmark count wins (a 10-page PDF with 240 bookmarks reported 240). The
        root `/Pages` carries the largest page count; interior nodes carry partial
        counts; max over the anchored set is the total."""
        counts: list[int] = []
        for m in re.finditer(rb"/Type\s*/Pages\b", full):
            # Scan the enclosing OBJECT (forward to `endobj`, capped), not a fixed
            # byte window or the first `>>`: a flat page tree's /Kids array pushes
            # /Count far past /Type, and a NESTED dict (e.g. /Resources<<…>>) makes
            # the first `>>` close the wrong dict — both broke a fixed/`>>` window
            # (review 2026-06-02). `endobj` bounds the object unambiguously, and a
            # /Pages object's only /Count is the page count. Short backward fallback
            # for the rare /Count-before-/Type ordering.
            close = full.find(b"endobj", m.end())
            fwd_end = close if 0 <= close <= m.end() + 65536 else m.end() + 65536
            cm = re.search(rb"/Count\s+(\d+)", full[m.start():fwd_end])
            if cm is None:
                cm = re.search(rb"/Count\s+(\d+)", full[max(0, m.start() - 512):m.start()])
            if cm:
                counts.append(int(cm.group(1)))
        return max(counts) if counts else None

    # ---- v1.7 structural-anchor reader (PDF) --------------------------------
    @staticmethod
    def _pdf_last_startxref(path: Path, sample: bytes, whole: bytes | None = None) -> int | None:
        """Byte offset of the cross-reference section from the LAST `startxref` in
        the file tail. Linearized PDFs carry an early `startxref` too — the trailing
        one (at EOF) is the authoritative entry point. Uses `whole`'s tail when the
        file was already fully read (no extra open); else seeks the tail."""
        if whole is not None:
            tail = whole[-PDF_STARTXREF_TAIL:]
        else:
            try:
                size = path.stat().st_size
                with open(path, "rb") as f:
                    if size > PDF_STARTXREF_TAIL:
                        f.seek(size - PDF_STARTXREF_TAIL)
                    tail = f.read()
            except OSError:
                tail = sample
        idx = tail.rfind(b"startxref")
        if idx < 0:
            return None
        m = re.search(rb"startxref\s+(\d+)", tail[idx:])
        return int(m.group(1)) if m else None

    @staticmethod
    def _pdf_obj_ref(data: bytes, key: bytes) -> int | None:
        """Object number of an indirect reference `/Key N G R`."""
        m = re.search(re.escape(key) + rb"\s+(\d+)\s+\d+\s+R\b", data)
        return int(m.group(1)) if m else None

    @staticmethod
    def _resolve_obj_region(path: Path, offset: int, whole: bytes | None) -> bytes:
        """A single object's dict region at byte `offset`. Slices the already-read
        whole-file bytes when present (≤ FULL_READ_CAP — the common case, ZERO extra
        I/O); seeks the file only for > cap PDFs (where `whole` is None because the
        full read was skipped). Bounded by PDF_ANCHOR_OBJ_CAP; trimmed at `endobj`."""
        if offset < 0:
            return b""
        if whole is not None:
            chunk = whole[offset:offset + PDF_ANCHOR_OBJ_CAP]
        else:
            try:
                with open(path, "rb") as f:
                    f.seek(offset)
                    chunk = f.read(PDF_ANCHOR_OBJ_CAP)
            except OSError:
                return b""
        end = chunk.find(b"endobj")
        return chunk if end < 0 else chunk[:end]

    @staticmethod
    def _parse_classic_xref(path: Path, sx: int, whole: bytes | None
                            ) -> tuple[dict[int, int], int | None, int | None] | None:
        """Parse the classic xref table(s) → {object_number: byte_offset}, plus the
        /Root and /Info object numbers. Follows /Prev across incremental updates
        (bounded by PDF_XREF_PREV_HOPS); the LATEST section wins per object. Reads
        each section from `whole` (slice) when available, else by seek."""
        offset_map: dict[int, int] = {}
        root_ref: int | None = None
        info_ref: int | None = None
        cur: int | None = sx
        seen: set[int] = set()
        for _ in range(PDF_XREF_PREV_HOPS):
            if cur is None or cur in seen:
                break
            seen.add(cur)
            if whole is not None:
                chunk = whole[cur:]               # in memory — no cap needed; the
                                                  # `trailer` search bounds the parse
                                                  # (a > 1 MB xref table is fine).
            else:
                try:
                    with open(path, "rb") as f:
                        f.seek(cur)
                        chunk = f.read(1 << 20)   # > cap path: ≤1 MB of xref + trailer
                                                  # (a > 1 MB table on a > 64 MB PDF
                                                  # degrades to the v1.5 fallback)
                except OSError:
                    break
            if not re.match(rb"\s*xref\b", chunk):
                break   # not a classic table (e.g. xref stream) — caller handles
            ti = chunk.find(b"trailer")
            table = chunk[:ti] if ti >= 0 else chunk
            obj = 0
            # splitlines() (not split(b"\n")) — PDF xref entries may end in `\r`,
            # `\n`, or `\r\n` (ISO 32000); a CR-only table would otherwise parse as
            # one line and yield no offsets (gemini PR review).
            for raw in table.splitlines():
                ln = raw.strip()
                if not ln or ln == b"xref":
                    continue
                parts = ln.split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    obj = int(parts[0])            # subsection header: start count
                elif len(parts) >= 3 and parts[2] in (b"n", b"f"):
                    if parts[2] == b"n" and parts[0].isdigit() and obj not in offset_map:
                        offset_map[obj] = int(parts[0])   # latest section wins
                    obj += 1
            if ti >= 0:
                tdict = chunk[ti:ti + 8192]
                if root_ref is None:
                    root_ref = Scanner._pdf_obj_ref(tdict, b"/Root")
                if info_ref is None:
                    info_ref = Scanner._pdf_obj_ref(tdict, b"/Info")
                pm = re.search(rb"/Prev\s+(\d+)", tdict)
                cur = int(pm.group(1)) if pm else None
            else:
                cur = None
        if not offset_map:
            return None
        return offset_map, root_ref, info_ref

    @staticmethod
    def _pdf_count_from_pages(pg: bytes) -> int | None:
        """The `/Count` of a single page-tree node region (shared by the map and
        locate resolution paths so the extraction lives in one place)."""
        m = re.search(rb"/Count\s+(\d+)", pg)
        return int(m.group(1)) if m else None

    def _pdf_count_via_map(self, path: Path, offset_map: dict[int, int],
                           root_ref: int | None, whole: bytes | None) -> int | None:
        """Root catalog → /Pages → /Count, resolving each object by its xref offset
        (so a superseded page-tree fragment can't win)."""
        if root_ref is None or root_ref not in offset_map:
            return None
        cat = self._resolve_obj_region(path, offset_map[root_ref], whole)
        pages_ref = self._pdf_obj_ref(cat, b"/Pages")
        if pages_ref is None or pages_ref not in offset_map:
            return None
        return self._pdf_count_from_pages(
            self._resolve_obj_region(path, offset_map[pages_ref], whole))

    def _locate_regular_obj(self, whole: bytes | None, objnum: int | None) -> bytes | None:
        """Find a regular (uncompressed) object `N G obj` in the already-read
        whole-file bytes. For xref-STREAM PDFs, whose offset table is compressed
        (v1.8), this recovers refs that are plain objects (the common case for
        /Info, catalog). Returns None when the whole file isn't available (> cap)."""
        if objnum is None or whole is None:
            return None
        # LAST occurrence, not first: an incremental update appends the newer copy
        # of an object after the original, so the last `N G obj` is the current one
        # (the latest-wins discipline the classic xref path gets from its offset
        # map; the regex-locate path is the xref-stream best-effort until v1.8).
        # Residual: a literal `N G obj` inside another object's content could match
        # — a real-offset resolver (v1.8) removes that.
        last = None
        for mm in re.finditer(rb"\b%d\s+\d+\s+obj\b" % objnum, whole):
            last = mm
        if last is None:
            return None
        end = whole.find(b"endobj", last.end())
        return whole[last.start():end if end >= 0 else last.start() + PDF_ANCHOR_OBJ_CAP]

    def _pdf_count_via_locate(self, whole: bytes | None, root_ref: int | None) -> int | None:
        cat = self._locate_regular_obj(whole, root_ref)
        if not cat:
            return None
        pg = self._locate_regular_obj(whole, self._pdf_obj_ref(cat, b"/Pages"))
        return self._pdf_count_from_pages(pg) if pg else None

    def _read_structural_index(self, path: Path, sample: bytes, whole: bytes | None,
                               fmt: str) -> dict[str, Any] | None:
        """Dispatch to the reader for a format's structural index, keyed off the
        declared STRUCTURAL_ANCHORS table — the v1.7 generalization seam. v1.7
        implements the PDF `trailer_pointer`; ZIP (`eocd`) / OLE2 (`fat`) are
        declared but read by zipfile/olefile elsewhere, so they have no reader here
        yet (a v1.8 addition is a table entry + a branch)."""
        if STRUCTURAL_ANCHORS.get(fmt) == "trailer_pointer":
            return self._pdf_anchor(path, sample, whole)
        return None

    def _pdf_anchor(self, path: Path, sample: bytes, whole: bytes | None
                    ) -> dict[str, Any] | None:
        """Follow the PDF's structural index. Returns {xref_type, page_count,
        info_region} or None when no anchor can be followed (caller falls back to
        the v1.5 window scan). Reads from `whole` (slice) when available, else seeks.
        Never raises."""
        sx = self._pdf_last_startxref(path, sample, whole)
        if sx is None:
            return None
        if whole is not None:
            head = whole[sx:sx + 64]
        else:
            try:
                with open(path, "rb") as f:
                    f.seek(sx)
                    head = f.read(64)
            except OSError:
                return None
        # Classic cross-reference table.
        if re.match(rb"\s*xref\b", head):
            parsed = self._parse_classic_xref(path, sx, whole)
            if parsed is None:
                return None
            offset_map, root_ref, info_ref = parsed
            info_region = (self._resolve_obj_region(path, offset_map[info_ref], whole)
                           if info_ref is not None and info_ref in offset_map else None)
            return {"xref_type": "classic",
                    "page_count": self._pdf_count_via_map(path, offset_map, root_ref, whole),
                    "info_region": info_region}
        # Cross-reference STREAM (PDF 1.5+): the dict is plaintext (carries /Root,
        # /Info); the offset table is compressed (decoding it → v1.8). Recover
        # /Info + page_count by locating the referenced regular objects.
        if re.match(rb"\s*\d+\s+\d+\s+obj\b", head):
            region = self._resolve_obj_region(path, sx, whole)
            if b"/XRef" in region:
                info_ref = self._pdf_obj_ref(region, b"/Info")
                return {"xref_type": "stream",
                        "page_count": self._pdf_count_via_locate(
                            whole, self._pdf_obj_ref(region, b"/Root")),
                        "info_region": self._locate_regular_obj(whole, info_ref)}
        return None

    def _extract_pdf_metadata(self, path: Path, sample: bytes,
                              budget: int = 131072) -> dict[str, Any]:
        # `budget` is accepted for caller uniformity (the dispatcher passes the
        # specialist budget to every extractor) but is intentionally NOT used to
        # size the PDF reads: the marker window is fixed at PDF_MARKER_BUDGET (so
        # this tier and detect_requires_vision agree regardless of profile) and
        # page_count/Info read the whole file (PDF_FULL_READ_CAP).
        del budget
        # Markers (text/image) use a FIXED head+tail window — identical to the one
        # detect_requires_vision uses — so text_detected and requires_vision can
        # never contradict each other regardless of specialist_budget.
        region = self._pdf_scan_region(path, sample, PDF_MARKER_BUDGET)
        # page_count + /Info read the whole file (capped) — the root page tree and
        # trailer Info can sit in the middle of a large non-linearized PDF.
        full = self._pdf_full_or_region(path, sample)
        # `whole` is the complete file bytes when it was fully read (≤ cap — the
        # common case); the anchor reader then resolves every object by slicing it
        # (one read, no re-opens). None for > cap PDFs, where the anchor falls back
        # to seeking the file directly.
        try:
            whole = full if path.stat().st_size <= PDF_FULL_READ_CAP else None
        except OSError:
            whole = None
        meta: dict[str, Any] = {}
        meta["has_text_streams"] = (
            b"/Text" in region or b"/Font" in region
            or b"BT\n" in region or b"BT\r\n" in region or b"BT\r" in region
        )
        meta["encrypted"] = b"/Encrypt" in full
        # v1.12 disclosure ("extraction_permission_bypassed") surfaces via
        # FileRecord.safety_flags, NOT a pdf-namespaced field — leg-1 review #12.
        # The pypdf cascade may emit it via meta["_safety_extras"] (transient;
        # scan_file pops it before constructing the FileRecord).
        # v1.7: follow the structural anchor (startxref → latest trailer → root →
        # page tree), dispatched via STRUCTURAL_ANCHORS. Precise on incremental
        # updates (the root count, not the max over superseded fragments) and on
        # > 64 MB PDFs (the pointer is followed regardless of size). `xref_type`
        # records the form observed (`none` = no anchor followed → v1.5 fallback).
        anchor = self._read_structural_index(path, sample, whole, "pdf")
        meta["xref_type"] = (anchor or {}).get("xref_type") or "none"
        if anchor and anchor.get("page_count") is not None:
            meta["page_count"] = anchor["page_count"]
        else:
            meta["page_count"] = self._pdf_page_count(full)      # v1.5 fallback
        # /Info strings: literal (...) AND hex <...>. Gated on `encrypted` — a
        # standard-security PDF encrypts its /Info strings, so extracting them
        # yields ciphertext garbage; emit null instead. When the anchor resolved the
        # /Info object that region is AUTHORITATIVE (the latest trailer's /Info) — a
        # missing key is genuinely absent, so we do NOT fall back to a whole-file
        # scan, which would resurface a stale value from a superseded /Info on an
        # incrementally-updated PDF (Gemini review). The whole-file scan is used only
        # when no anchor resolved /Info at all (the v1.5 path).
        # /Info source + how authoritative it is:
        #  - a resolved region (bytes) → authoritative, use it.
        #  - anchor followed on a FULLY-READ file (whole present, ≤ cap) but no
        #    region → the latest trailer genuinely has no /Info; the fields are
        #    absent and we must NOT scan the whole file (that would resurface a
        #    superseded /Info on an incremental update — gemini + codex PR review).
        #  - anchor on a > cap file whose /Info object couldn't be read (whole None
        #    → the xref-stream locate path can't slice), OR no anchor at all → use
        #    the v1.5 window scan (its bounded tail holds the latest revision's
        #    /Info). Without this, a > 64 MB xref-stream PDF loses a real producer
        #    that v1.5 found in the tail (corpus re-validation caught this).
        info_src = (anchor or {}).get("info_region")
        if info_src is not None:
            src: bytes | None = info_src
        elif anchor is not None and whole is not None:
            src = None
        else:
            src = full
        for field_name, pdf_key in [
            ("title", b"/Title"), ("author", b"/Author"),
            ("producer", b"/Producer"), ("creator", b"/Creator"),
            ("creation_date", b"/CreationDate"),
        ]:
            meta[field_name] = (None if (meta["encrypted"] or src is None)
                                else self._extract_pdf_string(src, pdf_key))
        # pdf_version: search the head (tolerate a leading BOM / whitespace before %PDF-).
        ver_match = re.search(rb"%PDF-(\d+\.\d+)", sample[:1024])
        meta["pdf_version"] = ver_match.group(1).decode("ascii") if ver_match else None
        # v1.5 (stable, promoted v1.10): born-digital-vs-image signal over the marker region
        # (same window as requires_vision). Object-stream PDFs that compress their
        # /Font refs remain a documented residual.
        meta["text_detected"] = (b"/Font" in region
                                 or bool(re.search(rb"\bBT\b", region)))
        # Retained for continuity but head-only and ~0.0 for all real PDFs (text
        # ops live in compressed streams) — NOT the vision signal (see text_detected).
        count_bt = len(re.findall(rb"\bBT\b", sample))
        count_et = len(re.findall(rb"\bET\b", sample))
        meta["sample_text_marker_density"] = (
            (count_bt + count_et) / len(sample) if len(sample) > 0 else None)
        # v1.8: object-stream PDFs (PDF 1.5+) compress the page tree into an /ObjStm,
        # so v1.7's byte reader leaves page_count (and sometimes /Info) null. A tiered
        # decode fills them — pypdf (tier 1) → stdlib decoder (tier 2) → null —
        # ADDITIVE ONLY: it fills nulls, never overrides a value v1.7 produced.
        # `parser` records which tier produced a recovered value (none = not used).
        meta["parser"] = "none"
        # v1.12 §3.1(c): relax the original `not meta["encrypted"]` gate. pypdf
        # handles empty-password decrypt internally and reads /Info + page tree even
        # when content streams are encrypted; the v1.7 anchor reader skips PDF
        # strings on encrypted PDFs (so /Info comes back null even on classic-xref
        # encrypted PDFs). Run the cascade when page_count is null OR the PDF is
        # encrypted. Note: `info_null` is structurally always True when encrypted
        # (line 3060-3064 forces /Info to None on encryption), so checking
        # `meta["encrypted"]` alone is equivalent and clearer (leg-1 review #4).
        #
        # CRITICAL: the merge below MUST be a strict null-fill for EVERY field —
        # leg-1 review #2/#7 caught that v1.11 page_count from the v1.7 anchor
        # could be overwritten by pypdf's `len(reader.pages)` when the cascade
        # fires on classic-xref encrypted PDFs, breaking the byte-identical
        # contract for non-residual PDFs. The `meta.get(k) is None` guard
        # protects every populated field — page_count included.
        if meta["page_count"] is None or meta["encrypted"]:
            decoded = self._pdf_decode_compressed(path, whole)
            if decoded:
                # Strict null-fill for ALL fields (leg-1 review #2/#7): the merge
                # NEVER overrides a value v1.7 produced; only fills nulls. Track
                # whether the cascade actually filled anything so `parser` only
                # records a TIER ATTRIBUTION when a value was produced (round-2
                # leg-1 review #2/#3/#5/#7/#8/#10 — the parser field's documented
                # contract is "the tier that PRODUCED a recovered value"; setting
                # parser="pypdf" on the DependencyError stub or the bypass-only
                # escape would misattribute v1.7-anchor values to pypdf).
                cascade_filled_a_field = False
                for k in ("page_count", "title", "author", "producer", "creator", "creation_date"):
                    if meta.get(k) is None and decoded.get(k) is not None:
                        meta[k] = decoded[k]
                        cascade_filled_a_field = True
                if cascade_filled_a_field:
                    meta["parser"] = decoded["parser"]
                # v1.12 disclosure (transient — popped before serialization in scan_file):
                # promoted from a pdf-namespaced bool to a safety_flags entry per
                # leg-1 review #12. Surfaced via _safety_extras for scan_file pickup.
                # This signal is INDEPENDENT of cascade_filled_a_field — we may
                # decrypt + disclose without recovering any new field.
                if decoded.get("permission_flags_bypassed"):
                    meta.setdefault("_safety_extras", []).append("extraction_permission_bypassed")
                # v1.12 RFC §4.1: cryptography-absent on an AES-encrypted PDF triggers
                # an ErrorRecord (leg-1 review #3/#8). Marker is popped + emitted in scan_file.
                # Also independent of cascade_filled_a_field — the error is the signal.
                if decoded.get("_pdf_encryption_unsupported"):
                    meta["_pdf_encryption_unsupported"] = True
        return meta

    def _pdf_decode_compressed(self, path: Path, whole: bytes | None) -> dict[str, Any] | None:
        """v1.8 tiered decode for object-stream PDFs (page tree / Info compressed):
        pypdf (tier 1) → stdlib decoder (tier 2) → None. The first tier to return a
        result wins; every tier degrades to the next, never raises. `whole` is the
        already-read whole file (≤ cap) — reused by both tiers so the file isn't
        re-read (read-once, like the v1.7 anchor).

        Round-2 leg-1 #4: when pypdf returns a SIGNAL-ONLY dict (the leg-1 #5/#6
        bypass-only escape or the DependencyError marker — every data field is
        None), still run stdlib so a no-filter / compressed-xref recovery can land.
        Merge stdlib's data fields into the pypdf signal dict (preserves the
        permission_flags_bypassed disclosure + the _pdf_encryption_unsupported
        marker, while letting stdlib supply page_count when it can)."""
        result = self._pdf_via_pypdf(path, whole)
        if result is None:
            return self._pdf_via_stdlib(path, whole)
        # pypdf returned a dict. If it's signal-only (every data field None),
        # try stdlib too and merge — but keep pypdf's transient signals.
        data_fields = ("page_count", "title", "author", "producer", "creator", "creation_date")
        if all(result.get(k) is None for k in data_fields):
            stdlib_result = self._pdf_via_stdlib(path, whole)
            if stdlib_result is not None:
                # stdlib filled at least page_count — promote its data fields,
                # promote its parser tier ATTRIBUTION (since stdlib actually produced
                # values), but preserve pypdf's transient signals (bypass disclosure,
                # encryption-unsupported marker).
                merged = {**result, **{k: stdlib_result.get(k) for k in data_fields},
                          "parser": stdlib_result.get("parser", result.get("parser"))}
                return merged
        return result

    # ---- v1.8 tier 2: stdlib object-stream decoder (no dependency) -----------
    # Decodes the compressed cross-reference stream + object streams in stdlib
    # (zlib + PNG predictor + /W binary xref + /ObjStm) to recover page_count for
    # object-stream PDFs WITHOUT pypdf. Scoped to the common cases — returns None
    # (NEVER a wrong value) on exotic inputs (TIFF/avg/paeth predictors, unusual
    # /W, etc.); cross-validated against pypdf as an oracle (0 disagreements on the
    # 371-PDF corpus; recovers 327, nulls 44 scoped-out).
    @staticmethod
    def _safe_inflate(body: bytes, cap: int = PDF_INFLATE_CAP) -> bytes | None:
        """zlib-inflate `body`, bounded to `cap` bytes — refuses a decompression bomb
        (a small flate stream that expands to GBs) by returning None when the output
        would exceed the cap, instead of exhausting memory. Same discipline as
        `_ZIP_MAX_DECOMPRESS`. Returns None on any zlib error. (gemini PR review.)"""
        try:
            d = zlib.decompressobj()
            out = d.decompress(body, cap)
            # A bomb is when the stream did NOT finish within `cap` output bytes
            # (`not d.eof`). Do NOT key on `unconsumed_tail` — a valid stream that
            # finished can still leave trailing bytes after the zlib data (common in
            # PDF stream bodies), which would falsely refuse it (gemini PR review).
            if not d.eof:
                return None
            return out
        except Exception:
            return None

    @staticmethod
    def _pdf_stream_body(data: bytes, obj_off: int) -> tuple[bytes, bytes] | tuple[None, None]:
        """(dict_bytes, raw_stream_body) for the object at absolute `obj_off`."""
        win = data[obj_off:obj_off + PDF_ANCHOR_OBJ_CAP]
        si = win.find(b"stream")
        if si < 0:
            return None, None
        d = win[:si]
        bs = obj_off + si + len(b"stream")
        if data[bs:bs + 2] == b"\r\n":
            bs += 2
        elif data[bs:bs + 1] in (b"\n", b"\r"):
            bs += 1
        lm = re.search(rb"/Length\s+(\d+)", d)
        if lm:
            body = data[bs:bs + int(lm.group(1))]
        else:
            em = data.find(b"endstream", bs)
            body = data[bs:em] if em >= 0 else b""
        return d, body

    @staticmethod
    def _png_predictor_undo(raw: bytes, columns: int, predictor: int) -> bytes | None:
        """Undo a PNG predictor (predictor ≥ 10) over `columns`-wide rows. Supports
        filters None/Sub/Up (the ones xref streams use); returns None for avg/paeth
        or a TIFF predictor → the caller nulls (scoped out, never wrong)."""
        if predictor < 10:
            return None
        # Bound `columns` (attacker-controlled via /Columns) BEFORE allocating —
        # a row can never be wider than the inflated stream, and a row width ≥ 1.
        # Without this an attacker /Columns drives a multi-GB bytearray(columns)
        # allocation decoupled from the (capped) stream size (red-team #1/#3).
        if columns < 1 or columns > len(raw):
            return None
        stride = columns + 1
        out = bytearray()
        prev = bytearray(columns)
        for i in range(0, len(raw), stride):   # partial trailing row handled by the break below
            ft = raw[i]
            row = bytearray(raw[i + 1:i + 1 + columns])
            if len(row) < columns:
                break
            if ft == 0:
                pass
            elif ft == 2:                       # Up
                for j in range(columns):
                    row[j] = (row[j] + prev[j]) & 0xFF
            elif ft == 1:                       # Sub (bpp=1 approximation; ok for xref)
                for j in range(columns):
                    row[j] = (row[j] + (row[j - 1] if j else 0)) & 0xFF
            else:
                return None
            out += row
            prev = row
        return bytes(out)

    @staticmethod
    def _pdf_xref_stream_map(data: bytes, offset: int
                             ) -> tuple[dict[int, tuple[int, int, int]], int | None] | None:
        """Parse the xref stream(s) at `offset` (following /Prev, bounded) into
        {obj: (type, field2, field3)} + the /Root object number. type 1 = regular
        (field2=byte offset), type 2 = compressed (field2=objstm obj, field3=index)."""
        objmap: dict[int, tuple[int, int, int]] = {}
        root_ref: int | None = None
        cur: int | None = offset
        seen: set[int] = set()
        total_raw = 0   # aggregate inflated bytes across the /Prev chain (red-team #3)
        for _ in range(PDF_XREF_PREV_HOPS):
            if cur is None or cur in seen:
                break
            seen.add(cur)
            if not re.match(rb"\s*\d+\s+\d+\s+obj", data[cur:cur + 40]):
                break
            d, body = Scanner._pdf_stream_body(data, cur)
            if d is None or b"/XRef" not in d:
                break
            wm = re.search(rb"/W\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s*\]", d)
            if not wm:
                break
            w = [int(wm.group(i)) for i in (1, 2, 3)]
            ew = sum(w)
            if ew == 0:
                break   # zero-width xref entries → the entry loop never advances and
                        # runs the full attacker /Index count → unbounded (red-team #2)
            sm = re.search(rb"/Size\s+(\d+)", d)
            size = int(sm.group(1)) if sm else 0
            im = re.search(rb"/Index\s*\[([\d\s]+)\]", d)
            index = [int(x) for x in im.group(1).split()] if im else [0, size]
            if root_ref is None:
                root_ref = Scanner._pdf_obj_ref(d, b"/Root")
            # v1.12 §3.3 PIVOTED: uncompressed xref streams (no /Filter) are common
            # on engineering-spec PDFs (42 PDFs on corpora_infra; e.g. WSDOT specs).
            # Body is already the raw entry bytes per /W — skip the Flate inflate.
            # _pdf_stream_body bounds `body` by declared /Length or endstream locator,
            # so the v1.8.1 bounded-observation discipline applies; the aggregate
            # PDF_INFLATE_CAP cap (>= test below) bounds the /Prev chain too.
            #
            # /Filter detection MUST match the KEY, not a substring (leg-1 review #14):
            # a literal-string containing "/Filter" elsewhere in the dict would
            # false-positive a substring check. The PDF syntax for a dictionary key
            # /Filter is followed by either a name (`/FlateDecode`) or an array
            # (`[/FlateDecode ...]`) per ISO 32000 §7.3.7.
            #
            # The raw-body path applies WHEN: (a) no /Filter key, or (b) /Filter
            # names an identity / no-op filter (`/None` or `/Identity`) — leg-4
            # Gemini Code Assist review on PR #55 caught the /None + /Identity case.
            # If /Filter is present AND names a real compression filter (FlateDecode
            # is the only one we decode in stdlib; LZW/DCT/etc. fall through to
            # _safe_inflate which fails cleanly → null), take the inflate path.
            filter_match = re.search(rb"/Filter\s*[/\[]\s*/?([A-Za-z][A-Za-z0-9]*)", d)
            if filter_match is None:
                raw = body                                  # no /Filter — raw bytes
            elif filter_match.group(1) in (b"None", b"Identity"):
                raw = body                                  # explicit no-op filter
            else:
                raw = Scanner._safe_inflate(body)           # compression filter declared
            if raw is None:
                break
            total_raw += len(raw)
            if total_raw >= PDF_INFLATE_CAP:
                break   # bound TOTAL work across the /Prev chain, not just per-stream
                        # (32 hops × 64 MB would compose to ~2 GB of predictor work).
                        # `>=` not `>` — leg-1 review #10: with strict `>`, a single
                        # 64MB uncompressed xref stream (PDF_INFLATE_CAP == 64MB)
                        # slips on the FIRST iteration and runs predictor+entry loops
                        # over the full 64MB. The v1.8 Flate path was protected
                        # only because `_safe_inflate` refused mid-truncation; the
                        # v1.12 no-filter path needs the explicit ≥ to bound disk reads.
            pm = re.search(rb"/Predictor\s+(\d+)", d)
            if pm and int(pm.group(1)) > 1:
                cm = re.search(rb"/Columns\s+(\d+)", d)
                raw = Scanner._png_predictor_undo(raw, int(cm.group(1)) if cm else ew, int(pm.group(1)))
                if raw is None:
                    break                       # unsupported predictor → scoped out
            pos = 0
            for k in range(0, len(index) - 1, 2):
                start, count = index[k], index[k + 1]
                for n in range(count):
                    if pos + ew > len(raw):
                        break
                    rec = raw[pos:pos + ew]
                    pos += ew
                    o = 0
                    f = []
                    for width in w:
                        f.append(int.from_bytes(rec[o:o + width], "big") if width else 0)
                        o += width
                    t = f[0] if w[0] else 1
                    onum = start + n
                    if onum not in objmap and t in (1, 2):
                        objmap[onum] = (t, f[1], f[2])
            pv = re.search(rb"/Prev\s+(\d+)", d)
            cur = int(pv.group(1)) if pv else None
        return (objmap, root_ref) if objmap else None

    @staticmethod
    def _pdf_objstm_extract(data: bytes, objmap: dict[int, tuple[int, int, int]],
                            stm: int, index: int) -> bytes | None:
        """Extract the `index`-th object from object stream `stm` (its objects are
        concatenated after a `/First`-offset header of objnum/offset pairs)."""
        ent = objmap.get(stm)
        if not ent or ent[0] != 1:
            return None
        d, body = Scanner._pdf_stream_body(data, ent[1])
        if d is None:
            return None
        fm = re.search(rb"/First\s+(\d+)", d)
        if not fm:
            return None
        first = int(fm.group(1))
        dec = Scanner._safe_inflate(body)
        if dec is None:
            return None
        hdr = dec[:first].split()
        pairs = [(int(hdr[i]), int(hdr[i + 1])) for i in range(0, len(hdr) - 1, 2)]
        if index >= len(pairs):
            return None
        o = first + pairs[index][1]
        nxt = first + pairs[index + 1][1] if index + 1 < len(pairs) else len(dec)
        return dec[o:nxt]

    @staticmethod
    def _pdf_resolve_via_map(data: bytes, objmap: dict[int, tuple[int, int, int]],
                             num: int | None) -> bytes | None:
        if num is None:
            return None
        ent = objmap.get(num)
        if not ent:
            return None
        if ent[0] == 1:                          # regular object at a byte offset
            chunk = data[ent[1]:ent[1] + PDF_ANCHOR_OBJ_CAP]
            end = chunk.find(b"endobj")           # trim at endobj (parity with
            return chunk if end < 0 else chunk[:end]   # _resolve_obj_region — no stale-key match)
        if ent[0] == 2:                          # compressed in an object stream
            return Scanner._pdf_objstm_extract(data, objmap, ent[1], ent[2])
        return None

    def _pdf_via_stdlib(self, path: Path, whole: bytes | None = None) -> dict[str, Any] | None:
        """Tier 2: decode an object-stream PDF's page_count in stdlib. Returns a dict
        (`parser="stdlib"`) or None. Never raises. Reuses the already-read `whole`
        file (≤ cap) when given; > cap files (whole=None) are skipped (needs the
        whole file in memory)."""
        if whole is not None:
            data = whole
        else:
            try:
                if path.stat().st_size > PDF_FULL_READ_CAP:
                    return None
                data = path.read_bytes()
            except OSError:
                return None
        try:
            sx = self._pdf_last_startxref(path, b"", data)
            if sx is None:
                return None
            parsed = self._pdf_xref_stream_map(data, sx)
            if parsed is None:
                return None
            objmap, root_ref = parsed
            cat = self._pdf_resolve_via_map(data, objmap, root_ref)
            if cat is None:
                return None
            pages = self._pdf_resolve_via_map(data, objmap, self._pdf_obj_ref(cat, b"/Pages"))
            if pages is None:
                return None
            cnt = self._pdf_count_from_pages(pages)
            if cnt is None:
                return None
            return {"parser": "stdlib", "page_count": cnt, "title": None, "author": None,
                    "producer": None, "creator": None, "creation_date": None}
        except Exception:
            return None

    @staticmethod
    def _pdf_via_pypdf(path: Path, whole: bytes | None = None) -> dict[str, Any] | None:
        """Tier 1: read page_count + /Info via the optional `pypdf` parser, scoped to
        exactly those facts (no text/structure — observe, don't extract). Bounded
        (strict=False, no network/JS). Returns a dict (with `parser="pypdf"`) or None
        when pypdf is absent / can't read / found nothing. Never raises. Reads from
        the already-read `whole` bytes via BytesIO when given (no re-read, no file
        handle); else opens the path (e.g. > cap files)."""
        if pypdf is None:
            return None

        def _s(v: Any) -> str | None:
            if v is None:
                return None
            s = str(v).strip()
            return s or None

        # Round-2 leg-1 #1: `except pypdf.errors.DependencyError:` is a bare
        # attribute reference. On older pypdf builds that lack this exception
        # class, Python's except-matching evaluates the attribute path during
        # the raise — which would itself raise AttributeError and be swallowed
        # by the outer `except Exception:`, losing the marker. Resolve it once,
        # tolerantly; a tuple of `()` cannot match anything (so the targeted
        # branch becomes a no-op on old pypdf — falling through to the broad
        # Exception handler, which still null-cleans rather than crashes).
        _dep_err = getattr(getattr(pypdf, "errors", None), "DependencyError", None)
        _dep_err_match: tuple = (_dep_err,) if _dep_err is not None else ()

        try:
            source: Any = io.BytesIO(whole) if whole is not None else str(path)
            reader = pypdf.PdfReader(source, strict=False)
            permission_flags_bypassed = False
            if getattr(reader, "is_encrypted", False):
                try:
                    decrypt_result = reader.decrypt("")          # empty-password (owner-only) PDFs
                except _dep_err_match:
                    # v1.12: cryptography is required for AES-256/V5 decrypt; if absent,
                    # pypdf raises DependencyError. RFC §4.1 mandates a structured
                    # ErrorRecord on this exact case — emit a transient event marker so
                    # _extract_pdf_metadata / scan_file can surface it. The marker is
                    # popped before serialization (never appears in the manifest).
                    return {"parser": "pypdf", "page_count": None,
                            "title": None, "author": None, "producer": None,
                            "creator": None, "creation_date": None,
                            "permission_flags_bypassed": False,
                            "_pdf_encryption_unsupported": True}
                except Exception:
                    return None
                # v1.12 §3.1(c): if decrypt returned 0 (no/wrong password) the PDF needs
                # a real password — we MUST NOT prompt; cascade returns None cleanly.
                # pypdf <5 returned 0/1/2 int; pypdf 6+ returns a PasswordType enum
                # whose value is 0 for failure. Compare against the int explicitly.
                if int(decrypt_result) == 0:
                    return None
                # v1.12 §3.4(a) disclosure: surface when the primary EXTRACT permission
                # (bit 5 — ISO 32000 Table 22 §7.6.4.2) is NOT set in
                # user_access_permissions but we extract metadata anyway. Pypdf names
                # the constant `EXTRACT` (value 16); `EXTRACT_TEXT_AND_GRAPHICS` (bit 10,
                # value 512) is the accessibility override that PDF 2.0 deprecates to
                # "shall always be 1" — that bit is NOT the right gate for disclosure.
                try:
                    from pypdf.constants import UserAccessPermissions
                    perms = getattr(reader, "user_access_permissions", None)
                    if perms is not None and UserAccessPermissions.EXTRACT not in perms:
                        permission_flags_bypassed = True
                except ImportError:
                    pass    # UserAccessPermissions absent on an unusually-old pypdf
                except AttributeError:
                    pass    # the EXTRACT member isn't on this pypdf's enum
                except Exception:
                    pass    # never-crash: any hostile/exotic reader state nulls cleanly
            out: dict[str, Any] = {"parser": "pypdf", "page_count": None,
                                   "title": None, "author": None, "producer": None,
                                   "creator": None, "creation_date": None,
                                   "permission_flags_bypassed": permission_flags_bypassed}
            try:
                out["page_count"] = len(reader.pages)
            except Exception:
                pass
            try:
                md = reader.metadata
                if md is not None:
                    out["title"] = _s(md.title)
                    out["author"] = _s(md.author)
                    out["producer"] = _s(md.producer)
                    out["creator"] = _s(md.creator)
                    out["creation_date"] = _s(md.get("/CreationDate"))
            except Exception:
                pass
            if out["page_count"] is None and all(
                    out[k] is None for k in ("title", "author", "producer", "creator", "creation_date")):
                # v1.12 (leg-1 #5/#6): if we successfully decrypted an extract-denied PDF
                # but pypdf returned no usable metadata, the bypass DISCLOSURE must still
                # survive — returning None would let the cascade fall through to stdlib
                # (which doesn't carry the bypass key) and silently lose the audit signal.
                # Return the (otherwise empty) dict so the bypass flag propagates.
                if permission_flags_bypassed:
                    return out
                return None                      # nothing useful → let the cascade continue
            return out
        except Exception:
            return None

    @staticmethod
    def _pdf_literal_string(data: bytes, open_paren: int) -> bytes | None:
        """Read a PDF literal string starting at the `(` at `open_paren`, honoring
        backslash escapes AND balanced nested parens (ISO 32000 §7.3.4.2). A regex
        can't do balanced parens; an unescaped inner `(`/`)` in a /Title used to
        truncate the value (review 2026-06-02). Returns unescaped content, or None
        if unterminated. Bounded by a 64 KB scan so a stray unbalanced `(` can't
        run away."""
        depth, i, out = 0, open_paren, bytearray()
        limit = min(len(data), open_paren + 65536)
        while i < limit:
            c = data[i]
            if c == 0x5C:                       # backslash → next byte literal
                out += data[i + 1:i + 2]
                i += 2
                continue
            if c == 0x28:                       # (
                depth += 1
                if depth > 1:
                    out.append(c)
            elif c == 0x29:                     # )
                depth -= 1
                if depth == 0:
                    return bytes(out)
                out.append(c)
            else:
                out.append(c)
            i += 1
        return None                              # unterminated / runaway

    @staticmethod
    def _decode_pdf_bytes(raw: bytes) -> str:
        """Decode PDF string bytes (literal OR hex). PDF strings carry text either
        as PDFDocEncoded (~latin-1) or UTF-16 with a byte-order mark — both literal
        `(…)` and hex `<…>` forms (v1.6: the literal path previously assumed
        latin-1, mojibake-ing UTF-16BE producer strings like `þÿ\x00M\x00i…`)."""
        if raw[:2] == b"\xfe\xff":
            return raw[2:].decode("utf-16-be", errors="replace")
        if raw[:2] == b"\xff\xfe":
            return raw[2:].decode("utf-16-le", errors="replace")
        # BOM-less UTF-16: detect by parity, not by "any NUL present" (v1.6 fix —
        # a latin-1 producer with a stray/trailing NUL like b"doPDF 7.2\x00" was
        # mojibake-d to UTF-16 by the old `b"\x00" in raw` test, regressing v1.5).
        # UTF-16-BE ASCII has its high (even-index) bytes all NUL; LE the odd-index.
        if len(raw) >= 2 and len(raw) % 2 == 0:
            if not any(raw[0::2]):
                return raw.decode("utf-16-be", errors="replace")
            if not any(raw[1::2]):
                return raw.decode("utf-16-le", errors="replace")
        return raw.decode("latin-1", errors="replace")

    def _extract_pdf_string(self, data: bytes, key: bytes) -> str | None:
        # literal string: /Key (…) — depth-aware (balanced + escaped parens).
        km = re.search(re.escape(key) + rb"\s*\(", data)
        if km:
            val = self._pdf_literal_string(data, km.end() - 1)  # at the '('
            if val is not None:
                return self._decode_pdf_bytes(val)
        # hex string: /Key <48656C6C6F>.
        match = re.search(re.escape(key) + rb"\s*<([0-9A-Fa-f\s]+)>", data)
        if match:
            hexstr = re.sub(rb"\s", b"", match.group(1))
            if len(hexstr) % 2:
                hexstr += b"0"  # ISO 32000 §7.3.4.3: odd-length hex pads a trailing 0
            try:
                return self._decode_pdf_bytes(bytes.fromhex(hexstr.decode("ascii")))
            except ValueError:
                return None
        return None

    def _extract_png_metadata(self, sample: bytes) -> dict[str, Any] | None:
        # PNG signature: 8 bytes + IHDR chunk (4 len + 4 type + 13 data = 29 bytes minimum)
        PNG_SIG = b"\x89PNG\r\n\x1a\n"
        if len(sample) < 8 or sample[:8] != PNG_SIG:
            return None
        # IHDR must be first chunk: bytes 8-11 = length, 12-15 = "IHDR", 16-28 = data
        if len(sample) < 24:
            return {"width": None, "height": None, "bit_depth": None}
        chunk_type = sample[12:16]
        if chunk_type != b"IHDR":
            return {"width": None, "height": None, "bit_depth": None}
        # IHDR data: width(4) + height(4) + bit_depth(1) + color_type(1) + ...
        if len(sample) < 29:
            return {"width": None, "height": None, "bit_depth": None}
        width, height = struct.unpack(">II", sample[16:24])
        bit_depth = sample[24]
        return {"width": width, "height": height, "bit_depth": bit_depth}

    # v1.16: EXIF lives in the JPEG APP1 segment / HEIC 'Exif' item, both near the file
    # front but past the 8 KB universal sample (a thumbnail-bearing APP1 can run tens of
    # KB; a HEIC iloc offset can point further). Read a bounded head from the path — a
    # declared deviation from `sample_size`, capped so it stays bounded-observation-safe.
    IMAGE_METADATA_MAX_BYTES = 1 << 20  # 1 MiB

    def _image_metadata_head(self, path: Path, sample: bytes) -> bytes:
        """Bounded head read for image metadata. Falls back to the 8 KB sample on any
        read error (never-crash)."""
        try:
            with open(path, "rb") as fh:
                return fh.read(self.IMAGE_METADATA_MAX_BYTES)
        except OSError:
            return sample

    @staticmethod
    def _jpeg_dimensions(head: bytes) -> tuple[int | None, int | None]:
        # Scan for SOF0 (0xFFC0) or SOF2 (0xFFC2) markers
        i = 0
        while i < len(head) - 1:
            if head[i] != 0xFF:
                i += 1
                continue
            marker = head[i + 1]
            if marker in (0xC0, 0xC2):  # SOF0 or SOF2
                if i + 9 > len(head):
                    return None, None
                height = struct.unpack(">H", head[i + 5:i + 7])[0]
                width = struct.unpack(">H", head[i + 7:i + 9])[0]
                return width, height
            if marker == 0xDA:  # SOS — start of compressed scan data
                # SOF always precedes SOS in a valid JPEG. Stop here: scanning into the
                # entropy-coded stream would false-match a stray 0xFFC0/0xFFC2 byte pair
                # and return garbage dimensions (leg-2/Gemini — amplified by the v1.16
                # 1 MiB head vs the old 8 KB sample). Honest-null beats a wrong value.
                break
            if marker == 0xD8 or marker == 0xD9:  # SOI or EOI
                i += 2
                continue
            if marker == 0x00:  # stuffed byte
                i += 2
                continue
            # Other markers: skip length
            if i + 3 < len(head):
                seg_len = struct.unpack(">H", head[i + 2:i + 4])[0]
                i += 2 + seg_len
            else:
                break
        return None, None

    def _extract_jpeg_metadata(self, path: Path, sample: bytes) -> dict[str, Any] | None:
        head = self._image_metadata_head(path, sample)
        width, height = self._jpeg_dimensions(head)
        meta: dict[str, Any] = {"width": width, "height": height}
        self._apply_exif(meta, _exif_tiff_from_jpeg(head), head)
        return meta

    def _extract_heic_metadata(self, path: Path, sample: bytes) -> dict[str, Any] | None:
        head = self._image_metadata_head(path, sample)
        meta: dict[str, Any] = {"width": None, "height": None}
        # HEIC dims come from EXIF PixelXDimension/PixelYDimension (authoritative),
        # filled by _apply_exif when width/height are still None.
        self._apply_exif(meta, _heif_exif_tiff(head), head)
        return meta

    @staticmethod
    def _apply_exif(meta: dict[str, Any], tiff: bytes | None, head: bytes) -> None:
        """Merge EXIF fields + XMP-presence + geotagged disclosure into an image record.
        Always sets the EXIF keys (None when absent) so the field surface is stable.
        Fills width/height from EXIF pixel dimensions only when not already set (JPEG
        keeps its authoritative SOF dims; HEIC takes them from EXIF)."""
        exif = _parse_exif_tiff(tiff) if tiff else None
        for key in ("make", "model", "orientation", "datetime_original"):
            meta[key] = exif.get(key) if exif else None
        if meta.get("width") is None and exif and exif.get("pixel_x"):
            meta["width"], meta["height"] = exif["pixel_x"], exif.get("pixel_y")
        gps_present = bool(exif.get("gps_present")) if exif else False
        meta["gps_present"] = gps_present
        meta["xmp_present"] = _XMP_MARKER in head
        if gps_present:
            # observe-with-disclosure (the v1.12 extraction_permission_bypassed pattern):
            # surface GPS *presence*, never coordinates.
            meta["_safety_extras"] = ["geotagged"]

    # v1.17: video container metadata. `moov` is usually at the file TAIL (measured: 61/62
    # real .mov), so scanning top-level boxes and seeking past the giant `mdat` reads ONLY
    # the moov box — bounded, no whole-file read. Cap the moov size (a real moov is KBs–few
    # MB; reject a hostile oversize claim).
    MOOV_MAX_BYTES = 16 << 20  # 16 MiB

    def _read_moov(self, path: Path) -> bytes | None:
        """Return the bytes of the `moov` box (seeking past `mdat`), or None. Bounded by
        MOOV_MAX_BYTES; never raises (caller-safe)."""
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fsize = fh.tell()
                pos = 0
                while pos + 8 <= fsize:
                    fh.seek(pos)
                    hdr = fh.read(8)
                    if len(hdr) < 8:
                        break
                    size = struct.unpack(">I", hdr[:4])[0]
                    typ = hdr[4:8]
                    if size == 1:                       # 64-bit largesize
                        ext = fh.read(8)
                        if len(ext) < 8:
                            break
                        size = struct.unpack(">Q", ext)[0]
                    if size == 0:                       # box runs to EOF
                        size = fsize - pos
                    if typ == b"moov":
                        if size > self.MOOV_MAX_BYTES or size < 8:
                            return None
                        fh.seek(pos)
                        return fh.read(size)
                    if size < 8:
                        break
                    pos += size
        except OSError:
            return None
        return None

    def _extract_video_metadata(self, path: Path, sample: bytes) -> dict[str, Any] | None:
        # v1.17 container/track half: codec / duration_s / width / height / creation_date.
        # v1.18 Apple half: make / model (QuickTime keys) + gps_present / gps_source
        # (location.ISO6709 — presence + mechanism, NOT coordinates) → geotagged.
        moov = self._read_moov(path)
        meta: dict[str, Any] = {"codec": None, "duration_s": None, "width": None,
                                "height": None, "creation_date": None, "creation_date_qt": None,
                                "make": None, "model": None,
                                "gps_present": False, "gps_source": None}
        if moov is None:
            return meta
        try:
            meta.update(_parse_moov(moov))
        except Exception:
            pass
        if meta.get("gps_present"):
            # observe-with-disclosure (the v1.16 image pattern), now for video.
            meta["_safety_extras"] = ["geotagged"]
        return meta

    def _extract_eml_metadata(self, sample: bytes) -> dict[str, Any] | None:
        try:
            from email.parser import BytesParser
            from email.policy import default as email_policy
            msg = BytesParser(policy=email_policy).parsebytes(sample)
            subject = msg.get("Subject")
            from_addr = msg.get("From")
            to_addr = msg.get("To")
            date_str = msg.get("Date")
            message_id = msg.get("Message-ID")
            # Detect attachments
            has_attachments = False
            content_type = msg.get_content_type() or ""
            if "multipart/mixed" in content_type:
                has_attachments = True
            elif sample.find(b"Content-Disposition: attachment") != -1:
                has_attachments = True
            return {
                "subject": str(subject) if subject else None,
                "from": str(from_addr) if from_addr else None,
                "to": str(to_addr) if to_addr else None,
                "date": str(date_str) if date_str else None,
                "message_id": str(message_id) if message_id else None,
                "has_attachments": has_attachments,
            }
        except Exception:
            return None

    def _extract_xlsx_metadata(self, path: Path, budget: int = 131072) -> dict[str, Any] | None:
        import zipfile
        from io import BytesIO
        deviation_budget = budget
        try:
            raw = path.read_bytes()[:deviation_budget]
        except Exception:
            return None
        try:
            zf = zipfile.ZipFile(BytesIO(raw))
        except (zipfile.BadZipFile, Exception):
            return None
        try:
            sheet_names: list[str] = []
            header_rows: dict[str, list[str]] = {}
            # Extract sheet names from workbook.xml
            if "xl/workbook.xml" in zf.namelist():
                wb_raw = self._safe_zip_read(zf, "xl/workbook.xml")
                if wb_raw is None:
                    return None
                wb_xml = wb_raw.decode("utf-8", errors="replace")
                try:
                    root = xml_fromstring(wb_xml)
                    ns = {"": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for sheet in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
                        name = sheet.get("name")
                        if name:
                            sheet_names.append(name)
                except Exception:
                    pass
            # Extract header rows from sheet XML files
            for i, sheet_name in enumerate(sheet_names[:10], start=1):  # cap at 10 sheets
                sheet_path = f"xl/worksheets/sheet{i}.xml"
                if sheet_path not in zf.namelist():
                    continue
                sheet_raw = self._safe_zip_read(zf, sheet_path)
                if sheet_raw is None:
                    continue
                try:
                    sheet_xml = sheet_raw.decode("utf-8", errors="replace")
                    sroot = xml_fromstring(sheet_xml)
                    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                    rows = list(sroot.iter(f"{{{ns_main}}}row"))
                    if rows:
                        first_row = rows[0]
                        cells = []
                        for cell in first_row.iter(f"{{{ns_main}}}v"):
                            cells.append(cell.text or "")
                        if cells:
                            header_rows[sheet_name] = cells
                except Exception:
                    continue
            result: dict[str, Any] = {"sheet_names": sheet_names, "header_rows": header_rows}
            # v1.6: producing app from docProps/app.xml (if present in the budget window)
            app_raw = self._safe_zip_read(zf, "docProps/app.xml")
            if app_raw is not None:
                try:
                    # Pass raw bytes — the parser detects encoding from the XML
                    # declaration / BOM; a forced utf-8 decode corrupts a UTF-16
                    # app.xml (gemini-code-assist, PR #36).
                    aroot = xml_fromstring(app_raw)
                    ns_e = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
                    for el in aroot.iter(f"{{{ns_e}}}Application"):
                        if el.text and el.text.strip():
                            result["application"] = el.text.strip()
                        break
                except Exception:
                    pass
            return result
        finally:
            zf.close()

    def _extract_xls_metadata(self, path: Path) -> dict[str, Any] | None:
        # See _extract_msg_metadata: OLE2 requires the full file. olefile gets
        # the path directly; deviation from sample_size is intentional and
        # bounded by file size on disk.
        if not olefile:
            return None
        try:
            if not olefile.isOleFile(str(path)):
                return None
            ole = olefile.OleFileIO(str(path))
            try:
                sheet_names: list[str] = []
                # Try to read sheet names from Workbook stream
                if ole.exists("Workbook"):
                    try:
                        wb_data = ole.openstream("Workbook").read()
                        # BIFF8: scan for BoundSheet8 records (type 0x0085)
                        pos = 0
                        while pos < len(wb_data) - 4:
                            rec_type = int.from_bytes(wb_data[pos:pos + 2], "little")
                            rec_len = int.from_bytes(wb_data[pos + 2:pos + 4], "little")
                            if rec_type == 0x0085 and rec_len >= 8:
                                # BoundSheet8: 4 bytes offset + 1 byte visibility + 1 byte type + name
                                name_len = wb_data[pos + 10] if pos + 10 < len(wb_data) else 0
                                flag = wb_data[pos + 11] if pos + 11 < len(wb_data) else 0
                                name_start = pos + 12
                                if flag == 0:
                                    # Compressed (Latin-1)
                                    name = wb_data[name_start:name_start + name_len].decode("latin-1", errors="replace")
                                else:
                                    # UTF-16LE
                                    name = wb_data[name_start:name_start + name_len * 2].decode("utf-16-le", errors="replace")
                                sheet_names.append(name.rstrip("\x00"))
                            pos += 4 + rec_len
                    except Exception:
                        pass
                # v1.10: producing app from OLE2 SummaryInformation (PIDSI_APPNAME=18)
                application = None
                if ole.exists("\x05SummaryInformation"):
                    try:
                        app = ole.getproperties("\x05SummaryInformation").get(18)
                        if isinstance(app, bytes):
                            application = app.decode("cp1252", errors="replace").rstrip("\x00") or None
                        elif isinstance(app, str):
                            application = app.rstrip("\x00") or None
                    except Exception:
                        pass
                return {"sheet_names": sheet_names, "format": "biff", "application": application}
            finally:
                ole.close()
        except Exception:
            return None

    def _extract_docx_metadata(self, path: Path, budget: int = 131072) -> dict[str, Any] | None:
        import zipfile
        from io import BytesIO
        deviation_budget = budget
        try:
            with path.open("rb") as f:
                raw = f.read(deviation_budget)
        except Exception:
            return None
        try:
            zf = zipfile.ZipFile(BytesIO(raw))
        except (zipfile.BadZipFile, Exception):
            return None
        try:
            meta: dict[str, Any] = {
                "title": None, "author": None, "word_count": None, "heading_count": None,
            }
            # Core properties from docProps/core.xml
            core_raw = self._safe_zip_read(zf, "docProps/core.xml")
            if core_raw is not None:
                try:
                    root = xml_fromstring(core_raw.decode("utf-8", errors="replace"))
                    for el in root.iter("{http://purl.org/dc/elements/1.1/}title"):
                        if el.text:
                            meta["title"] = el.text.strip()
                        break
                    for el in root.iter("{http://purl.org/dc/elements/1.1/}creator"):
                        if el.text:
                            meta["author"] = el.text.strip()
                        break
                except Exception:
                    pass
            # App properties from docProps/app.xml (word count + producing app, v1.6)
            app_raw = self._safe_zip_read(zf, "docProps/app.xml")
            if app_raw is not None:
                try:
                    # Raw bytes — parser detects encoding (gemini-code-assist, PR #36).
                    root = xml_fromstring(app_raw)
                    ns = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
                    for el in root.iter(f"{{{ns}}}Words"):
                        if el.text and el.text.isdigit():
                            meta["word_count"] = int(el.text)
                        break
                    for el in root.iter(f"{{{ns}}}Application"):  # v1.6: producing app
                        if el.text and el.text.strip():
                            meta["application"] = el.text.strip()
                        break
                except Exception:
                    pass
            # Heading count from word/document.xml
            doc_raw = self._safe_zip_read(zf, "word/document.xml")
            if doc_raw is not None:
                try:
                    root = xml_fromstring(doc_raw.decode("utf-8", errors="replace"))
                    ns_w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                    heading_count = 0
                    for pstyle in root.iter(f"{{{ns_w}}}pStyle"):
                        val = pstyle.get(f"{{{ns_w}}}val", "")
                        if val.startswith("Heading") or val.startswith("heading"):
                            heading_count += 1
                    meta["heading_count"] = heading_count
                except Exception:
                    pass
            return meta
        finally:
            zf.close()

    def _extract_doc_metadata(self, path: Path) -> dict[str, Any] | None:
        # See _extract_msg_metadata: OLE2 requires the full file. olefile gets
        # the path directly; deviation from sample_size is intentional and
        # bounded by file size on disk.
        if not olefile:
            return None
        try:
            if not olefile.isOleFile(str(path)):
                return None
            ole = olefile.OleFileIO(str(path))
            try:
                meta: dict[str, Any] = {
                    "title": None, "author": None, "application": None,
                }
                # OLE2 SummaryInformation: 2=Title, 4=Author, 18=PIDSI_APPNAME (creating app, v1.10)
                if ole.exists("\x05SummaryInformation"):
                    try:
                        props = ole.getproperties("\x05SummaryInformation")
                        meta["title"] = props.get(2)
                        meta["author"] = props.get(4)
                        meta["application"] = props.get(18)
                    except Exception:
                        pass
                # Clean string values
                for key in ("title", "author", "application"):
                    v = meta[key]
                    if isinstance(v, bytes):
                        meta[key] = v.decode("cp1252", errors="replace").rstrip("\x00") or None
                    elif isinstance(v, str):
                        meta[key] = v.rstrip("\x00") or None
                    else:
                        meta[key] = None   # malformed SummaryInformation prop (datetime
                                           # /int/…) → None, so non-str can't reach json
                                           # serialization (in-house review v1.10).
                return meta
            finally:
                ole.close()
        except Exception:
            return None

    def _extract_rtf_metadata(self, sample: bytes) -> dict[str, Any] | None:
        try:
            text = sample.decode("ascii", errors="replace")
        except Exception:
            return None
        meta: dict[str, Any] = {"title": None, "author": None}
        # Find {\info ...} group accounting for nested braces
        info_start = text.find("{\\info")
        if info_start == -1:
            return meta
        # Walk from info_start to find matching closing brace
        depth = 0
        info_block = ""
        for i in range(info_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    info_block = text[info_start:i + 1]
                    break
        if not info_block:
            return meta
        # Extract {\title ...} and {\author ...} from the info block
        for field in ("title", "author"):
            pattern = r"\{\\" + field + r"\s+([^}]*)\}"
            match = re.search(pattern, info_block)
            if match:
                val = match.group(1).strip()
                if val:
                    meta[field] = val
        return meta

    def _extract_msg_metadata(self, path: Path) -> dict[str, Any] | None:
        # OLE2 compound documents (.msg) cannot be parsed from a head sample
        # buffer — the FAT sector chains span the whole file. olefile is given
        # the file path directly. This is an intentional, declared deviation
        # from the bounded-observation rule (sample_size); the deviation is
        # bounded by the file size on disk.
        if not olefile:
            return None
        try:
            if not olefile.isOleFile(str(path)):
                return None
            ole = olefile.OleFileIO(str(path))
            try:
                subject = self._msg_read_property(ole, "__substg1.0_0037001F") or \
                          self._msg_read_property(ole, "__substg1.0_0037001E")
                # v0.7.2: prefer PR_SENDER_NAME (0x0C1A — always a display name)
                # over PR_SENDER_EMAIL_ADDRESS (0x0C1F), which returns the
                # ugly Exchange legacyDN for Exchange-sourced messages.
                from_addr = self._msg_read_property(ole, "__substg1.0_0C1A001F") or \
                            self._msg_read_property(ole, "__substg1.0_0C1A001E") or \
                            self._msg_read_property(ole, "__substg1.0_0C1F001F") or \
                            self._msg_read_property(ole, "__substg1.0_0C1F001E") or \
                            self._msg_read_property(ole, "__substg1.0_0042001F") or \
                            self._msg_read_property(ole, "__substg1.0_0042001E")
                to_addr = self._msg_read_property(ole, "__substg1.0_0E04001F") or \
                          self._msg_read_property(ole, "__substg1.0_0E04001E")
                # v0.7.2: read PR_CLIENT_SUBMIT_TIME (0x0039, PT_SYSTIME) from
                # the MAPI properties stream. The previous implementation read
                # from a substg stream, which can never work — fixed-length
                # properties (FILETIME, INT32, etc.) live inline in the
                # properties stream, not in substg streams. Falls back to
                # PR_MESSAGE_DELIVERY_TIME (0x0E06) if the submit time is absent.
                date_val = self._msg_read_filetime_property(ole, 0x0039) or \
                           self._msg_read_filetime_property(ole, 0x0E06)
                message_id = self._msg_read_property(ole, "__substg1.0_1035001F") or \
                             self._msg_read_property(ole, "__substg1.0_1035001E")
                # has_attachments from PR_HASATTACH (0x0E1B) — boolean property
                has_attachments = ole.exists("__attach_version1.0_#00000000")
                return {
                    "subject": subject,
                    "from": from_addr,
                    "to": to_addr,
                    "date": date_val,
                    "message_id": message_id,
                    "has_attachments": has_attachments,
                }
            finally:
                ole.close()
        except Exception:
            return None

    def _msg_read_property(self, ole: Any, stream_name: str) -> str | None:
        try:
            if ole.exists(stream_name):
                data = ole.openstream(stream_name).read()
                if stream_name.endswith("001F"):
                    return data.decode("utf-16-le", errors="replace").rstrip("\x00")
                else:
                    return data.decode("cp1252", errors="replace").rstrip("\x00")
        except Exception:
            pass
        return None

    # Top-level message header in __properties_version1.0 is 32 bytes.
    # Format reference: MS-OXMSG §2.4.
    _MSG_TOPLEVEL_HEADER_SIZE = 32
    _MSG_PROPERTY_ENTRY_SIZE = 16
    _MSG_PT_SYSTIME = 0x0040

    def _msg_read_filetime_property(self, ole: Any, prop_id: int) -> str | None:
        """Read a PT_SYSTIME property from a .msg file's __properties_version1.0
        stream and return its ISO 8601 string. Returns None if absent.

        The .msg property table is the MAPI/MS-OXMSG format, NOT the OLE2
        PropertySetStream format that olefile.getproperties() handles. We parse
        the 16-byte property entries directly. Each entry is:
            4 bytes  property tag (LE; low 16 bits = type, high 16 = ID)
            4 bytes  flags
            8 bytes  value (for PT_SYSTIME, an 8-byte Windows FILETIME)
        """
        try:
            if not ole.exists("__properties_version1.0"):
                return None
            data = ole.openstream("__properties_version1.0").read()
        except Exception:
            return None
        target_tag = (prop_id << 16) | self._MSG_PT_SYSTIME
        pos = self._MSG_TOPLEVEL_HEADER_SIZE
        end = len(data)
        while pos + self._MSG_PROPERTY_ENTRY_SIZE <= end:
            tag = int.from_bytes(data[pos:pos + 4], "little")
            if tag == target_tag:
                ft = int.from_bytes(data[pos + 8:pos + 16], "little")
                return self._filetime_to_iso(ft)
            pos += self._MSG_PROPERTY_ENTRY_SIZE
        return None

    @staticmethod
    def _filetime_to_iso(ft: int) -> str | None:
        """Convert a Windows FILETIME (100-ns intervals since 1601-01-01 UTC)
        to an ISO 8601 timestamp. Returns None for zero/invalid values."""
        if ft <= 0:
            return None
        try:
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            epoch = _dt(1601, 1, 1, tzinfo=_tz.utc)
            return (epoch + _td(seconds=ft / 10_000_000)).isoformat()
        except (OverflowError, ValueError):
            return None

    _ZIP_MAX_DECOMPRESS = 1048576  # 1MB max decompressed size per entry

    def _safe_zip_read(self, zf: Any, entry_name: str) -> bytes | None:
        """Read a ZIP entry with size validation. Returns None if unsafe."""
        if not self._is_safe_zip_entry(entry_name):
            return None
        try:
            info = zf.getinfo(entry_name)
            if info.file_size > self._ZIP_MAX_DECOMPRESS:
                return None
            return zf.read(entry_name)
        except Exception:
            return None

    @staticmethod
    def _is_safe_zip_entry(name: str) -> bool:
        # Normalize separators
        normalized = name.replace("\\", "/")
        # Reject absolute paths
        if normalized.startswith("/"):
            return False
        # Reject drive letters (e.g. C:/, D:\)
        if len(normalized) > 1 and normalized[1] == ":":
            return False
        # Reject parent directory traversal
        if ".." in normalized.split("/"):
            return False
        # Reject current directory references
        if normalized.startswith("./") or "/./" in normalized:
            return False
        return True

    def hash_file(self, path: Path) -> str:
        digest = sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def read_sample(self, path: Path) -> bytes:
        with path.open("rb") as f:
            return f.read(self.config.sample_size)

    def detect_binary(self, sample: bytes, mime_type: str) -> tuple[bool, ProvenanceEntry]:
        # UTF-16/UTF-32 text files contain interleaved NUL bytes by construction
        # (every other byte for ASCII content in UTF-16). The NUL-byte heuristic
        # below would always misclassify them as binary, so check for a leading
        # Unicode BOM first and treat BOM-prefixed files as text.
        bom_enc = _detect_unicode_bom(sample)
        if bom_enc is not None:
            return False, ProvenanceEntry(
                layer="derived", method="detect_binary",
                trigger="unicode_bom", inputs=["mime_type"],
                detail={"bom": bom_enc},
            )
        if b"\x00" in sample:
            return True, ProvenanceEntry(
                layer="derived", method="detect_binary",
                trigger="nul_byte", inputs=["mime_type"],
            )
        if any(mime_type.startswith(p) for p in BINARY_MIME_PREFIXES):
            return True, ProvenanceEntry(
                layer="derived", method="detect_binary",
                trigger="mime_prefix_binary", inputs=["mime_type"],
                detail={"mime_type": mime_type},
            )
        if mime_type in BINARY_MIME_TYPES:
            return True, ProvenanceEntry(
                layer="derived", method="detect_binary",
                trigger="known_binary_mime", inputs=["mime_type"],
                detail={"mime_type": mime_type},
            )
        if mime_type.startswith("application/") and mime_type not in TEXT_APP_MIMES:
            if not self.looks_like_text(sample):
                return True, ProvenanceEntry(
                    layer="derived", method="detect_binary",
                    trigger="text_ratio_failure", inputs=["mime_type"],
                    detail={"threshold": 0.85},
                )
        if not self.looks_like_text(sample):
            return True, ProvenanceEntry(
                layer="derived", method="detect_binary",
                trigger="text_ratio_failure", inputs=["mime_type"],
                detail={"threshold": 0.85},
            )
        return False, ProvenanceEntry(
            layer="derived", method="detect_binary",
            trigger="text_ratio_ok", inputs=["mime_type"],
            detail={"threshold": 0.85},
        )

    def looks_like_text(self, sample: bytes) -> bool:
        if not sample:
            return True
        text_chars = sum(
            1 for b in sample
            if b in b"\t\n\r\f\b" or 32 <= b <= 126 or b >= 128
        )
        return (text_chars / max(len(sample), 1)) >= 0.85

    @staticmethod
    def _label_content_pairs(text: str, drop_nonspeaker: bool = False) -> list[tuple[str, str]]:
        """(label, post-colon content) for each speaker-label line (v1.4.0).

        When ``drop_nonspeaker`` is set, labels in the non-speaker stop-list
        (From:/Usage:/Note:/Question: …) are excluded — used by detection so
        doc-section labels never count as turns (the stop-list is load-bearing;
        see the constant's note). The FAQ single letters Q/A are NOT stop-listed,
        so `A:`/`B:` dialogue is preserved for the complete-set rule.
        """
        pairs = [(m.group(1), m.group(2).strip())
                 for m in CHATLOG_LABEL_CONTENT_RE.finditer(text)]
        if drop_nonspeaker:
            pairs = [(l, c) for l, c in pairs
                     if l.casefold() not in CHATLOG_SPEAKER_STOP_LIST_CF]
        return pairs

    @staticmethod
    def _is_utterance(content: str) -> bool:
        """A turn is a phrase; a field value is atomic (RFC v1.4.0 §2.1).

        Utterance-like when it (a) contains a function word, (b) ends in
        sentence punctuation, (c) is multi-word, or (d) is long. The
        function-word arm is what separates terse-but-real dialogue ("hi *there*
        friend", "*how are you*") from atomic data values (John Smith, 1.00,
        localhost), which contain none; the punctuation arm rescues terse
        punctuated dialogue ("I attack!", "Roll for it."). Atomic-value classes
        clear none of the four arms, so they stay at ratio 0.0.
        """
        stripped = content.rstrip()
        if stripped and stripped[-1] in ".!?" and any(ch.isalpha() for ch in stripped):
            return True
        # normalize curly apostrophe (U+2019) so copy-pasted contractions match
        words = CHATLOG_WORD_RE.findall(content.lower().replace("’", "'"))
        if any(w in CHATLOG_FUNCTION_WORDS for w in words):
            return True
        return (len(content.split()) >= CHATLOG_UTTERANCE_MIN_WORDS
                or len(content) >= CHATLOG_UTTERANCE_MIN_CHARS)

    @classmethod
    def _chatlog_content_shape(cls, text: str) -> tuple[float, float]:
        """(utterance_ratio, density) over speaker-label lines. (0.0, 0.0) if none.
        Provisional observed signals surfaced in chatlog metadata (RFC §7)."""
        pairs = cls._label_content_pairs(text, drop_nonspeaker=True)
        if not pairs:
            return (0.0, 0.0)
        ur = sum(1 for _, c in pairs if cls._is_utterance(c)) / len(pairs)
        nonblank = sum(1 for ln in text.splitlines() if ln.strip())
        den = len(pairs) / nonblank if nonblank else 0.0
        return (round(ur, 3), round(den, 3))

    @classmethod
    def _prose_dialogue(cls, text: str) -> bool:
        """v1.4.0 prose dialogue rule — the v1.2.4 count rule PLUS a content-shape
        gate (RFC §2.2 + §3 + §4).

        Labels are first filtered by the (load-bearing) non-speaker stop-list,
        then must clear the count floor (>=2 distinct, >=3 total, >=1 recurring).
        What v1.4.0 ADDS on top: a content-shape gate (`utterance_ratio`) that
        rejects cyclic data tables (Item:/Price: — recurring but atomic, a v1.2.4
        false positive) while admitting terse-but-real dialogue via the
        function-word / punctuation arms; a closed FP-lexicon dominance rule
        (`Added:`-style changelogs); a version-TAG structure vote-against (release
        notes; dated-journal headers do NOT vote against); and a FAQ complete-set
        exclusion. (A density floor was prototyped and DROPPED in review — it is
        surfaced as an observation but does not gate; see the NOTE below.)
        Recurrence is retained — the all-distinct roll-call FN is accepted (see
        LIMITATIONS), as is ultra-terse contentless dialogue ("hi"/"bye"), which
        is irreducibly ambiguous with atomic data.
        """
        pairs = cls._label_content_pairs(text, drop_nonspeaker=True)
        if not pairs:
            return False
        counts = Counter(lbl for lbl, _ in pairs)
        distinct = list(counts)
        # §2.2.1 structural floor — recurrence retained (decision Q3)
        if not (len(counts) >= 2 and sum(counts.values()) >= 3
                and any(c >= 2 for c in counts.values())):
            return False
        # §4 FAQ complete-set exclusion (subset test: {A,B} survives, {Q,A} rejected)
        if all(d.casefold() in CHATLOG_FAQ_LABELS for d in distinct):
            return False
        # §2.2.2 content-shape — the primary non-count signal
        ur = sum(1 for _, c in pairs if cls._is_utterance(c)) / len(pairs)
        if ur < CHATLOG_UTTERANCE_MIN_RATIO:
            return False
        # §3.3 FP-lexicon dominance (closed list; one stray label doesn't reject)
        lex_hits = sum(1 for d in distinct if d.casefold() in CHATLOG_FP_LABEL_LEXICON)
        if lex_hits >= len(distinct) * CHATLOG_FP_LEXICON_DOMINANCE:
            return False
        # §3.2 structure vote-against — changelog / release-notes (version-tagged
        # headers only; dated-journal headers deliberately do NOT vote against)
        if len(CHATLOG_VERSION_HEADER_RE.findall(text)) >= CHATLOG_STRUCTURE_HEADER_MIN:
            return False
        # NOTE: no density gate. A density floor was prototyped (reject labels
        # sprinkled in prose) but review falsified it — it false-NEGATIVES common
        # multi-line-turn dialogue (3+ lines/turn → density < 0.5) while the
        # sprinkled-prose case it targeted sits at HIGHER density (~0.43) than the
        # dialogue it breaks, so no threshold separates them. `density` is still
        # surfaced as an observation (content_shape), but recurring-label-in-prose
        # joins the accepted recurring-taxonomy FP residual (see LIMITATIONS).
        return True

    def _detect_chatlog_pattern(self, text: str) -> bool:
        """Content-based detection of chatlog / journal / vault structure.

        Returns True if the decoded text matches any of the rules:

          1. (v1.4.0) Prose dialogue — the count rule plus a content-shape gate
             (``_prose_dialogue``); rejects cyclic data tables, admits terse
             dialogue, excludes changelogs/FAQs/release-notes.
          2/3. (v1.2) Markdown structure — 5+ ``### `` headers OR 3+ section
             dividers — but ONLY with a conversational co-signal: 2+ distinct
             non-stop-list labels (unchanged from v1.2.4 — real-data
             falsification showed the stop-list is load-bearing here, suppressing
             doc-section labels (Usage:/Authorization:) the content signal can't).
          4. Conversational JSON/JSONL (generalized, v1.2).

        Detection runs even when ``enable_specialists=False`` because it's
        cheap (regex on the already-decoded baseline text).
        """
        if not text:
            return False
        # Rule 1 (v1.4.0): prose dialogue (count floor + content-shape gate).
        if self._prose_dialogue(text):
            return True
        # Rules 2/3 (v1.2): markdown structure counts only with a conversational
        # co-signal — 2+ distinct non-stop-list labels. This is a STRUCTURE rule,
        # not a content-shape rule, so the co-signal uses the label-only regex
        # (CHATLOG_SPEAKER_LABEL_RE, matches a label regardless of same-line
        # content) — NOT _label_content_pairs, whose `[ \t]+content` requirement
        # would miss labels written on their own line (`Alice:\n<utterance>`,
        # screenplay/script style) and lose the co-signal v1.3.0 had (review
        # 2026-06-02: both the in-house and Gemini passes flagged this FN).
        # Stop-list filtering still excludes doc-section labels (Usage:/Note:).
        speaker_labels = {m.group(1) for m in CHATLOG_SPEAKER_LABEL_RE.finditer(text)
                          if m.group(1).casefold() not in CHATLOG_SPEAKER_STOP_LIST_CF}
        structure_cosignal = len(speaker_labels) >= 2
        if structure_cosignal and len(CHATLOG_H3_HEADER_RE.findall(text)) >= 5:
            return True
        if structure_cosignal and len(CHATLOG_SECTION_DIVIDER_RE.findall(text)) >= 3:
            return True
        # Rule 4 (v1.2): generalized conversational JSON/JSONL detection
        # (line-delimited, arrays, nested trees, embedded speaker labels).
        return self._detect_conversational_json(text)

    @classmethod
    def _string_has_speaker_dialogue(cls, s: Any) -> bool:
        """Dialogue embedded in a JSON string value (e.g. hh-rlhf's
        '\\n\\nHuman: ...\\n\\nAssistant: ...'). v1.4.0: applies the SAME content-
        shape composite as prose Rule 1 (RFC §6 parity) — so the same text isn't
        detected inside a JSON string yet rejected as prose, or vice-versa."""
        if not isinstance(s, str) or len(s) < 20:
            return False
        return cls._prose_dialogue(s)

    def _detect_conversational_json(self, text: str) -> bool:
        """Generalized conversational JSON/JSONL detection (v1.2; tightened v1.2.1).

        Handles line-delimited messages (ConvoKit speaker/text, Claude
        type+message.content), nested trees (oasst prompt.role+replies), message
        arrays (ShareGPT from/value), dialogue embedded in a string field
        (hh-rlhf), and truncated large single-JSON via a regex fallback.

        A conversation requires **3+ messages with 2+ DISTINCT speakers**. The
        distinct-speaker rule (v1.2.1) is what separates a real conversation
        from a structured log (`type:"info"` repeated), a single-role stream, or
        Claude rich-content blocks — all of which carry <2 distinct roles and
        previously false-positived.
        """
        speakers = [sp for sp, _ in self._extract_json_conversation(text)]
        if len(speakers) >= 3 and len(set(speakers)) >= 2:
            return True
        # Regex fallback ONLY when the parser extracted nothing — a truncated/
        # large single-JSON it couldn't read (e.g. a multi-MB ShareGPT file).
        # Gated on `not speakers` so it can't override the parser on readable
        # input (otherwise inner content blocks would re-inflate the count).
        # Regex fallback ONLY for a truncated/unparseable single-JSON (the
        # parser read nothing AND the sample doesn't parse). A parseable-but-
        # non-conversational doc (e.g. a structured log whose `type` values were
        # correctly rejected as non-speakers) must NOT be rescued here.
        if not speakers and not self._sample_parses_as_json(text):
            matches = CHATLOG_JSON_MESSAGE_RE.findall(text)
            if len(matches) >= 3:
                # role values from the message-like matches only, 2+ distinct
                roles = [m.group(1) for m in
                         (CHATLOG_JSON_ROLE_VALUE_RE.search(s) for s in matches) if m]
                if len(set(roles)) >= 2:
                    return True
        return False

    @staticmethod
    def _sample_parses_as_json(text: str) -> bool:
        """True if the sample contains at least one parseable JSON value.
        Gates the regex fallback so it fires only on truly-unparseable
        (truncated) input, not on readable non-conversational JSON."""
        for ln in text.split("\n"):
            ln = ln.strip()
            if ln and ln[0] in "{[":
                try:
                    json.loads(ln)
                    return True
                except (json.JSONDecodeError, ValueError):
                    pass
        s = text.strip()
        if s[:1] in "{[":
            try:
                json.loads(s)
                return True
            except (json.JSONDecodeError, ValueError):
                pass
        return False

    @staticmethod
    def _message_role_content(obj: dict) -> tuple[str, str] | None:
        """(speaker, content_text) for a message-like dict, else None.

        v1.2.1: `type` counts as the speaker only when its value is a
        conversational role (Claude's type:user/assistant); a non-conversational
        `type` (a wrapper like "message", a log level "info", a content block
        "text") is skipped so the next role key (role/from/speaker/author) wins.
        """
        speaker = None
        for k in CHATLOG_ROLE_FIELD_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                val = v.strip()
            elif isinstance(v, int):
                val = str(v)
            else:
                continue
            if k == "type" and val.lower() not in CHATLOG_CONVERSATIONAL_TYPE_VALUES:
                continue  # `type` is a speaker only for conversational values
            speaker = val
            break
        if speaker is None:
            return None
        for k in CHATLOG_CONTENT_FIELD_KEYS:
            if k not in obj:
                continue
            v = obj[k]
            if isinstance(v, str) and v.strip():
                return (speaker, v)
            if isinstance(v, dict):
                c = v.get("content")
                if isinstance(c, str) and c.strip():
                    return (speaker, c)
                if isinstance(c, list):
                    parts = [it["text"] for it in c if isinstance(it, dict) and isinstance(it.get("text"), str)]
                    if parts:
                        return (speaker, "\n".join(parts))
            if isinstance(v, list):
                parts = [it["text"] for it in v if isinstance(it, dict) and isinstance(it.get("text"), str)]
                if parts:
                    return (speaker, "\n".join(parts))
        return None

    @staticmethod
    def _parse_embedded_dialogue(s: str) -> list[tuple[str, str]]:
        """Split a string with prose speaker labels into (speaker, text) pairs
        (e.g. hh-rlhf's '\\n\\nHuman: ...\\n\\nAssistant: ...')."""
        pairs: list[tuple[str, str]] = []
        matches = [m for m in CHATLOG_SPEAKER_LABEL_RE.finditer(s)
                   if m.group(1).casefold() not in CHATLOG_SPEAKER_STOP_LIST_CF]
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(s)
            pairs.append((m.group(1), s[m.end():end].strip()))
        return pairs

    def _extract_json_conversation(self, text: str, cap: int = 2000) -> list[tuple[str, str]]:
        """Ordered (speaker, content) pairs from conversational JSON/JSONL —
        line-delimited messages, arrays, nested trees, and embedded dialogue."""
        pairs: list[tuple[str, str]] = []
        seen = [0]

        def walk(node: Any) -> None:
            stack = [node]
            while stack and len(pairs) < cap and seen[0] < 20000:
                cur = stack.pop(); seen[0] += 1
                if isinstance(cur, dict):
                    rc = self._message_role_content(cur)
                    if rc:
                        pairs.append(rc)
                        # recurse only into non-role/content fields (e.g. replies),
                        # not this message's own content sub-structure
                        stack.extend(reversed([v for k, v in cur.items()
                            if k not in CHATLOG_ROLE_FIELD_KEYSET
                            and k not in CHATLOG_CONTENT_FIELD_KEYSET]))
                    else:
                        for v in cur.values():
                            if isinstance(v, str) and self._string_has_speaker_dialogue(v):
                                pairs.extend(self._parse_embedded_dialogue(v))
                        stack.extend(reversed(list(cur.values())))
                elif isinstance(cur, list):
                    stack.extend(reversed(cur))

        parsed_any = False
        for line in text.split("\n"):
            line = line.strip()
            if not line or line[0] not in "{[":
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            parsed_any = True
            walk(obj)
            if len(pairs) >= cap:
                break
        if not parsed_any:
            s = text.strip()
            if s[:1] in "{[":
                try:
                    walk(json.loads(s))
                except (json.JSONDecodeError, ValueError):
                    pass
        return pairs

    # Default top-N for capitalized tokens. Per spec §2.5 N=20.
    _CHATLOG_TOP_TOKENS_N = 20

    def _extract_chatlog_metadata(self, text: str) -> dict[str, Any] | None:
        """Extract drift-visible signals from a chatlog/journal/vault text.

        Supports two formats:
        - Prose with speaker labels (v0.8+: .txt/.md/.mdx)
        - JSONL with role-bearing JSON objects (v0.10.1: .jsonl)

        For JSONL, message text is extracted from JSON objects and concatenated,
        then the standard text-based extraction runs on the concatenated content.

        Per spec §2.5 / §2.6:

        - ``turn_count`` is the raw number of speaker label occurrences.
        - ``speaker_labels`` is sorted alphabetically and filtered to tokens
          that appear 3+ times (eliminates one-off proper nouns).
        - ``avg/min/max_turn_chars`` are character distances between
          consecutive raw speaker labels.
        - Section markers count both pure-divider lines (``---``, ``===``,
          ``***``, ``###``) and Markdown header lines (``# `` … ``###### ``);
          styles are output normalized.
        - ``top_capitalized_tokens`` is the top-N (default 20) tokens of
          length 3+ that appear 3+ times, sorted by frequency desc with
          alphabetical secondary; ``capitalized_token_count`` is the cardinality
          of that qualifying set.
        - ``vocabulary_size_estimate`` is the count of distinct lowercase
          word-tokens after lowercasing the whole text.

        See spec §2.7 for what this DOES NOT do (no NLP, no entity resolution,
        no interpretation).
        """
        if not text:
            return None

        # v1.2: generalized conversational-JSON extraction (mirrors detection —
        # line-delimited messages, arrays, nested trees, embedded dialogue).
        json_pairs = self._extract_json_conversation(text)
        jsonl_mode = len(json_pairs) >= 3
        turn_lengths_seq: list[tuple[str, int]] = []
        speaker_seq: list[str] = []

        if jsonl_mode:
            jsonl_roles = [sp for sp, _ in json_pairs]
            message_texts = [txt for _, txt in json_pairs]
            speaker_seq = jsonl_roles
            turn_lengths_seq = [(sp, len(txt)) for sp, txt in json_pairs]
            turn_count = len(jsonl_roles)
            label_counts = Counter(jsonl_roles)
            speaker_labels = sorted(
                label for label, count in label_counts.items() if count >= 3
            )
            concat_text = "\n".join(message_texts) if message_texts else ""
            avg_turn_chars = max_turn_chars = min_turn_chars = 0
            lengths = [len(t) for t in message_texts if t]
            if lengths:
                avg_turn_chars = int(sum(lengths) / len(lengths))
                max_turn_chars = max(lengths)
                min_turn_chars = min(lengths)
            section_marker_count = 0
            section_marker_styles: list[str] = []
        else:
            concat_text = text

            # --- Speaker labels and turn statistics (prose mode) ---
            # v0.9.1: filter stop-list tokens from both detection and turn metrics
            raw_label_matches = [
                m for m in CHATLOG_SPEAKER_LABEL_RE.finditer(text)
                if m.group(1).casefold() not in CHATLOG_SPEAKER_STOP_LIST_CF
            ]
            turn_count = len(raw_label_matches)
            label_counts = Counter(m.group(1) for m in raw_label_matches)
            speaker_labels = sorted(
                label for label, count in label_counts.items()
                if count >= 3
            )
            # v1.2: per-speaker sequence + attributed turn lengths (prose mode)
            speaker_seq = [m.group(1) for m in raw_label_matches]
            for i, mm in enumerate(raw_label_matches):
                seg_end = raw_label_matches[i + 1].start() if i + 1 < len(raw_label_matches) else len(text)
                turn_lengths_seq.append((mm.group(1), max(0, seg_end - mm.end())))
            # Char distance between consecutive speaker labels.
            avg_turn_chars = 0
            max_turn_chars = 0
            min_turn_chars = 0
            if len(raw_label_matches) >= 2:
                turn_lengths: list[int] = []
                for i in range(len(raw_label_matches) - 1):
                    length = raw_label_matches[i + 1].start() - raw_label_matches[i].end()
                    if length > 0:
                        turn_lengths.append(length)
                if turn_lengths:
                    avg_turn_chars = int(sum(turn_lengths) / len(turn_lengths))
                    max_turn_chars = max(turn_lengths)
                    min_turn_chars = min(turn_lengths)

            # --- Section markers (pure dividers + markdown headers) ---
            section_marker_count = 0
            section_marker_styles_set: set[str] = set()
            for divider_match in CHATLOG_PURE_DIVIDER_RE.finditer(text):
                section_marker_count += 1
                section_marker_styles_set.add(divider_match.group(1) * 3)
            for header_match in CHATLOG_MD_HEADER_RE.finditer(text):
                section_marker_count += 1
                section_marker_styles_set.add(header_match.group(1) + " ")
            section_marker_styles = sorted(section_marker_styles_set)

        # --- Reference tokens (runs on concat_text for both modes) ---
        at_mentions = len(CHATLOG_AT_MENTION_RE.findall(concat_text))
        wiki_links = len(CHATLOG_WIKI_LINK_RE.findall(concat_text))
        code_fence_blocks = concat_text.count("```") // 2
        url_count = len(CHATLOG_URL_RE.findall(concat_text))

        # --- Capitalized tokens (length 3+, frequency 3+) ---
        cap_token_counts = Counter(CHATLOG_CAPITALIZED_TOKEN_RE.findall(concat_text))
        qualifying_caps = [
            (token, count) for token, count in cap_token_counts.items() if count >= 3
        ]
        # Sort: frequency desc, then alphabetical (per spec §2.5).
        qualifying_caps.sort(key=lambda tc: (-tc[1], tc[0]))
        capitalized_token_count = len(qualifying_caps)
        top_capitalized_tokens = [
            token for token, _ in qualifying_caps[: self._CHATLOG_TOP_TOKENS_N]
        ]

        # --- Vocabulary size estimate ---
        # Lowercase the whole text first so we catch all word-shaped tokens
        # regardless of original case. Distinct count is the vocabulary signal.
        lowercase_words = CHATLOG_LOWERCASE_WORD_RE.findall(concat_text.lower())
        vocabulary_size_estimate = len(set(lowercase_words))

        # --- v1.2 (provisional): per-speaker turn structure ---
        speaker_turn_counts = dict(sorted(Counter(speaker_seq).items()))
        _per_speaker: dict[str, list[int]] = {}
        for sp, ln in turn_lengths_seq:
            _per_speaker.setdefault(sp, []).append(ln)
        speaker_turn_chars = {
            sp: {"avg": int(sum(ls) / len(ls)), "max": max(ls), "min": min(ls)}
            for sp, ls in sorted(_per_speaker.items()) if ls
        }
        longest_run = cur_run = changes = 0
        prev: str | None = None
        for sp in speaker_seq:
            if sp == prev:
                cur_run += 1
            else:
                cur_run = 1
                if prev is not None:
                    changes += 1
            longest_run = max(longest_run, cur_run)
            prev = sp
        change_ratio = round(changes / (len(speaker_seq) - 1), 3) if len(speaker_seq) > 1 else 0.0
        alternation = {
            "longest_single_speaker_run": longest_run,
            "speaker_change_ratio": change_ratio,
        }

        # v1.4.0 (provisional, RFC §7): the content-shape signals that drive prose
        # detection, surfaced so consumers can see *why* detection fired. They are
        # prose-label measures — null in JSONL mode, where the JSON path decides.
        if jsonl_mode:
            content_shape: dict[str, float] | None = None
        else:
            ur, den = self._chatlog_content_shape(text)
            content_shape = {"utterance_ratio": ur, "density": den}

        return {
            "turn_count": turn_count,
            "speaker_labels": speaker_labels,
            "speaker_turn_counts": speaker_turn_counts,
            "speaker_turn_chars": speaker_turn_chars,
            "alternation": alternation,
            "content_shape": content_shape,
            "section_marker_count": section_marker_count,
            "section_marker_styles": section_marker_styles,
            "avg_turn_chars": avg_turn_chars,
            "max_turn_chars": max_turn_chars,
            "min_turn_chars": min_turn_chars,
            "reference_tokens": {
                "at_mentions": at_mentions,
                "wiki_links": wiki_links,
                "code_fence_blocks": code_fence_blocks,
                "url_count": url_count,
            },
            "top_capitalized_tokens": top_capitalized_tokens,
            "capitalized_token_count": capitalized_token_count,
            "vocabulary_size_estimate": vocabulary_size_estimate,
        }

    def _extract_email_body(self, path: Path, extension: str, sample: bytes) -> str | None:
        """Extract the plain-text body from an email file for cross-cut analysis.

        v0.9: used by the email body chatlog cross-cut (spec §4.1).
        """
        if extension == ".eml":
            try:
                from email.parser import BytesParser
                from email.policy import default as email_policy
                msg = BytesParser(policy=email_policy).parsebytes(sample)
                body = msg.get_body(preferencelist=("plain",))
                if body:
                    content = body.get_content()
                    return content if isinstance(content, str) else None
            except Exception:
                return None
        elif extension == ".msg" and olefile:
            try:
                if not olefile.isOleFile(str(path)):
                    return None
                ole = olefile.OleFileIO(str(path))
                try:
                    # PR_BODY (0x1000) — Unicode (001F) or ANSI (001E)
                    body = self._msg_read_property(ole, "__substg1.0_1000001F") or \
                           self._msg_read_property(ole, "__substg1.0_1000001E")
                    return body
                finally:
                    ole.close()
            except Exception:
                return None
        return None

    def _extract_reference_tokens(self, text: str) -> dict[str, int]:
        """v0.9: extract reference token counts per spec §3.2.

        Runs on every text-eligible file. Returns counts for seven subcategories.
        """
        # v0.9.2: strip URLs before counting path references to avoid
        # matching URL path fragments (e.g. googleapis.com/auth/chat).
        # The original regex is kept simple; URL removal handles context.
        text_no_urls = CHATLOG_URL_RE.sub("", text)
        return {
            "at_mentions": len(CHATLOG_AT_MENTION_RE.findall(text)),
            "wiki_links": len(CHATLOG_WIKI_LINK_RE.findall(text)),
            "code_fence_blocks": text.count("```") // 2,
            "url_count": len(CHATLOG_URL_RE.findall(text)),
            "email_mentions": len(REFERENCE_EMAIL_RE.findall(text)),
            "path_references": len(REFERENCE_PATH_UNIX_RE.findall(text_no_urls)) + len(REFERENCE_PATH_WIN_RE.findall(text_no_urls)),
            "numeric_id_patterns": len(REFERENCE_TICKET_RE.findall(text)) + len(REFERENCE_SEMVER_RE.findall(text)) + len(REFERENCE_PROJECT_ID_RE.findall(text)),
        }

    def detect_requires_vision(
        self, path: Path, sample: bytes, mime_type: str, extension: str, is_binary: bool
    ) -> tuple[bool, ProvenanceEntry]:
        if mime_type.startswith("image/"):
            return True, ProvenanceEntry(
                layer="derived", method="detect_requires_vision",
                trigger="image_mime", inputs=["mime_type"],
            )
        if extension == ".pdf" and is_binary:
            # v1.5: decide over head + bounded tail, not the 8 KB head alone. The
            # head-only check mis-flagged born-digital PDFs whose content streams
            # are compressed (no plaintext BT/Font in the head) as needing vision.
            region = self._pdf_scan_region(path, sample, PDF_MARKER_BUDGET)
            has_text = (b"/Font" in region or b"/Text" in region
                        or bool(re.search(rb"\bBT\b", region)))
            if has_text:
                return False, ProvenanceEntry(
                    layer="derived", method="detect_requires_vision",
                    trigger="pdf_text_detected", inputs=["mime_type", "is_binary"],
                )
            has_image = any(t in region for t in
                            (b"/Image", b"/XObject", b"/DCTDecode", b"/CCITTFax",
                             b"/JPXDecode", b"/JBIG2Decode"))
            if has_image:
                return True, ProvenanceEntry(
                    layer="derived", method="detect_requires_vision",
                    trigger="pdf_image_only", inputs=["mime_type", "is_binary"],
                )
            # No text AND no image markers (e.g. an object-stream PDF that compresses
            # both): conservatively NOT vision — err away from a false "needs OCR" on
            # a PDF that is most likely compressed-but-textual. Documented residual.
            return False, ProvenanceEntry(
                layer="derived", method="detect_requires_vision",
                trigger="pdf_no_markers", inputs=["mime_type", "is_binary"],
            )
        return False, ProvenanceEntry(
            layer="derived", method="detect_requires_vision",
            trigger="not_applicable", inputs=["mime_type"],
        )

    def decode_text(self, sample: bytes, path: Path, max_read: int | None = None) -> tuple[str, str, ProvenanceEntry]:
        detected_enc: str | None = None
        chardet_confidence: float = 0.0
        if chardet:
            detected = chardet.detect(sample)
            if detected and detected.get("encoding"):
                enc = detected["encoding"].lower()
                chardet_confidence = detected.get("confidence", 0) or 0
                if chardet_confidence >= 0.5:
                    detected_enc = enc
        max_bytes = max_read or max(self.config.baseline_max_bytes, self.config.sample_size)
        with path.open("rb") as f:
            raw = f.read(max_bytes)
        if detected_enc:
            try:
                prov = ProvenanceEntry(
                    layer="derived", method="decode_text",
                    trigger="chardet_confident",
                    detail={"encoding": detected_enc, "confidence": chardet_confidence},
                )
                return detected_enc, raw.decode(detected_enc), prov
            except (UnicodeDecodeError, LookupError):
                pass
        cascade_encodings = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
        for enc in cascade_encodings:
            try:
                trigger = f"cascade_{enc.replace('-', '_')}"
                prov = ProvenanceEntry(
                    layer="derived", method="decode_text",
                    trigger=trigger,
                )
                return enc, raw.decode(enc), prov
            except UnicodeDecodeError:
                continue
        prov = ProvenanceEntry(
            layer="derived", method="decode_text",
            trigger="replace",
        )
        return "unknown", raw.decode("utf-8", errors="replace"), prov

    def make_preview(self, text: str, max_chars: int | None = None) -> str:
        normalized = CONTROL_CHAR_RE.sub("", text).strip()
        return normalized[: max_chars or self.config.preview_max_chars]

    def extract_tags(self, text: str) -> list[str]:
        stripped = CODE_STRIP_RE.sub("", text)
        return sorted(
            tag for tag in set(HASHTAG_RE.findall(stripped))
            if not HEX_COLOR_RE.match(tag) and tag.lower() not in TAG_STOP_WORDS
        )

    def extract_frontmatter(self, text: str) -> FrontmatterRecord:
        match = FRONTMATTER_RE.search(text)
        if match:
            raw = match.group(1)
            keys = self._parse_frontmatter_keys(raw)
            return FrontmatterRecord(exists=True, keys=keys, raw=raw)
        # Detect malformed frontmatter: opening --- without closing ---
        if FRONTMATTER_OPEN_RE.match(text):
            # Normalize line endings then split
            normalized = text.replace("\r\n", "\n")
            raw = normalized.split("\n", 1)[1] if "\n" in normalized else ""
            return FrontmatterRecord(exists=False, keys=[], raw=raw)
        return FrontmatterRecord()

    def _parse_frontmatter_keys(self, raw: str) -> list[str]:
        """Extract top-level keys from frontmatter YAML. Uses PyYAML when available."""
        if yaml:
            try:
                parsed = yaml.safe_load(raw)
                if isinstance(parsed, dict):
                    return sorted(str(k) for k in parsed.keys())
            except Exception:
                pass
        # Fallback: string splitting
        keys = []
        for line in raw.splitlines():
            if ":" in line:
                key = line.split(":", 1)[0].strip()
                if key:
                    keys.append(key)
        return sorted(set(keys))

    def tags_from_frontmatter(self, raw: str) -> list[str]:
        tags: list[str] = []
        for line in raw.splitlines():
            if line.lower().startswith("tags:"):
                _, rhs = line.split(":", 1)
                for item in re.split(r"[,\[\]]", rhs):
                    value = item.strip().strip("'-\"")
                    if value:
                        tags.append(value)
        return tags

    def extract_assets(self, text: str) -> list[str]:
        matches = []
        for candidate in ASSET_RE.findall(text):
            candidate = candidate.strip()
            if candidate and not candidate.startswith(("http://", "https://")):
                matches.append(candidate)
        return sorted(set(matches))

    def extract_filename_date(self, filename: str) -> str | None:
        match = FILENAME_DATE_RE.search(filename)
        if not match:
            return None
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

    def extract_html_title(self, text: str) -> str | None:
        match = HTML_TITLE_RE.search(text)
        if match:
            title = match.group(1).strip()
            if title:
                return title
        return None

    def extract_md_title(self, text: str) -> str | None:
        for match in MD_HEADING_RE.finditer(text):
            if len(match.group(1)) == 1:
                return match.group(2).strip()
        return None

    def extract_heading_structure(self, text: str) -> list[str]:
        headings = []
        for match in MD_HEADING_RE.finditer(text):
            level = len(match.group(1))
            if level == 2:
                headings.append(match.group(2).strip())
        return headings

    def extract_csv_headers(self, text: str) -> list[str]:
        first_line = text.split("\n", 1)[0].strip()
        if not first_line:
            return []
        headers = [h.strip().strip('"') for h in first_line.split(",")]
        # Sanity check: if all "headers" look like numeric data, it's not a header row
        if all(h.replace(".", "").replace("-", "").isdigit() for h in headers if h):
            return []
        return headers

    def extract_yaml_keys(self, text: str) -> list[str]:
        keys = []
        for line in text.splitlines():
            if line and not line[0].isspace() and not line.startswith("#") and ":" in line:
                key = line.split(":", 1)[0].strip()
                if key and not key.startswith("---"):
                    keys.append(key)
        return keys

    def extract_json_keys(self, text: str) -> list[str]:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return sorted(data.keys())
        except (json.JSONDecodeError, ValueError):
            pass
        return []

    def extract_xml_keys(self, text: str) -> list[str]:
        try:
            root = xml_fromstring(text)
            keys = [root.tag]
            child_tags = sorted({child.tag for child in root})
            keys.extend(child_tags)
            return keys
        except Exception:
            return []

    def extract_toml_keys(self, text: str) -> list[str]:
        if not tomllib:
            return []
        try:
            data = tomllib.loads(text)
            return sorted(data.keys())
        except Exception:
            return []

    def detect_technology(self, text: str) -> list[str]:
        found: set[str] = set()
        for name, pattern in TECHNOLOGY_PATTERNS:
            if pattern.search(text):
                found.add(name)
        return sorted(found)

    def scan_signatures(self, sample: bytes) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
        """Scan sample for magic byte signatures. Returns (file_signature, format_signatures, is_polyglot)."""
        if not sample:
            return None, [], False
        # Raw file signature (first 16 bytes as hex)
        sig_len = min(16, len(sample))
        file_sig = {"magic_bytes": sample[:sig_len].hex(), "magic_length": sig_len}
        # Scan for known format signatures (v1.3: multi-constraint matcher)
        found: list[dict[str, Any]] = []
        seen_formats: set[str] = set()
        for constraints, fmt in MAGIC_SIGNATURES:
            off = self._signature_matches(sample, constraints)
            if off is not None:
                found.append({"format": fmt, "offset": off})
                seen_formats.add(fmt)
        # A recognized RIFF sub-type supersedes the generic riff_container label,
        # so a known RIFF file emits exactly one signature (no false polyglot).
        if seen_formats & {"image/webp", "audio/wav", "video/x-msvideo"}:
            found = [s for s in found if s["format"] != "riff_container"]
            seen_formats.discard("riff_container")
        # v1.15: same pattern for ISO-BMFF `ftyp` — a recognized image brand
        # (HEIC/HEIF/AVIF) supersedes the generic video/mp4 ftyp label, so a real
        # iPhone photo emits one signature, not a false image+video polyglot.
        # (v1.15.1: image/heif added when generic HEIF brands split off image/heic.)
        if seen_formats & {"image/heic", "image/heif", "image/avif"}:
            found = [s for s in found if s["format"] != "video/mp4"]
            seen_formats.discard("video/mp4")
        found.sort(key=lambda x: x["offset"])
        is_polyglot = len(seen_formats) > 1
        return file_sig, found, is_polyglot

    @staticmethod
    def _signature_matches(
        sample: bytes, constraints: tuple[tuple[int | None, bytes], ...]
    ) -> int | None:
        """v1.3: return the anchor offset if ALL (offset, pattern) constraints
        match the head sample, else None. offset=int is anchored; offset=None
        means the pattern occurs anywhere in the sample. Shared by
        scan_signatures and _sniff_mime so the two never drift apart."""
        if not constraints:
            return None
        anchor: int | None = None
        for offset, pattern in constraints:
            if offset is not None:
                if sample[offset:offset + len(pattern)] != pattern:
                    return None
                pos = offset
            else:
                pos = sample.find(pattern)
                if pos < 0:
                    return None
            if anchor is None:
                anchor = pos
        return anchor if anchor is not None else 0

    def _sniff_mime(self, sample: bytes) -> str | None:
        """v1.3: pure-Python content-based MIME from MAGIC_SIGNATURES (no
        libmagic). First matching signature whose label is a MIME type wins;
        table order puts specific signatures (RIFF sub-types) first. Signatures
        are precise enough not to collide with prose (review: dropped the 2-byte
        MZ/BM; ID3 and bzip2 carry a corroborating byte), so no text-gate is
        needed — PDF/RTF/PostScript (ASCII-headed) still sniff correctly."""
        if not sample:
            return None
        for constraints, fmt in MAGIC_SIGNATURES:
            if "/" in fmt and self._signature_matches(sample, constraints) is not None:
                return fmt
        return None

    def detect_safety_flags(self, extension: str, sample: bytes, zip_entries: list[str] | None = None) -> list[str]:
        flags: list[str] = []
        # PDF: JavaScript
        if extension == ".pdf":
            if b"/JS" in sample or b"/JavaScript" in sample or b"/S/JavaScript" in sample:
                flags.append("has_javascript")
        # DOCX: macros
        if extension == ".docx" and zip_entries:
            if any(e in ("word/vbaProject.bin", "word/vbaData.xml") for e in zip_entries):
                flags.append("has_macros")
        # RTF: embedded OLE objects
        if extension == ".rtf":
            if b"\\objemb" in sample or b"\\objlink" in sample:
                flags.append("has_ole_objects")
        # XML: external entities
        if extension in {".xml", ".vx"}:
            if b"<!ENTITY" in sample and (b"SYSTEM" in sample or b"PUBLIC" in sample):
                flags.append("has_external_references")
        return sorted(flags)

    def _get_zip_entries(self, path: Path, budget: int) -> list[str] | None:
        """Get ZIP entry names by reading the central directory from end of file.

        ZIP central directory is at the end of the archive. We let zipfile seek
        to it directly. zipfile.ZipFile only reads the central directory bytes
        for namelist() — it does not read entry content. This is bounded by
        the size of the central directory itself, not the full archive.

        Files smaller than budget bytes are also handled correctly (zipfile
        will read what it needs).
        """
        import zipfile
        try:
            # Skip reading if file is enormous and we'd cause memory pressure
            # via the central directory. In practice, central directories are
            # tiny (KB range). budget is used here only as a safety ceiling
            # against pathological archives.
            try:
                file_size = path.stat().st_size
            except Exception:
                return None
            if file_size > 10 * budget:
                # Pathological size — refuse rather than risk OOM on a malformed CD
                return None
            with zipfile.ZipFile(str(path)) as zf:
                return zf.namelist()
        except Exception:
            return None

    def detect_sidecar(self, path: Path) -> bool:
        candidates = [
            path.with_suffix(path.suffix + ".json"),
            path.with_suffix(path.suffix + ".md"),
            path.with_name(path.stem + ".json"),
        ]
        # A max-length base name makes a candidate exceed the 255-byte filesystem
        # limit → `.exists()` raises OSError [Errno 36]. Guard EACH candidate
        # independently so one over-long candidate can't (a) abort the scan
        # (red-team #4) or (b) hide a valid shorter sidecar that exists (PR review:
        # a single try/except around the whole `any()` would skip the rest).
        for c in candidates:
            try:
                if c.exists():
                    return True
            except OSError:
                continue
        return False

    def run_specialist_probe(self, path: Path, extension: str, errors: list[ErrorRecord]) -> None:
        if extension == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(ErrorRecord(ERR_JSON_PARSE_FAILED, str(exc), "specialist"))
        elif extension in {".pdf", ".docx", ".rtf"}:
            return

    def safe_created_at(self, stat: os.stat_result) -> str | None:
        try:
            birth = getattr(stat, "st_birthtime", None)
            if birth is None:
                return None
            return self.ts_to_iso(birth)
        except (OSError, ValueError):
            return None

    def ts_to_iso(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


def _dc_encoder(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    raise TypeError(f"Unsupported type: {type(obj)!r}")


def compute_manifest_checksum(manifest: ScanManifest) -> str:
    """Compute SHA-256 of the manifest content, excluding volatile fields."""
    d = asdict(manifest)
    d["manifest_checksum"] = ""
    d["manifest_signature"] = None  # signature depends on checksum, excluded
    # Exclude volatile fields from deterministic checksum per RFC §Deterministic serialization
    d["meta"]["scan_id"] = ""
    d["meta"]["generated_at"] = ""
    canonical = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def manifest_to_json(manifest: ScanManifest) -> str:
    return json.dumps(manifest, default=_dc_encoder, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# v1.13: `--schema` self-description. Introspects the installed build's
# COMPLETE output surface from the module's registries + dataclasses and emits
# a deterministic, sorted schema document. No scan, no source dir, no manifest;
# `--schema` short-circuits the normal CLI path (like --help). Reflects what
# the build CAN emit, not what any particular scan did emit. SCHEMA_VERSION
# (the manifest contract) is unchanged; this is a SEPARATE surface.
# ---------------------------------------------------------------------------

def _dataclass_field_map(cls: type) -> list[dict[str, str]]:
    """[{name, type}] for a dataclass's fields, in declaration order. With
    `from __future__ import annotations` (this module) f.type is the verbatim
    source string of the annotation."""
    import dataclasses as _dc
    out = []
    for f in _dc.fields(cls):
        t = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", str(f.type))
        stability = "provisional" if (cls.__name__, f.name) in PROVISIONAL_MANIFEST_FIELDS else "stable"
        out.append({"name": f.name, "type": str(t), "stability": stability})
    return out


def _referenced_dataclass_names(type_str: str) -> list[str]:
    """Names from a type-annotation string that resolve to module-level
    dataclasses (e.g. `DeltaRecord | None` → ['DeltaRecord'];
    `list[FileRecord]` → ['FileRecord']). Used to recurse the manifest tree so
    `--schema` documents EVERY nested block, not just the top-level dataclasses
    (v1.13 leg-1 #3 — the COMPLETE claim must hold)."""
    import dataclasses as _dc
    import re as _re
    g = globals()
    out = []
    for token in _re.findall(r"[A-Za-z_][A-Za-z0-9_]*", type_str):
        obj = g.get(token)
        if isinstance(obj, type) and _dc.is_dataclass(obj):
            out.append(token)
    return out


def _collect_manifest_dataclasses() -> dict[str, list[dict[str, str]]]:
    """Transitively walk the dataclass tree rooted at ScanManifest, expanding
    every nested dataclass-typed field. Deterministic (sorted output). This is
    what makes the manifest description COMPLETE — context/meta/stats/
    routing_summary/delta and any future nested block are documented, not left
    as opaque type names (v1.13 leg-1 #3)."""
    import dataclasses as _dc
    seen: dict[str, list[dict[str, str]]] = {}
    queue = [ScanManifest]
    while queue:
        cls = queue.pop()
        name = cls.__name__
        if name in seen:
            continue
        fields = _dataclass_field_map(cls)
        seen[name] = fields
        for f in fields:
            for ref in _referenced_dataclass_names(f["type"]):
                obj = globals().get(ref)
                if isinstance(obj, type) and _dc.is_dataclass(obj) and ref not in seen:
                    queue.append(obj)
    return {k: seen[k] for k in sorted(seen)}


def build_schema_document() -> dict[str, Any]:
    """The complete, code-derived output-surface description. Deterministic:
    same installed build → byte-identical document. Read from the live
    registries so it cannot drift from what the code emits (guard tests in
    test_v1_13 assert completeness against the training corpus)."""
    def _vstab(vid: str) -> str:
        return "provisional" if vid in PROVISIONAL_VECTORS else "stable"
    vectors = [
        {"vector_id": CHATLOG_VECTOR_ID, "scope": "file", "method_version": CHATLOG_METHOD_VERSION, "stability": _vstab(CHATLOG_VECTOR_ID)},
        {"vector_id": REFERENCE_TOKENS_VECTOR_ID, "scope": "file", "method_version": REFERENCE_TOKENS_METHOD_VERSION, "stability": _vstab(REFERENCE_TOKENS_VECTOR_ID)},
        {"vector_id": FILENAME_PATTERNS_VECTOR_ID, "scope": "file", "method_version": FILENAME_PATTERNS_METHOD_VERSION, "stability": _vstab(FILENAME_PATTERNS_VECTOR_ID)},
        {"vector_id": PRESERVATION_VECTOR_ID, "scope": "file", "method_version": PRESERVATION_METHOD_VERSION, "stability": _vstab(PRESERVATION_VECTOR_ID)},
        {"vector_id": AUTHOR_AGGREGATE_VECTOR_ID, "scope": "corpus", "method_version": AUTHOR_AGGREGATE_METHOD_VERSION, "stability": _vstab(AUTHOR_AGGREGATE_VECTOR_ID)},
        {"vector_id": PROVENANCE_VECTOR_ID, "scope": "corpus", "method_version": PROVENANCE_METHOD_VERSION, "stability": _vstab(PROVENANCE_VECTOR_ID)},
    ]
    # MAGIC_SIGNATURES labels (the format vocabulary), sorted + deduped.
    magic_formats = sorted({label for _, label in MAGIC_SIGNATURES})
    # FORMAT_OBSOLESCENCE grouped by tier.
    preservation: dict[str, list[str]] = {}
    for ext, tier in FORMAT_OBSOLESCENCE.items():
        preservation.setdefault(tier, []).append(ext)
    for tier in preservation:
        preservation[tier].sort()

    return {
        "schema_doc_version": 2,   # v1.14: specialists.fields is now list[{name, stability}] (was list[str]); + stability on vectors/manifest fields
        "scanner_version": SCANNER_VERSION,
        "logic_version": LOGIC_VERSION,
        "schema_version": SCHEMA_VERSION,
        # Every dataclass reachable from ScanManifest, expanded (v1.13 leg-1 #3).
        "manifest": _collect_manifest_dataclasses(),
        "specialists": {
            "tools": dict(sorted(SPECIALIST_TOOLS.items())),
            "namespaces": dict(sorted(SPECIALIST_NAMESPACE.items())),
            "fields": {
                ns: [{"name": f, "stability": _field_stability(ns, f)} for f in sorted(SPECIALIST_FIELDS[ns])]
                for ns in sorted(SPECIALIST_FIELDS)
            },
        },
        "vectors": sorted(vectors, key=lambda v: v["vector_id"]),
        "safety_flags": dict(sorted(SAFETY_FLAGS.items())),
        "error_codes": dict(sorted(ERROR_CODES.items())),
        "provenance_triggers": {
            name: PROVENANCE_TRIGGERS[name] for name in sorted(PROVENANCE_TRIGGERS)
        },
        "format_signatures": magic_formats,
        "preservation_tiers": preservation,
        "reference_tokens_subcategories": sorted(REFERENCE_TOKENS_STATIC_TUNING["enabled_subcategories"]),
        "filename_patterns_subcategories": sorted(FILENAME_PATTERNS_STATIC_TUNING["enabled_subcategories"]),
        "mime_tiers": ["libmagic", "magic_signature_fallback", "extension_fallback", "octet_stream"],
    }


def schema_to_json(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True)


def schema_to_markdown(doc: dict[str, Any]) -> str:
    """Human-readable rendering of the schema document (the `--format md` form
    + the committed docs/SCHEMA.md source). Deterministic."""
    L: list[str] = []
    L.append("# File Observer output schema")
    L.append("")
    L.append(f"> Generated by `file-observer --schema --schema-format md` from "
             f"SCANNER {doc['scanner_version']} / LOGIC {doc['logic_version']} / "
             f"SCHEMA {doc['schema_version']}. Code-derived — do not hand-edit; "
             f"regenerate. This describes the COMPLETE output surface the build "
             f"can emit, independent of any particular scan.")
    L.append("")
    # GFM cell escaping: a literal `|` inside a cell (even within backticks) is
    # a column delimiter and breaks the row. Union types like `DeltaRecord | None`
    # must escape it (v1.13 leg-1 #2).
    def _cell(s: str) -> str:
        return s.replace("|", "\\|")

    L.append("## Manifest structure")
    for cls_name, fields in doc["manifest"].items():
        L.append(f"### `{cls_name}`")
        L.append("")
        L.append("| field | type | stability |")
        L.append("|---|---|---|")
        for f in fields:
            L.append(f"| `{_cell(f['name'])}` | `{_cell(f['type'])}` | {f.get('stability', 'stable')} |")
        L.append("")
    L.append("## Specialists")
    L.append("")
    L.append("| extension | namespace | tool |")
    L.append("|---|---|---|")
    for ext, tool in doc["specialists"]["tools"].items():
        ns = doc["specialists"]["namespaces"].get(ext, "")
        L.append(f"| `{ext}` | `{ns}` | `{tool}` |")
    L.append("")
    L.append("### Specialist metadata fields")
    for ns, fields in doc["specialists"]["fields"].items():
        L.append(f"- **{ns}**: " + ", ".join(
            f"`{x['name']}`" + (" _(provisional)_" if x["stability"] == "provisional" else "")
            for x in fields))
    L.append("")
    L.append("## Vectors")
    L.append("")
    L.append("| vector_id | scope | method_version | stability |")
    L.append("|---|---|---|---|")
    for v in doc["vectors"]:
        L.append(f"| `{v['vector_id']}` | {v['scope']} | {v['method_version']} | {v.get('stability', 'stable')} |")
    L.append("")
    L.append("## safety_flags")
    L.append("")
    for k, v in doc["safety_flags"].items():
        L.append(f"- `{k}` — {v}")
    L.append("")
    L.append("## error_codes")
    L.append("")
    for k, v in doc["error_codes"].items():
        L.append(f"- `{k}` — {v}")
    L.append("")
    L.append("## signal_provenance triggers")
    L.append("")
    L.append("| trigger | layer | method | description |")
    L.append("|---|---|---|---|")
    for name, meta in doc["provenance_triggers"].items():
        L.append(f"| `{name}` | {meta['layer']} | `{meta['method']}` | {meta['description']} |")
    L.append("")
    L.append("## format_signatures")
    L.append("")
    L.append(", ".join(f"`{x}`" for x in doc["format_signatures"]))
    L.append("")
    L.append("## preservation tiers")
    L.append("")
    for tier, exts in sorted(doc["preservation_tiers"].items()):
        L.append(f"- **{tier}**: " + (", ".join(f"`{x}`" for x in exts) if exts else "_(default — all other extensions)_"))
    L.append("")
    L.append("## reference_tokens subcategories")
    L.append("")
    L.append(", ".join(f"`{x}`" for x in doc["reference_tokens_subcategories"]))
    L.append("")
    L.append("## filename_patterns subcategories")
    L.append("")
    L.append(", ".join(f"`{x}`" for x in doc["filename_patterns_subcategories"]))
    L.append("")
    L.append("## MIME detection tiers")
    L.append("")
    L.append(" → ".join(f"`{x}`" for x in doc["mime_tiers"]))
    L.append("")
    return "\n".join(L)


def schema_to_summary(doc: dict[str, Any]) -> str:
    """v1.19: a human-readable PROSE rendering of the schema document — the readable
    counterpart to `schema_to_json` / `schema_to_markdown`. Walks the SAME `doc` (single
    source of truth → cannot drift from the structured schema). Deterministic, and
    COMPLETE: it names every enumerated element (a guard test asserts no registry element
    is dropped). This is the 'what this tool CAN observe' summary, sibling to the per-scan
    'what this scan FOUND' summary."""
    sp = doc["specialists"]
    L: list[str] = []
    L.append(f"File Observer {doc['scanner_version']} — what it can observe")
    L.append("")
    L.append(f"(LOGIC {doc['logic_version']} / SCHEMA {doc['schema_version']}. This is the "
             f"COMPLETE observable surface of this build — what it CAN emit, independent of "
             f"any particular scan; the prose counterpart to `--schema --format json|md`.)")
    L.append("")
    L.append("File Observer is an observation layer: it recursively discovers files and "
             "emits a deterministic JSON manifest — identity, filesystem metadata, content "
             "signals — without ingesting, OCRing, embedding, or classifying. Every value "
             "is a bounded observation; a null means 'not observed within bounds', never "
             "'absent from the file'.")
    L.append("")
    L.append("EVERY file gets the universal layer: identity + path-derived fields, "
             "filesystem metadata, a SHA-256 checksum, MIME analysis (content-vs-extension), "
             "routing flags (is_binary / requires_vision / requires_specialist_tool), and "
             "structural file signatures (file_signature / format_signatures / is_polyglot).")
    L.append("")

    # Specialists — group extensions by namespace, name what each extracts.
    L.append("FORMAT SPECIALISTS — for these extensions it extracts more (only when "
             "specialists are enabled; off by default):")
    ns_exts: dict[str, list[str]] = {}
    for ext, ns in sp["namespaces"].items():
        ns_exts.setdefault(ns, []).append(ext)
    for ns in sorted(ns_exts):
        exts = sorted(ns_exts[ns])
        tool = sp["tools"].get(exts[0], "")   # name the semantic tool too (leg-2 completeness)
        via = f" via {tool}" if tool else ""
        fields = ", ".join(f["name"] for f in sp["fields"].get(ns, []))
        L.append(f"  • {ns}{via} ({', '.join(exts)}): {fields or '—'}")
    # any namespace with fields but content-detected (no extension), e.g. chatlog
    for ns in sorted(sp["fields"]):
        if ns not in ns_exts:
            fields = ", ".join(f["name"] for f in sp["fields"][ns])
            L.append(f"  • {ns} (content-detected): {fields}")
    L.append("")

    # Vectors.
    L.append("VECTORS — named observation units computed over the scan:")
    for v in doc["vectors"]:
        L.append(f"  • {v['vector_id']} ({v['scope']}-scoped, {v['stability']})")
    L.append("")

    # Safety flags.
    L.append("SAFETY FLAGS — structural disclosures, NOT threat verdicts:")
    for name, desc in doc["safety_flags"].items():
        L.append(f"  • {name} — {desc}")
    L.append("")

    # The rest of the surface, named for completeness but compactly.
    L.append("MIME detection tiers: " + " → ".join(doc["mime_tiers"]) + ".")
    trig = doc["provenance_triggers"]
    L.append(f"Signal provenance — every derived field records how it was produced, via one "
             f"of {len(trig)} triggers: {', '.join(sorted(trig))}.")
    ecodes = doc["error_codes"]
    L.append(f"Non-fatal errors are structured ({len(ecodes)} codes): {', '.join(sorted(ecodes))}.")
    sigs = doc["format_signatures"]
    L.append(f"Structural format signatures recognized ({len(sigs)}): {', '.join(sigs)}.")
    pres = doc["preservation_tiers"]
    tier_strs = "; ".join(f"{tier} ({', '.join(exts)})" for tier, exts in sorted(pres.items()))
    L.append(f"Format-preservation tiers: {tier_strs}.")
    L.append("reference_tokens subcategories: "
             + ", ".join(doc["reference_tokens_subcategories"]) + ".")
    L.append("filename_patterns subcategories: "
             + ", ".join(doc["filename_patterns_subcategories"]) + ".")
    L.append("")
    L.append("Everything above is observe-only and deterministic: identical inputs + "
             "identical ScanContext → identical output. Specialists are gated (default off); "
             "what is observed never changes how a file is treated downstream.")
    return "\n".join(L)


def manifest_to_jsonl(manifest: ScanManifest) -> str:
    lines: list[str] = []
    # Header line with schema_version, context, meta, stats, routing_summary, delta, manifest_checksum, vectors_collected
    header: dict[str, Any] = {
        "schema_version": manifest.schema_version,
        "context": asdict(manifest.context),
        "meta": asdict(manifest.meta),
        "stats": asdict(manifest.stats),
        "quality": asdict(manifest.quality),
        "routing_summary": asdict(manifest.routing_summary),
        "delta": asdict(manifest.delta) if manifest.delta else None,
        "manifest_checksum": manifest.manifest_checksum,
        "manifest_signature": manifest.manifest_signature,
        "vectors_collected": manifest.vectors_collected,
        "summary": manifest.summary,
    }
    lines.append(json.dumps(header, ensure_ascii=False))
    # One line per file record
    for record in manifest.files:
        lines.append(json.dumps(asdict(record), ensure_ascii=False))
    return "\n".join(lines) + "\n"


def manifest_to_markdown(manifest: ScanManifest) -> str:
    """Generate a human-readable Markdown report from a scan manifest.

    v0.10.2: standalone .md file written alongside the JSON/JSONL manifest.
    """
    lines: list[str] = []
    s = manifest.stats
    q = manifest.quality
    ctx = manifest.context

    # Title
    lines.append(f"# Scan Report")
    lines.append("")
    lines.append(f"**Generated:** {manifest.meta.generated_at}")
    lines.append(f"**Source:** `{manifest.meta.source_dir}`")
    lines.append(f"**Scanner:** v{ctx.scanner_version} (schema {manifest.schema_version}, logic {ctx.logic_version})")
    lines.append(f"**Manifest:** `{manifest.manifest_checksum[:16]}...`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(manifest.summary)
    lines.append("")
    lines.append("---")
    lines.append("")

    # Stats
    lines.append("## File Statistics")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|---|---|")
    lines.append(f"| Total files | {s.total_files:,} |")
    lines.append(f"| Text files | {s.text_files:,} |")
    lines.append(f"| Binary files | {s.binary_files:,} |")
    lines.append(f"| Supported | {s.supported_files:,} |")
    lines.append(f"| Unsupported | {s.unsupported_files:,} |")
    lines.append(f"| Requires vision | {s.requires_vision:,} |")
    lines.append(f"| Requires specialist | {s.requires_specialist_tool:,} |")
    lines.append("")

    # Quality
    lines.append("## Quality")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|---|---|")
    lines.append(f"| Clean | {q.clean_files:,} |")
    lines.append(f"| Degraded | {q.degraded_files:,} |")
    lines.append(f"| Errors | {q.error_files:,} |")
    lines.append(f"| MIME mismatches | {q.mime_mismatches:,} |")
    lines.append(f"| Polyglots | {q.polyglots_detected:,} |")
    lines.append(f"| Safety flags | {q.safety_flags:,} |")
    lines.append(f"| Chatlog files | {q.chatlog_files:,} |")
    lines.append(f"| Duplicate clusters | {q.duplicate_cluster_count:,} ({q.redundant_file_count:,} redundant) |")
    lines.append("")
    if q.specialist_stats:
        lines.append("### Specialist stats")
        lines.append("")
        lines.append("| Tool | Attempted | Succeeded | Failed |")
        lines.append("|---|---|---|---|")
        for tool in sorted(q.specialist_stats):
            s = q.specialist_stats[tool]
            lines.append(f"| {tool} | {s['attempted']:,} | {s['succeeded']:,} | {s['failed']:,} |")
        lines.append("")

    # Vectors
    if manifest.vectors_collected:
        lines.append("## Vectors")
        lines.append("")
        for v in manifest.vectors_collected:
            vid = v["vector_id"]
            mv = v["method_version"]
            applied = v["applied_to_count"]
            digest = v["identity_digest"][:16]
            lines.append(f"### {vid}")
            lines.append("")
            lines.append(f"- **Method version:** {mv}")
            lines.append(f"- **Scope:** {v['scope']}")
            lines.append(f"- **Applied to:** {applied:,} files")
            lines.append(f"- **Identity digest:** `{digest}...`")
            lines.append("")
            summary = v["summary"]
            if summary:
                lines.append("| Field | Value |")
                lines.append("|---|---|")
                for k, val in summary.items():
                    if isinstance(val, list) and len(val) > 5:
                        lines.append(f"| {k} | [{len(val)} items] |")
                    elif isinstance(val, dict):
                        lines.append(f"| {k} | {len(val)} entries |")
                    else:
                        lines.append(f"| {k} | {val} |")
                lines.append("")

    # Per-directory summary
    if q.per_directory_summary:
        lines.append("## Directory Summary")
        lines.append("")
        lines.append("| Directory | Files | Chatlog | Safety | Mismatches | Unsupported |")
        lines.append("|---|---|---|---|---|---|")
        for d in sorted(q.per_directory_summary, key=lambda x: -x["total_files"]):
            name = d["directory"] or "_(root)_"
            lines.append(
                f"| {name} | {d['total_files']:,} | {d['chatlog_files']} | "
                f"{d['safety_flags_files']} | {d['mime_mismatches']} | {d['unsupported_extensions']} |"
            )
        lines.append("")

    # Top files with specialist metadata
    specialist_files = [f for f in manifest.files if f.specialist_metadata]
    if specialist_files:
        lines.append("## Specialist Metadata Highlights")
        lines.append("")
        lines.append(f"{len(specialist_files):,} files with specialist metadata.")
        lines.append("")
        # Group by namespace
        ns_counts: dict[str, int] = {}
        for f in specialist_files:
            for ns in f.specialist_metadata:
                ns_counts[ns] = ns_counts.get(ns, 0) + 1
        lines.append("| Namespace | Files |")
        lines.append("|---|---|")
        for ns, count in sorted(ns_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {ns} | {count:,} |")
        lines.append("")

    # Files with safety flags
    flagged = [f for f in manifest.files if f.safety_flags]
    if flagged:
        lines.append("## Safety Flags")
        lines.append("")
        lines.append("| File | Flags |")
        lines.append("|---|---|")
        for f in flagged[:20]:
            lines.append(f"| `{f.path}` | {', '.join(f.safety_flags)} |")
        if len(flagged) > 20:
            lines.append(f"| _...and {len(flagged) - 20} more_ | |")
        lines.append("")

    # Files with errors
    error_files = [f for f in manifest.files if f.errors]
    if error_files:
        error_count = sum(len(f.errors) for f in error_files)
        lines.append("## Errors")
        lines.append("")
        lines.append(f"{error_count:,} errors across {len(error_files):,} files.")
        lines.append("")

    # Context
    lines.append("## Scan Context")
    lines.append("")
    lines.append(f"| | |")
    lines.append(f"|---|---|")
    lines.append(f"| Scanner | {ctx.scanner_version} |")
    lines.append(f"| Logic | {ctx.logic_version} |")
    lines.append(f"| Python | {ctx.python_version} |")
    lines.append(f"| Platform | {ctx.platform} |")
    for dep, info in ctx.dependencies.items():
        available = "yes" if info.get("available") else "no"
        ver = info.get("version", "")
        lines.append(f"| {dep} | {available} ({ver}) |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"_Report generated by File Observer v{ctx.scanner_version}_")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="File Observer — recursively discover files and emit a deterministic JSON manifest.",
    )
    parser.add_argument("source", nargs="?", default=".", help="Source directory to scan (default: cwd)")
    parser.add_argument("-o", "--output", default=None, help="Output directory for the manifest (default: <scanner_pkg>/manifests/)")
    parser.add_argument("--specialists", action="store_true", help="Enable specialist tier probes")
    parser.add_argument("--exclude-hidden", action="store_true", help="Exclude hidden files and directories")
    parser.add_argument("--preview-max", type=int, default=1000, help="Max characters for content preview (default: 1000)")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json", help="Output format (default: json)")
    parser.add_argument("--ignore-file", default=None, help="Path to ignore file (default: .scannerignore in source dir)")
    parser.add_argument("--previous-manifest", default=None, help="Path to previous manifest for delta comparison")
    parser.add_argument("--workers", type=int, default=1, metavar="N", help="Parallel scan worker processes (default: 1 = serial). Output is byte-identical regardless of N.")
    parser.add_argument("--progress", action="store_true", help="Show a scan progress indicator on stderr (auto-on when stderr is a TTY)")
    parser.add_argument("--watch", action="store_true", help="Continuous mode: rescan on FS events and emit each delta as one JSONL line on stdout. Each emitted scan is byte-identical to a one-shot invocation at the same FS state (v1.11)")
    parser.add_argument("--watch-debounce-ms", type=int, default=200, metavar="N", help="Debounce window for batching FS events in --watch mode (default: 200ms)")
    parser.add_argument("--watch-include-files", action="store_true", help="Include files[] in each --watch emit (default: excluded to keep the stream small; the `delta` field carries what changed)")
    parser.add_argument("--profile", choices=list(SCAN_PROFILES.keys()), default=None, help="Named scan profile (fast_sort, general, deep_extract)")
    parser.add_argument("--specialist-budget", type=int, default=None, help="Max bytes for specialist deviation reads")
    parser.add_argument("--override", action="append", default=[], help="Per-extension override: .ext:field=value (e.g., .csv:baseline_max_bytes=1048576)")
    parser.add_argument("--schema", action="store_true", help="Print the complete output-surface description (every field, specialist, vector, safety_flag, error code, provenance trigger, format signature, preservation tier) and exit. Does NOT scan. Use --schema-format json|md (default json). (v1.13)")
    parser.add_argument("--schema-format", choices=["json", "md", "summary"], default="json", help="Format for --schema output: json (default), md, or summary (human-readable prose — what the tool can observe, v1.19). Only meaningful with --schema.")
    args = parser.parse_args()

    # v1.13: --schema short-circuits the scan path entirely (like --help). It
    # introspects the installed build's output surface; no source dir is read,
    # no manifest is produced. Validate flag compatibility symmetric with --watch
    # (v1.13 leg-1 #1/#5/#6/#7/#11): --schema is a non-scanning surface, so a
    # source dir or any scan-only / streaming flag passed alongside it is a
    # mistake — reject loudly rather than silently discard.
    if args.schema:
        conflicts = []
        if args.source not in (".", None):
            conflicts.append(f"a source directory ({args.source!r})")
        if args.output is not None:
            conflicts.append("--output")
        if args.watch:
            conflicts.append("--watch")
        if args.format != "json":
            # --format is the scan-output format (json/jsonl); schema output is
            # controlled by --schema-format. A non-default --format here is a
            # mistake — reject it rather than silently ignore (v1.13 leg-4 Codex).
            conflicts.append(f"--format {args.format} (use --schema-format for schema output)")
        if conflicts:
            print(f"file-observer: --schema does not scan; remove {', '.join(conflicts)}", file=sys.stderr)
            sys.exit(2)
        doc = build_schema_document()
        if args.schema_format == "md":
            sys.stdout.write(schema_to_markdown(doc) + "\n")
        elif args.schema_format == "summary":
            sys.stdout.write(schema_to_summary(doc) + "\n")
        else:
            sys.stdout.write(schema_to_json(doc) + "\n")
        return

    # Build config from profile + explicit args + overrides
    profile_values = SCAN_PROFILES.get(args.profile, {}) if args.profile else {}

    # Parse --override flags into extension_overrides dict
    ext_overrides: dict[str, dict[str, Any]] = {}
    for ov in args.override:
        # Format: .ext:field=value
        if ":" in ov and "=" in ov:
            ext_part, kv = ov.split(":", 1)
            key, val = kv.split("=", 1)
            ext_overrides.setdefault(ext_part, {})[key] = int(val) if val.isdigit() else val

    config = ScannerConfig(
        enable_specialists=profile_values.get("enable_specialists", args.specialists),
        exclude_hidden=args.exclude_hidden,
        preview_max_chars=args.preview_max,
        baseline_max_bytes=profile_values.get("baseline_max_bytes", 65536),
        specialist_budget=args.specialist_budget if args.specialist_budget is not None else profile_values.get("specialist_budget", 131072),
        format=args.format,
        ignore_file=args.ignore_file,
        previous_manifest=args.previous_manifest,
        extension_overrides=ext_overrides,
        workers=args.workers,
        progress=args.progress,
        watch=args.watch,
        watch_debounce_ms=args.watch_debounce_ms,
        watch_include_files=args.watch_include_files,
    )

    # v1.11: --watch is a stream-to-stdout trigger loop; it does NOT take the
    # one-shot path that writes a manifest file to disk. Conflicting flags
    # (--output, --format jsonl) are rejected.
    if config.watch:
        if args.output is not None:
            print("file-observer: --watch is incompatible with --output (the stream goes to stdout)", file=sys.stderr)
            sys.exit(2)
        if config.format != "json":
            print(f"file-observer: --watch is incompatible with --format {config.format} (stream is JSONL of deltas)", file=sys.stderr)
            sys.exit(2)
        sys.exit(run_watch(source_dir=Path(args.source), config=config))

    scanner = Scanner(source_dir=Path(args.source), config=config)
    manifest = scanner.scan()

    if config.format == "jsonl":
        output = manifest_to_jsonl(manifest)
        ext = "jsonl"
    else:
        output = manifest_to_json(manifest)
        ext = "json"

    manifest_dir = Path(args.output) if args.output else Path(__file__).resolve().parent / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    manifest_path = manifest_dir / f"manifest_v{SCANNER_VERSION}_{timestamp}.{ext}"
    manifest_path.write_text(output, encoding="utf-8")
    print(f"Manifest written to {manifest_path}")

    # v0.10.2: write markdown report alongside the manifest
    md_path = manifest_dir / f"report_v{SCANNER_VERSION}_{timestamp}.md"
    md_path.write_text(manifest_to_markdown(manifest), encoding="utf-8")
    print(f"Report written to {md_path}")


if __name__ == "__main__":
    main()
