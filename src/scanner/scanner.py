"""
scanner.py — File capability scanner

Observation layer for the PKP document pipeline. Recursively discovers
files, extracts metadata and signals, emits a deterministic JSON manifest.

    Package:    scanner
    Version:    0.11.0
    Schema:     0.11
    Python:     >= 3.12
    Spec:       docs/v0.11.0_RFC_Specification.md (current)
    Repository: pkp.russalo.com/scanner/

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
import struct
import sys
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
    import tomllib
except ImportError:
    tomllib = None  # type: ignore[assignment]

try:
    from defusedxml.ElementTree import fromstring as xml_fromstring
    _defusedxml_available = True
except ImportError:
    from xml.etree.ElementTree import fromstring as xml_fromstring
    _defusedxml_available = False


SCANNER_VERSION = "0.11.0"
LOGIC_VERSION = "0.10.1"
SCHEMA_VERSION = "0.11"


# v0.8: register markdown extensions in stdlib mimetypes so that when libmagic
# is unavailable, the extension-fallback path in detect_mime() returns a real
# text MIME type for .md / .mdx instead of None → application/octet-stream.
# Without this, .mdx files in a no-libmagic environment would be marked
# binary, skip the text decode, and never get chatlog detection.
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/markdown", ".mdx")
mimetypes.add_type("application/jsonl", ".jsonl")


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".mdx", ".pdf", ".docx", ".rtf", ".csv", ".json", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".toml", ".png", ".msg",
    ".jpg", ".jpeg", ".css", ".vx", ".eml", ".xlsx",
    ".doc", ".xls", ".jsonl",
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
    ".msg": "email_envelope",
    ".eml": "email_envelope",
    ".xlsx": "spreadsheet_structure",
    ".xls": "spreadsheet_structure",
}

# Error code constants
ERR_UNIVERSAL_STAT_FAILED = "universal_stat_failed"
ERR_UNSUPPORTED_EXTENSION = "unsupported_extension"
ERR_MIME_TYPE_FALLBACK = "mime_type_fallback"
ERR_BASELINE_DECODE_FAILED = "baseline_decode_failed"
ERR_SPECIALIST_PROBE_FAILED = "specialist_probe_failed"
ERR_JSON_PARSE_FAILED = "json_parse_failed"

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
    ".msg": "email",
    ".eml": "email",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".docx": "document",
    ".doc": "document",
    ".rtf": "document",
}


# Magic byte signatures for polyglot/multi-format detection
# (pattern, offset, format_mime) — offset=None means scan entire sample
MAGIC_SIGNATURES: list[tuple[bytes, int | None, str]] = [
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"%PDF-", None, "application/pdf"),
    (b"PK\x03\x04", 0, "application/zip"),
    (b"\xd0\xcf\x11\xe0", 0, "application/x-ole-storage"),
    (b"{\\rtf", 0, "application/rtf"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"RIFF", 0, "riff_container"),
]

# MIME types a specialist namespace accepts — skip if mime_type doesn't match
SPECIALIST_MIME_GUARD: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "image": {"image/png", "image/jpeg", "image/gif", "image/webp"},
    "email": {"message/rfc822", "application/vnd.ms-outlook", "application/x-ole-storage", "application/CDFV2"},
    "spreadsheet": {"application/zip", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     "application/vnd.ms-excel", "application/x-ole-storage", "application/CDFV2",
                     "application/octet-stream"},
    "document": {"application/zip", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "application/msword", "application/x-ole-storage", "text/rtf", "application/rtf",
                 "application/CDFV2", "application/octet-stream"},
    # v0.8: chatlog is the first content-detected (not extension-driven)
    # specialist. Its MIME guard accepts text/plain and the markdown variants.
    "chatlog": {"text/plain", "text/markdown", "text/x-markdown", "application/json", "application/jsonl", "application/x-ndjson"},
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
CHATLOG_METHOD_VERSION = 3
CHATLOG_RULES_DEFINITION = (
    "detect:speaker_label_re(3+,stop_list),h3_header_re(5+),section_divider_re(3+),"
    "jsonl_role_keys(3+);"
    "extract:turn_count,speaker_labels(freq>=3,stop_list),section_markers,"
    "turn_char_stats,reference_tokens(at_mentions,wiki_links,code_fence_blocks,url_count),"
    "top_capitalized_tokens(freq>=3,top20),vocabulary_size_estimate;"
    "stop_list:Allow,CAUTION,Disallow,Error,Example,Examples,FIXME,"
    "IMPORTANT,NOTE,Note,Result,TIP,TODO,Warning"
)
CHATLOG_STATIC_TUNING = {
    "detection_threshold": 3,
    "h3_detection_threshold": 5,
    "top_capitalized_tokens_n": 20,
    "jsonl_role_keys": ["user", "assistant", "human"],
}
# v0.10.1: JSONL conversation role keys for chatlog detection
CHATLOG_JSONL_ROLE_KEYS = {"user", "assistant", "human"}
# v0.9.1: speaker labels matching these tokens are excluded from detection
# and extraction. These are common documentation patterns (Note:, Example:, etc.)
# that match the speaker label regex but are not conversation participants.
CHATLOG_SPEAKER_STOP_LIST: set[str] = {
    "Note", "NOTE", "Example", "Examples", "Result", "Warning", "Error",
    "Disallow", "Allow", "TODO", "FIXME", "TIP", "IMPORTANT", "CAUTION",
}

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


class Scanner:
    def __init__(self, source_dir: Path, config: ScannerConfig | None = None) -> None:
        self.source_dir = source_dir.resolve()
        self.config = config or ScannerConfig()
        self._magic = magic.Magic(mime=True) if magic else None
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
        records: list[FileRecord] = []
        for path in self.iter_files(self.source_dir):
            rec = self.scan_file(path)
            records.append(rec)
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

        # Run corpus-scoped vectors after the file walk completes
        self._run_corpus_vectors(records)

        context = self._build_context()
        meta = ScanMeta(
            scan_id=str(uuid.uuid4()),
            generated_at=self.now_iso(),
            source_dir=str(self.source_dir),
            config={k: v for k, v in asdict(self.config).items() if k not in ("signing_key", "signing_key_id")},
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
        extras: list[str] = []
        if q.safety_flags:
            extras.append(f"{q.safety_flags} safety flags")
        if q.polyglots_detected:
            extras.append(f"{q.polyglots_detected} polyglots")
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
        if vec_parts:
            lines.append("Vectors: " + ". ".join(vec_parts) + ".")

        # Line 4: top directories
        if q.per_directory_summary:
            top_dirs = sorted(q.per_directory_summary, key=lambda d: -d["total_files"])[:3]
            dir_strs = [f"{d['directory'] or '(root)'} ({d['total_files']:,})" for d in top_dirs]
            lines.append("Largest directories: " + ", ".join(dir_strs) + ".")

        return "\n\n".join(lines)

    def _build_context(self) -> ScanContext:
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
            deps["magic"] = {"available": True, "version": magic_ver}
        else:
            deps["magic"] = {"available": False, "version": None}
        # chardet
        if chardet:
            chardet_ver = getattr(chardet, "__version__", "unknown")
            deps["chardet"] = {"available": True, "version": chardet_ver}
        else:
            deps["chardet"] = {"available": False, "version": None}
        # PyYAML
        if yaml:
            yaml_ver = getattr(yaml, "__version__", "unknown")
            deps["yaml"] = {"available": True, "version": yaml_ver}
        else:
            deps["yaml"] = {"available": False, "version": None}
        # olefile
        if olefile:
            olefile_ver = getattr(olefile, "__version__", "unknown")
            deps["olefile"] = {"available": True, "version": olefile_ver}
        else:
            deps["olefile"] = {"available": False, "version": None}
        # defusedxml
        if _defusedxml_available:
            try:
                import defusedxml
                dxml_ver = getattr(defusedxml, "__version__", "unknown")
            except Exception:
                dxml_ver = "unknown"
            deps["defusedxml"] = {"available": True, "version": dxml_ver}
        else:
            deps["defusedxml"] = {"available": False, "version": None}

        return ScanContext(
            logic_version=LOGIC_VERSION,
            scanner_version=SCANNER_VERSION,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            platform=sys.platform,
            dependencies=deps,
        )

    def _compute_stats(self, records: list[FileRecord]) -> ScanStats:
        supported = sum(
            1 for r in records
            if r.extension in SUPPORTED_EXTENSIONS
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
        specialist_failures = sum(1 for r in records if any(e.code == ERR_SPECIALIST_PROBE_FAILED for e in r.errors))
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
                "specialist_failures": sum(1 for r in group if any(e.code == ERR_SPECIALIST_PROBE_FAILED for e in r.errors)),
                "unsupported_extensions": sum(1 for r in group if any(e.code == ERR_UNSUPPORTED_EXTENSION for e in r.errors)),
            })

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
            if any(e.get("code") == ERR_SPECIALIST_PROBE_FAILED for e in errors):
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
        for path in sorted(root.rglob("*")):
            if path.is_file():
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

        try:
            rel_path = path.relative_to(self.source_dir)
            stat = path.stat()
        except Exception as exc:
            # Universal tier failure — return a minimal record per §1.18
            rel_path = Path(path.name)
            errors.append(ErrorRecord(
                code=ERR_UNIVERSAL_STAT_FAILED,
                message=str(exc),
                stage="universal",
            ))
            # v0.10: filename_patterns still runs on error path (only needs filename)
            fp = self._extract_filename_patterns(path.name)
            self._filename_patterns_applied_count += 1
            if any(fp.values()):
                self._filename_patterns_files_with_any += 1
                for subcat, matched in fp.items():
                    if matched:
                        self._filename_patterns_sums[subcat] = self._filename_patterns_sums.get(subcat, 0) + 1
            return FileRecord(
                path=rel_path.as_posix(),
                filename=path.name,
                extension=path.suffix.lower(),
                mime_type="application/octet-stream",
                size_bytes=0,
                created_at=None,
                modified_at=self.now_iso(),
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
                signal_provenance={},
                errors=errors,
            )

        extension = path.suffix.lower()
        provenance: dict[str, Any] = {}
        eff = self.config.effective_for(extension)

        mime_type, mime_prov = self.detect_mime(path, errors)
        provenance["mime_type"] = asdict(mime_prov)
        mime_analysis = self.analyze_mime(path, mime_type, extension)
        provenance["mime_analysis.matches_extension"] = asdict(ProvenanceEntry(
            layer="derived", method="analyze_mime",
            trigger="mismatch" if not mime_analysis.matches_extension else "match",
            inputs=["mime_type"],
            detail={"detected": mime_analysis.detected_mime, "extension": mime_analysis.extension_mime},
        ))
        checksum = self.hash_file(path)
        created_at = self.safe_created_at(stat)
        modified_at = self.ts_to_iso(stat.st_mtime)
        stage_folder = rel_path.parts[0] if len(rel_path.parts) > 1 else ""
        directory_depth = max(len(rel_path.parts) - 1, 0)
        sidecar_exists = self.detect_sidecar(path)

        sample = self.read_sample(path)
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
            sample, mime_type, extension, is_binary
        )
        provenance["requires_vision"] = asdict(vision_prov)

        if extension not in SUPPORTED_EXTENSIONS:
            errors.append(ErrorRecord(
                code=ERR_UNSUPPORTED_EXTENSION,
                message=f"Extension '{extension}' is not in supported file types",
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
                if extension in {".txt", ".md", ".mdx", ".jsonl"}:
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
                                ))
                            else:
                                chatlog_meta = self._extract_chatlog_metadata(text)
                                if chatlog_meta is None:
                                    errors.append(ErrorRecord(
                                        code=ERR_SPECIALIST_PROBE_FAILED,
                                        message=f"specialist returned null for {CHATLOG_TOOL}",
                                        stage="specialist",
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
                    # Accumulate for corpus summary
                    self._reference_tokens_applied_count += 1
                    has_any = False
                    for subcat, count in ref_tokens.items():
                        self._reference_tokens_sums[subcat] = self._reference_tokens_sums.get(subcat, 0) + count
                        if count > 0:
                            has_any = True
                    if has_any:
                        self._reference_tokens_files_with_any += 1
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
                                code="xml_parse_failed",
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
                                    code="toml_parse_failed",
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
        fp = self._extract_filename_patterns(path.name)
        self._filename_patterns_applied_count += 1
        has_any_fp = False
        for subcat, matched in fp.items():
            if matched:
                self._filename_patterns_sums[subcat] = self._filename_patterns_sums.get(subcat, 0) + 1
                has_any_fp = True
        if has_any_fp:
            self._filename_patterns_files_with_any += 1

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
                    # No signatures detected and MIME is just extension echo — not trustworthy
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
                    ns = SPECIALIST_NAMESPACE.get(extension)
                    if ns:
                        specialist_metadata = {ns: raw_metadata}
                    else:
                        specialist_metadata = raw_metadata
                    tool = SPECIALIST_TOOLS.get(extension, "unknown")
                    is_deviation = extension in {".xlsx", ".docx"}
                    ns_prefix = f"specialist_metadata.{ns}." if ns else "specialist_metadata."
                    for key in raw_metadata:
                        prov_key = f"{ns_prefix}{key}"
                        trigger = "bounded_deviation" if is_deviation else "bounded_sample"
                        if raw_metadata[key] is None:
                            trigger = "missing_from_bounds"
                        prov_detail: dict[str, Any] = {"tool": tool}
                        if is_deviation:
                            prov_detail["read_budget_bytes"] = eff["specialist_budget"]
                            prov_detail["reason"] = "zip_central_directory_required"
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
            safety_flags=safety_flags,
            signal_provenance=provenance,
            errors=errors,
        )

    def detect_mime(self, path: Path, errors: list[ErrorRecord]) -> tuple[str, ProvenanceEntry]:
        if self._magic:
            try:
                detected = self._magic.from_file(str(path))
                if detected:
                    prov = ProvenanceEntry(
                        layer="raw", method="detect_mime",
                        trigger="libmagic",
                    )
                    return detected, prov
            except Exception as exc:
                guessed, _ = mimetypes.guess_type(str(path))
                errors.append(ErrorRecord(
                    code=ERR_MIME_TYPE_FALLBACK,
                    message=f"Content-based MIME detection failed ({exc}), used extension-based inference",
                    stage="universal",
                ))
                prov = ProvenanceEntry(
                    layer="raw", method="detect_mime",
                    trigger="extension_fallback",
                    detail={"reason": "libmagic_exception"},
                )
                return guessed or "application/octet-stream", prov
        # Fallback to extension-based inference per §1.12
        guessed, _ = mimetypes.guess_type(str(path))
        errors.append(ErrorRecord(
            code="mime_type_fallback",
            message="Content-based MIME detection unavailable, used extension-based inference",
            stage="universal",
        ))
        prov = ProvenanceEntry(
            layer="raw", method="detect_mime",
            trigger="extension_fallback",
            detail={"reason": "libmagic_unavailable"},
        )
        return guessed or "application/octet-stream", prov

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
            return self._extract_pdf_metadata(sample)
        if extension == ".png":
            return self._extract_png_metadata(sample)
        if extension in {".jpg", ".jpeg"}:
            return self._extract_jpeg_metadata(sample)
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

    def _extract_pdf_metadata(self, sample: bytes) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        # Detect text stream markers
        has_text_streams = (
            b"/Text" in sample
            or b"BT\n" in sample
            or b"BT\r\n" in sample
            or b"BT\r" in sample
            or b"/Font" in sample
        )
        meta["has_text_streams"] = has_text_streams
        # Extract page count from /Count in the sample (catalog/pages object)
        count_match = re.search(rb"/Count\s+(\d+)", sample)
        meta["page_count"] = int(count_match.group(1)) if count_match else None
        # Extract document info fields from the sample
        for field_name, pdf_key in [
            ("title", b"/Title"),
            ("author", b"/Author"),
            ("producer", b"/Producer"),
            ("creator", b"/Creator"),
        ]:
            meta[field_name] = self._extract_pdf_string(sample, pdf_key)
        # Creation date
        create_match = re.search(rb"/CreationDate\s*\(([^)]*)\)", sample)
        meta["creation_date"] = create_match.group(1).decode("latin-1", errors="replace") if create_match else None
        # v0.3: encrypted
        meta["encrypted"] = b"/Encrypt" in sample
        # v0.3: pdf_version from %PDF-X.Y header
        ver_match = re.match(rb"%PDF-(\d+\.\d+)", sample)
        meta["pdf_version"] = ver_match.group(1).decode("ascii") if ver_match else None
        # v0.3: sample_text_marker_density
        count_bt = len(re.findall(rb"\bBT\b", sample))
        count_et = len(re.findall(rb"\bET\b", sample))
        if len(sample) > 0:
            meta["sample_text_marker_density"] = (count_bt + count_et) / len(sample)
        else:
            meta["sample_text_marker_density"] = None
        return meta

    def _extract_pdf_string(self, sample: bytes, key: bytes) -> str | None:
        pattern = re.escape(key) + rb"\s*\(([^)]*)\)"
        match = re.search(pattern, sample)
        if match:
            return match.group(1).decode("latin-1", errors="replace")
        pattern_hex = re.escape(key) + rb"\s*<([^>]*)>"
        match = re.search(pattern_hex, sample)
        if match:
            try:
                hex_str = match.group(1).decode("ascii")
                return bytes.fromhex(hex_str).decode("utf-16-be", errors="replace")
            except (ValueError, UnicodeDecodeError):
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

    def _extract_jpeg_metadata(self, sample: bytes) -> dict[str, Any] | None:
        # Scan for SOF0 (0xFFC0) or SOF2 (0xFFC2) markers
        i = 0
        while i < len(sample) - 1:
            if sample[i] != 0xFF:
                i += 1
                continue
            marker = sample[i + 1]
            if marker in (0xC0, 0xC2):  # SOF0 or SOF2
                # SOF frame: 2 bytes length, 1 byte precision, 2 bytes height, 2 bytes width
                if i + 9 > len(sample):
                    return {"width": None, "height": None}
                height = struct.unpack(">H", sample[i + 5:i + 7])[0]
                width = struct.unpack(">H", sample[i + 7:i + 9])[0]
                return {"width": width, "height": height}
            if marker == 0xD8 or marker == 0xD9:  # SOI or EOI
                i += 2
                continue
            if marker == 0x00:  # stuffed byte
                i += 2
                continue
            # Other markers: skip length
            if i + 3 < len(sample):
                seg_len = struct.unpack(">H", sample[i + 2:i + 4])[0]
                i += 2 + seg_len
            else:
                break
        return {"width": None, "height": None}

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
            return {"sheet_names": sheet_names, "header_rows": header_rows}
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
                return {"sheet_names": sheet_names, "format": "biff"}
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
            # App properties from docProps/app.xml (word count)
            app_raw = self._safe_zip_read(zf, "docProps/app.xml")
            if app_raw is not None:
                try:
                    root = xml_fromstring(app_raw.decode("utf-8", errors="replace"))
                    ns = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
                    for el in root.iter(f"{{{ns}}}Words"):
                        if el.text and el.text.isdigit():
                            meta["word_count"] = int(el.text)
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
                    "title": None, "author": None,
                }
                # OLE2 SummaryInformation: 2=Title, 4=Author
                if ole.exists("\x05SummaryInformation"):
                    try:
                        props = ole.getproperties("\x05SummaryInformation")
                        meta["title"] = props.get(2)
                        meta["author"] = props.get(4)
                    except Exception:
                        pass
                # Clean string values
                for key in ("title", "author"):
                    if isinstance(meta[key], bytes):
                        meta[key] = meta[key].decode("cp1252", errors="replace").rstrip("\x00")
                    elif isinstance(meta[key], str):
                        meta[key] = meta[key].rstrip("\x00") or None
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

    def _detect_chatlog_pattern(self, text: str) -> bool:
        """Content-based detection of chatlog / journal / vault structure.

        Returns True if the decoded text matches any of the three rules:

          1. Three or more lines matching the speaker label pattern
             (excluding stop-list tokens like Note:, Example:, etc.)
          2. Five or more occurrences of ``### `` headers in the sample.
             (v0.9.1: raised from 3 to reduce false positives on markdown docs)
          3. Three or more lines that are pure section dividers.

        Detection runs even when ``enable_specialists=False`` because it's
        cheap (regex on the already-decoded baseline text).
        """
        if not text:
            return False
        # Rule 1: speaker labels, excluding stop-list matches
        speaker_matches = [
            m.group(1) for m in CHATLOG_SPEAKER_LABEL_RE.finditer(text)
            if m.group(1) not in CHATLOG_SPEAKER_STOP_LIST
        ]
        if len(speaker_matches) >= 3:
            return True
        # Rule 2: H3 headers (v0.9.1: threshold raised to 5)
        if len(CHATLOG_H3_HEADER_RE.findall(text)) >= 5:
            return True
        # Rule 3: section dividers (threshold stays at 3)
        if len(CHATLOG_SECTION_DIVIDER_RE.findall(text)) >= 3:
            return True
        # Rule 4 (v0.10.1): JSONL conversation format — count lines with
        # role-bearing JSON objects ("type": "user"/"assistant"/"human")
        jsonl_role_count = 0
        for line in text.split("\n"):
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("type") in CHATLOG_JSONL_ROLE_KEYS:
                    jsonl_role_count += 1
                    if jsonl_role_count >= 3:
                        return True
            except (json.JSONDecodeError, ValueError):
                continue
        return False

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

        # v0.10.1: detect JSONL format by scanning for role-bearing lines
        # (same check as detection rule 4 to ensure detection and extraction agree)
        jsonl_mode = False
        jsonl_roles: list[str] = []
        jsonl_role_count = 0
        for probe_line in text.split("\n"):
            probe_line = probe_line.strip()
            if not probe_line or not probe_line.startswith("{"):
                continue
            try:
                obj = json.loads(probe_line)
                if isinstance(obj, dict) and obj.get("type") in CHATLOG_JSONL_ROLE_KEYS:
                    jsonl_role_count += 1
                    if jsonl_role_count >= 3:
                        jsonl_mode = True
                        break
            except (json.JSONDecodeError, ValueError):
                continue

        if jsonl_mode:
            # Extract message text from JSONL conversation lines
            message_texts: list[str] = []
            for line in text.split("\n"):
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        continue
                    role = obj.get("type", "")
                    if role in CHATLOG_JSONL_ROLE_KEYS:
                        jsonl_roles.append(role.capitalize())
                        # Extract message content — try common structures
                        msg = obj.get("message", {})
                        if isinstance(msg, dict):
                            content = msg.get("content", "")
                            if isinstance(content, str) and content:
                                message_texts.append(content)
                            elif isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                                        message_texts.append(item["text"])
                        elif isinstance(msg, str) and msg:
                            message_texts.append(msg)
                except (json.JSONDecodeError, ValueError):
                    continue

            # Build turn statistics from JSONL roles
            turn_count = len(jsonl_roles)
            label_counts = Counter(jsonl_roles)
            speaker_labels = sorted(
                label for label, count in label_counts.items()
                if count >= 3
            )
            # Use concatenated message text for text-based extraction
            concat_text = "\n".join(message_texts) if message_texts else ""
            # Turn char stats from message lengths
            avg_turn_chars = 0
            max_turn_chars = 0
            min_turn_chars = 0
            if len(message_texts) >= 2:
                lengths = [len(t) for t in message_texts if len(t) > 0]
                if lengths:
                    avg_turn_chars = int(sum(lengths) / len(lengths))
                    max_turn_chars = max(lengths)
                    min_turn_chars = min(lengths)
            # Section markers: none in JSONL
            section_marker_count = 0
            section_marker_styles: list[str] = []
        else:
            concat_text = text

            # --- Speaker labels and turn statistics (prose mode) ---
            # v0.9.1: filter stop-list tokens from both detection and turn metrics
            raw_label_matches = [
                m for m in CHATLOG_SPEAKER_LABEL_RE.finditer(text)
                if m.group(1) not in CHATLOG_SPEAKER_STOP_LIST
            ]
            turn_count = len(raw_label_matches)
            label_counts = Counter(m.group(1) for m in raw_label_matches)
            speaker_labels = sorted(
                label for label, count in label_counts.items()
                if count >= 3
            )
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

        return {
            "turn_count": turn_count,
            "speaker_labels": speaker_labels,
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
        self, sample: bytes, mime_type: str, extension: str, is_binary: bool
    ) -> tuple[bool, ProvenanceEntry]:
        if mime_type.startswith("image/"):
            return True, ProvenanceEntry(
                layer="derived", method="detect_requires_vision",
                trigger="image_mime", inputs=["mime_type"],
            )
        if extension == ".pdf" and is_binary:
            has_text_markers = (
                b"/Text" in sample
                or b"BT\n" in sample
                or b"BT\r\n" in sample
                or b"BT\r" in sample
                or b"/Font" in sample
            )
            if not has_text_markers:
                return True, ProvenanceEntry(
                    layer="derived", method="detect_requires_vision",
                    trigger="pdf_no_text_markers", inputs=["mime_type", "is_binary"],
                )
            return False, ProvenanceEntry(
                layer="derived", method="detect_requires_vision",
                trigger="pdf_has_text_markers", inputs=["mime_type", "is_binary"],
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
        # Scan for known format signatures
        found: list[dict[str, Any]] = []
        seen_formats: set[str] = set()
        for pattern, offset, fmt in MAGIC_SIGNATURES:
            if offset is not None:
                if sample[offset:offset + len(pattern)] == pattern:
                    found.append({"format": fmt, "offset": offset})
                    seen_formats.add(fmt)
            else:
                idx = sample.find(pattern)
                if idx >= 0:
                    found.append({"format": fmt, "offset": idx})
                    seen_formats.add(fmt)
        found.sort(key=lambda x: x["offset"])
        is_polyglot = len(seen_formats) > 1
        return file_sig, found, is_polyglot

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
        return any(c.exists() for c in candidates)

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
    lines.append(f"_Report generated by Scanner v{ctx.scanner_version}_")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="File capability scanner — recursively discover files and emit a JSON manifest.",
    )
    parser.add_argument("source", nargs="?", default=".", help="Source directory to scan (default: cwd)")
    parser.add_argument("-o", "--output", default=None, help="Output directory for the manifest (default: <scanner_pkg>/manifests/)")
    parser.add_argument("--specialists", action="store_true", help="Enable specialist tier probes")
    parser.add_argument("--exclude-hidden", action="store_true", help="Exclude hidden files and directories")
    parser.add_argument("--preview-max", type=int, default=1000, help="Max characters for content preview (default: 1000)")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json", help="Output format (default: json)")
    parser.add_argument("--ignore-file", default=None, help="Path to ignore file (default: .scannerignore in source dir)")
    parser.add_argument("--previous-manifest", default=None, help="Path to previous manifest for delta comparison")
    parser.add_argument("--profile", choices=list(SCAN_PROFILES.keys()), default=None, help="Named scan profile (fast_sort, general, deep_extract)")
    parser.add_argument("--specialist-budget", type=int, default=None, help="Max bytes for specialist deviation reads")
    parser.add_argument("--override", action="append", default=[], help="Per-extension override: .ext:field=value (e.g., .csv:baseline_max_bytes=1048576)")
    args = parser.parse_args()

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
    )
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
