"""
scanner.py — File capability scanner

Observation layer for the PKP document pipeline. Recursively discovers
files, extracts metadata and signals, emits a deterministic JSON manifest.

    Package:    scanner
    Version:    0.6.0
    Schema:     0.6
    Python:     >= 3.12
    Spec:       docs/v0.6.0_RFC_Specification.md (current)
    Repository: pkp.russalo.com/scanner/

Design pillars:
    - Capability-locked determinism (ScanContext)
    - Signal layering (raw / derived / semantic-local)
    - Structured provenance (per-field derivation map)
    - Bounded observation (sample_size default 8KB, deviations declared)

Domains are products. Subdomains are responsibilities. Paths are capabilities.
"""

from __future__ import annotations

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


SCANNER_VERSION = "0.6.0"
LOGIC_VERSION = "0.6.0"
SCHEMA_VERSION = "0.6"


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".mdx", ".pdf", ".docx", ".rtf", ".csv", ".json", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".toml", ".png", ".msg",
    ".jpg", ".jpeg", ".css", ".vx", ".eml", ".xlsx",
    ".doc",
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
    added: list[str]
    modified: list[str]
    unchanged: list[str]
    removed: list[str]
    rescan_candidates: list[str] = field(default_factory=list)


@dataclass
class ScanManifest:
    schema_version: str
    context: ScanContext
    meta: ScanMeta
    stats: ScanStats
    routing_summary: RoutingSummary
    delta: DeltaRecord | None
    manifest_checksum: str
    files: list[FileRecord]


# Extension-to-specialist-namespace mapping
SPECIALIST_NAMESPACE: dict[str, str] = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".msg": "email",
    ".eml": "email",
    ".xlsx": "spreadsheet",
    ".docx": "document",
    ".doc": "document",
    ".rtf": "document",
}


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
        records: list[FileRecord] = []
        for path in self.iter_files(self.source_dir):
            records.append(self.scan_file(path))

        context = self._build_context()
        meta = ScanMeta(
            scan_id=str(uuid.uuid4()),
            generated_at=self.now_iso(),
            source_dir=str(self.source_dir),
            config=asdict(self.config),
        )
        stats = self._compute_stats(records)
        routing = self._compute_routing_summary(records)
        delta = self._compute_delta(records)

        # Build manifest without checksum first, then compute it
        manifest = ScanManifest(
            schema_version=SCHEMA_VERSION,
            context=context,
            meta=meta,
            stats=stats,
            routing_summary=routing,
            delta=delta,
            manifest_checksum="",
            files=records,
        )
        manifest.manifest_checksum = compute_manifest_checksum(manifest)
        return manifest

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
        structural = StructuralRecord(
            filename_date=self.extract_filename_date(path.name),
        )

        if not is_binary:
            try:
                encoding, text, enc_prov = self.decode_text(sample, path, eff["baseline_max_bytes"])
                provenance["encoding"] = asdict(enc_prov)
                preview = self.make_preview(text)
                tags = self.extract_tags(text)
                structural.technology_hints = self.detect_technology(text)

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
                    file_was_truncated = stat.st_size > max(self.config.baseline_max_bytes, self.config.sample_size)
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
                    file_was_truncated = stat.st_size > max(self.config.baseline_max_bytes, self.config.sample_size)
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

        specialist_metadata: dict[str, Any] | None = None
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
                raw_metadata = self.extract_specialist_metadata(path, extension, sample, eff["specialist_budget"])
                if raw_metadata is None and extension in SPECIALIST_TOOLS:
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
            return self._extract_msg_metadata(sample)
        if extension == ".eml":
            return self._extract_eml_metadata(sample)
        if extension == ".xlsx":
            return self._extract_xlsx_metadata(path, budget)
        if extension == ".docx":
            return self._extract_docx_metadata(path, budget)
        if extension == ".doc":
            return self._extract_doc_metadata(sample)
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

    def _extract_doc_metadata(self, sample: bytes) -> dict[str, Any] | None:
        if not olefile:
            return None
        try:
            from io import BytesIO
            buf = BytesIO(sample)
            if not olefile.isOleFile(buf):
                return None
            buf.seek(0)
            ole = olefile.OleFileIO(buf)
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

    def _extract_msg_metadata(self, sample: bytes) -> dict[str, Any] | None:
        if not olefile:
            return None
        try:
            from io import BytesIO
            buf = BytesIO(sample)
            if not olefile.isOleFile(buf):
                return None
            buf.seek(0)
            ole = olefile.OleFileIO(buf)
            try:
                subject = self._msg_read_property(ole, "__substg1.0_0037001F") or \
                          self._msg_read_property(ole, "__substg1.0_0037001E")
                from_addr = self._msg_read_property(ole, "__substg1.0_0C1F001F") or \
                            self._msg_read_property(ole, "__substg1.0_0C1F001E") or \
                            self._msg_read_property(ole, "__substg1.0_0042001F") or \
                            self._msg_read_property(ole, "__substg1.0_0042001E")
                to_addr = self._msg_read_property(ole, "__substg1.0_0E04001F") or \
                          self._msg_read_property(ole, "__substg1.0_0E04001E")
                # v0.4: enriched fields for EML parity
                date_val = self._msg_read_property(ole, "__substg1.0_0047001F") or \
                           self._msg_read_property(ole, "__substg1.0_0047001E")
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

    def make_preview(self, text: str) -> str:
        normalized = CONTROL_CHAR_RE.sub("", text).strip()
        return normalized[: self.config.preview_max_chars]

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
    # Exclude volatile fields from deterministic checksum per RFC §Deterministic serialization
    d["meta"]["scan_id"] = ""
    d["meta"]["generated_at"] = ""
    canonical = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def manifest_to_json(manifest: ScanManifest) -> str:
    return json.dumps(manifest, default=_dc_encoder, indent=2, ensure_ascii=False)


def manifest_to_jsonl(manifest: ScanManifest) -> str:
    lines: list[str] = []
    # Header line with schema_version, context, meta, stats, routing_summary, delta, manifest_checksum
    header: dict[str, Any] = {
        "schema_version": manifest.schema_version,
        "context": asdict(manifest.context),
        "meta": asdict(manifest.meta),
        "stats": asdict(manifest.stats),
        "routing_summary": asdict(manifest.routing_summary),
        "delta": asdict(manifest.delta) if manifest.delta else None,
        "manifest_checksum": manifest.manifest_checksum,
    }
    lines.append(json.dumps(header, ensure_ascii=False))
    # One line per file record
    for record in manifest.files:
        lines.append(json.dumps(asdict(record), ensure_ascii=False))
    return "\n".join(lines) + "\n"


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
        specialist_budget=args.specialist_budget or profile_values.get("specialist_budget", 131072),
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


if __name__ == "__main__":
    main()
