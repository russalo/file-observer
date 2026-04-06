Scanner Specification Package

Contents
	1.	RFC-style specification
	2.	Field-by-field schema definitions
	3.	Python reference implementation skeleton

⸻

1) RFC-Style Specification

Document Status

Title: Scanner Program Specification for Document Capability Analysis
Version: 1.0-draft
Intended Audience: Engineering, platform, ingestion, and automation teams

1.1 Purpose

This specification defines the required behavior of a scanner program that recursively inspects files in a directory, extracts universal and format-aware signals, and emits a deterministic JSON manifest for downstream systems.

The scanner is an observation and extraction component. It is not an ingestion engine, policy engine, or execution pipeline.

1.2 Normative Language

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are to be interpreted as requirement levels.

1.3 Scope

The scanner MUST:
	•	recursively discover files under a specified source directory
	•	analyze supported file types
	•	populate a complete output record for every discovered file
	•	emit a JSON document conforming to the output contract

The scanner MUST NOT:
	•	reject files due to ingestion or business policy
	•	mutate source files
	•	perform OCR in v1
	•	perform semantic summarization, embedding, classification, or clustering in v1

1.4 Supported File Types

Initial support scope:
	•	.txt
	•	.md
	•	.mdx
	•	.pdf
	•	.docx
	•	.rtf
	•	.csv
	•	.json
	•	.yaml
	•	.yml

Unsupported files MAY still produce universal metadata records, but MUST be clearly marked through routing and error fields.

1.5 Architectural Separation

The scanner is responsible only for:
	•	discovery
	•	metadata extraction
	•	baseline content probing
	•	specialist probing where declared
	•	standardized output production

Downstream ingestion systems are responsible for:
	•	routing decisions beyond scanner-declared signals
	•	approvals
	•	semantic enrichment
	•	persistence strategy

1.6 Capability Tiers

1.6.1 Universal Tier

The Universal tier MUST run for every file and MUST populate:
	•	identity metadata
	•	filesystem metadata
	•	content fingerprint
	•	path-derived fields
	•	routing flags that can be determined without specialist parsing

1.6.2 Baseline Tier

The Baseline tier SHOULD run for files that are text-like or decodeable as text.

Baseline capabilities include:
	•	encoding detection
	•	content preview generation
	•	tag extraction
	•	frontmatter probing where applicable
	•	lightweight structural hints

1.6.3 Specialist Tier

The Specialist tier MAY run for supported structured or complex formats when declared by the capability matrix.

Specialist extraction MUST be bounded and MUST NOT cause a file-level fatal failure.

1.6.4 Structural Signals Layer (v1 Extension)

The Structural Signals Layer provides lightweight document structure signals derived during baseline processing.

This layer:
	•	operates within the baseline capability envelope
	•	requires no specialist tools
	•	MUST be best-effort and non-blocking
	•	MUST NOT introduce scan failure
	•	MUST NOT depend on external libraries beyond baseline processing
	•	MUST default to null or empty values
	•	MUST be deterministic
	•	MUST NOT override specialist extraction results

These signals provide early document understanding without invoking specialist parsing.

The capability tier progression is: Universal → Baseline → Structural → Specialist.

1.7 Determinism and Idempotency

For identical file content and identical runtime configuration, the scanner MUST produce semantically identical output.

Repeated scans MUST NOT change field presence, field meaning, or schema shape.

1.8 Discovery Rules

The scanner MUST:
	•	recursively walk the source directory
	•	emit one output record per discovered file
	•	preserve relative path from source root

The scanner SHOULD support ignoring hidden/system files through configuration, but v1 default behavior SHOULD include all regular files unless explicitly excluded.

1.9 Output Completeness

The scanner MUST populate all fields defined in the output contract for every file record.

A field MAY contain:
	•	a concrete value
	•	null where permitted
	•	an empty array
	•	an empty string

The scanner MUST NOT omit declared fields.

1.10 Null Semantics

null is a meaningful value.

null means one of:
	•	extraction attempted but not applicable
	•	extraction attempted but unavailable
	•	extraction intentionally not performed because the field is undefined for that file type

Empty string and empty array are distinct from null and MUST be used consistently.

1.11 Required Routing Semantics

The scanner MUST populate:
	•	is_binary
	•	requires_vision
	•	requires_specialist_tool

1.11.1 Binary Detection

A file SHOULD be classified as binary when one or more of the following are true:
	•	a NUL byte is detected during sampling
	•	MIME sniffing strongly indicates binary/container data
	•	strict text decoding fails and no valid text fallback is available

1.11.2 Vision Requirement

requires_vision MUST be true when the file appears to require image-based interpretation to recover meaningful visible text or structure.

In v1 this primarily applies to:
	•	image-only PDFs
	•	files whose content is non-textual and not directly extractable via baseline methods

1.11.3 Specialist Requirement

requires_specialist_tool MUST be true when meaningful extraction depends on a format-specific parser or converter.

1.12 MIME Detection

The scanner SHOULD prefer content-based MIME detection.
If content-based MIME detection is unavailable, the scanner MAY fall back to extension-based inference.

When fallback inference is used, the implementation SHOULD record that fact in errors or diagnostic tags.

1.13 Encoding Rules
	•	Text-like files: the scanner MUST attempt encoding detection.
	•	Binary files: encoding MUST be null.
	•	Unknown text encoding: encoding SHOULD be "unknown" if decoding fallback succeeds, otherwise null.

1.14 Content Preview Rules

The scanner MUST attempt content_preview for files where text can be safely extracted.

Preview rules:
	•	MUST be UTF-8 serializable
	•	SHOULD strip or normalize control characters
	•	SHOULD be truncated to a bounded size
	•	SHOULD NOT exceed 1000 characters in v1
	•	MAY be empty when extraction yields no text

1.15 Tag Extraction Rules

tags MUST be deduplicated.

Tag extraction SHOULD include:
	•	inline hashtags such as #example
	•	frontmatter tag lists where supported
	•	lightweight pattern-derived tags when explicitly configured

The scanner MUST NOT invent semantic tags in v1.

1.16 Frontmatter Rules

Frontmatter support in v1 applies to Markdown-like files.

Rules:
	•	only top-of-file YAML frontmatter is recognized
	•	delimiter format MUST be --- opening fence
	•	malformed frontmatter MUST preserve raw content when detected

1.17 Asset Matching Rules

asset_matches SHOULD identify referenced local assets discoverable through lightweight scanning.

In v1 this primarily applies to Markdown-like files and MAY include:
	•	image links
	•	local relative media references
	•	linked attachments

The scanner MUST NOT verify external URLs in v1.

1.18 Error Handling

The scanner MUST emit a record for every discovered file, even if extraction partially fails.

The scanner MUST NOT raise a fatal scan-wide exception because of a single file failure.

Errors SHOULD be captured in a structured errors array.

1.19 Performance Boundaries

The scanner SHOULD:
	•	stream hashes instead of loading large files fully into memory
	•	sample when possible for detection tasks
	•	bound specialist extraction work
	•	avoid full-document expensive parsing unless the capability matrix requires it

1.20 Capability Matrix Compliance

The implementation MUST align with the declared capability matrix for v1 and MUST NOT silently expand capability claims beyond the specification without a version change.

1.21 Extensibility

New file types MAY be added in future versions.
The output schema MUST remain backward compatible where practical.

⸻

2) Field-by-Field Schema Definitions

2.1 Top-Level Output Shape

{
  "generated_at": "",
  "source_dir": "",
  "files": []
}

2.2 Top-Level Fields

generated_at
	•	Type: string
	•	Nullable: no
	•	Meaning: ISO-8601 timestamp of manifest generation
	•	Example: 2026-04-04T21:30:00Z

source_dir
	•	Type: string
	•	Nullable: no
	•	Meaning: root directory scanned

files
	•	Type: array
	•	Nullable: no
	•	Meaning: list of file result records

2.3 File Record Contract

{
  "path": "",
  "filename": "",
  "extension": "",
  "mime_type": "",
  "size_bytes": 0,
  "created_at": "",
  "modified_at": "",
  "checksum_sha256": "",
  "stage_folder": "",
  "directory_depth": 0,
  "encoding": null,
  "is_binary": false,
  "requires_vision": false,
  "requires_specialist_tool": false,
  "specialist_tool": null,
  "sidecar_exists": false,
  "frontmatter": {
    "exists": false,
    "keys": [],
    "raw": null
  },
  "tags": [],
  "asset_matches": [],
  "content_preview": null,
  "structural": {
    "title": null,
    "heading_structure": [],
    "csv_headers": [],
    "document_keys": [],
    "technology_hints": [],
    "filename_date": null
  },
  "errors": []
}

2.4 File Field Definitions

path
	•	Type: string
	•	Nullable: no
	•	Meaning: relative path from source_dir

filename
	•	Type: string
	•	Nullable: no
	•	Meaning: basename including extension

extension
	•	Type: string
	•	Nullable: no
	•	Meaning: lowercase normalized extension including leading dot where present
	•	Example: .md
	•	Files without extension SHOULD use empty string

mime_type
	•	Type: string
	•	Nullable: no
	•	Meaning: detected or inferred MIME type
	•	Unknown MIME SHOULD be application/octet-stream

size_bytes
	•	Type: integer
	•	Nullable: no
	•	Meaning: file size in bytes

created_at
	•	Type: string or null
	•	Nullable: yes
	•	Meaning: filesystem creation/birth timestamp when available
	•	If platform does not expose creation time, MAY be null

modified_at
	•	Type: string
	•	Nullable: no
	•	Meaning: last modification timestamp in ISO-8601 form

checksum_sha256
	•	Type: string
	•	Nullable: no
	•	Meaning: lowercase hex SHA-256 digest

stage_folder
	•	Type: string
	•	Nullable: no
	•	Meaning: first path segment beneath source_dir
	•	If file is at root, SHOULD be empty string

directory_depth
	•	Type: integer
	•	Nullable: no
	•	Meaning: relative path depth beneath source_dir
	•	Root file = 0

encoding
	•	Type: string or null
	•	Nullable: yes
	•	Meaning: detected or inferred text encoding
	•	Binary files MUST use null
	•	Unknown-but-decoded text MAY use unknown

is_binary
	•	Type: boolean
	•	Nullable: no
	•	Meaning: scanner binary/text routing flag

requires_vision
	•	Type: boolean
	•	Nullable: no
	•	Meaning: scanner believes visual/OCR-style interpretation would be needed for meaningful extraction

requires_specialist_tool
	•	Type: boolean
	•	Nullable: no
	•	Meaning: extraction depends on format-specific logic beyond baseline text probing

specialist_tool
	•	Type: string or null
	•	Nullable: yes
	•	Meaning: name of the specialist tool the ingestor should route to
	•	MUST be null when requires_specialist_tool is false
	•	MUST be non-null when requires_specialist_tool is true
	•	Values: "pdf_scanner" (.pdf), "docx_parser" (.docx), "rtf_parser" (.rtf)

sidecar_exists
	•	Type: boolean
	•	Nullable: no
	•	Meaning: presence of an associated sidecar file by configured convention
	•	Default v1 convention MAY be same stem + .json or .md

frontmatter
	•	Type: object
	•	Nullable: no
	•	Meaning: frontmatter extraction result

frontmatter.exists
	•	Type: boolean
	•	Nullable: no
	•	Meaning: frontmatter block detected

frontmatter.keys
	•	Type: array of strings
	•	Nullable: no
	•	Meaning: parsed top-level frontmatter keys



	•	null when not present

tags
	•	Type: array of strings
	•	Nullable: no
	•	Meaning: deduplicated extracted tags

asset_matches
	•	Type: array of strings
	•	Nullable: no
	•	Meaning: discovered asset references

content_preview
	•	Type: string or null
	•	Nullable: yes
	•	Meaning: bounded preview text
	•	null when not available

structural
	•	Type: object
	•	Nullable: no
	•	Meaning: lightweight document structure signals from the Structural Signals Layer

structural.title
	•	Type: string or null
	•	Nullable: yes
	•	Meaning: document title derived from markdown H1, HTML <title>, or first strong heading

structural.heading_structure
	•	Type: array of strings
	•	Nullable: no
	•	Meaning: ordered H2 headings detected in markdown

structural.csv_headers
	•	Type: array of strings
	•	Nullable: no
	•	Meaning: column names extracted from first row of CSV

structural.document_keys
	•	Type: array of strings
	•	Nullable: no
	•	Meaning: top-level keys for JSON/YAML documents

structural.technology_hints
	•	Type: array of strings
	•	Nullable: no
	•	Meaning: frameworks and tools inferred via lightweight pattern detection (e.g., google-fonts, react)

structural.filename_date
	•	Type: string or null
	•	Nullable: yes
	•	Meaning: date inferred from filename patterns, normalized to ISO format (YYYY-MM-DD)

errors
	•	Type: array of objects
	•	Nullable: no
	•	Meaning: structured non-fatal extraction errors

Recommended error object shape:

{
  "code": "",
  "message": "",
  "stage": "universal|baseline|specialist"
}

2.5 Normalization Rules
	•	All booleans MUST be explicit booleans
	•	Timestamps SHOULD be ISO-8601 UTC strings
	•	Arrays MUST be present even when empty
	•	Strings SHOULD be UTF-8 serializable
	•	Extension MUST be lowercase

⸻

3) Python Reference Implementation Skeleton

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
import json
import mimetypes
import os
import re


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".mdx", ".pdf", ".docx", ".rtf", ".csv", ".json", ".yaml", ".yml"
}

HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_\-/]+)")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
ASSET_RE = re.compile(r"!??\[[^\]]*\]\(([^)]+)\)")


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
    sidecar_exists: bool
    frontmatter: FrontmatterRecord
    tags: list[str]
    asset_matches: list[str]
    content_preview: str | None
    errors: list[ErrorRecord] = field(default_factory=list)


@dataclass
class ScanManifest:
    generated_at: str
    source_dir: str
    files: list[FileRecord]


class ScannerConfig:
    preview_max_chars: int = 1000
    sample_size: int = 8192
    enable_specialists: bool = False


class Scanner:
    def __init__(self, source_dir: Path, config: ScannerConfig | None = None) -> None:
        self.source_dir = source_dir.resolve()
        self.config = config or ScannerConfig()

    def scan(self) -> ScanManifest:
        records: list[FileRecord] = []
        for path in self.iter_files(self.source_dir):
            records.append(self.scan_file(path))
        return ScanManifest(
            generated_at=self.now_iso(),
            source_dir=str(self.source_dir),
            files=records,
        )

    def iter_files(self, root: Path) -> Iterable[Path]:
        for path in root.rglob("*"):
            if path.is_file():
                yield path

    def scan_file(self, path: Path) -> FileRecord:
        rel_path = path.relative_to(self.source_dir)
        stat = path.stat()
        extension = path.suffix.lower()
        errors: list[ErrorRecord] = []

        mime_type = self.detect_mime(path)
        checksum = self.hash_file(path)
        created_at = self.safe_created_at(stat)
        modified_at = self.ts_to_iso(stat.st_mtime)
        stage_folder = rel_path.parts[0] if len(rel_path.parts) > 1 else ""
        directory_depth = max(len(rel_path.parts) - 1, 0)
        sidecar_exists = self.detect_sidecar(path)

        sample = self.read_sample(path)
        is_binary = self.detect_binary(sample, mime_type)
        requires_specialist_tool = extension in {".pdf", ".docx", ".rtf"}
        requires_vision = extension == ".pdf" and requires_specialist_tool

        encoding: str | None = None
        preview: str | None = None
        tags: list[str] = []
        asset_matches: list[str] = []
        frontmatter = FrontmatterRecord()

        if not is_binary:
            try:
                encoding, text = self.decode_text(sample, path)
                preview = self.make_preview(text)
                tags = self.extract_tags(text)

                if extension in {".md", ".mdx"}:
                    frontmatter = self.extract_frontmatter(text)
                    asset_matches = self.extract_assets(text)
                    if frontmatter.exists:
                        tags = sorted(set(tags + self.tags_from_frontmatter(frontmatter.raw or "")))
            except Exception as exc:
                errors.append(ErrorRecord(
                    code="baseline_decode_failed",
                    message=str(exc),
                    stage="baseline",
                ))
        else:
            encoding = None

        if self.config.enable_specialists:
            try:
                self.run_specialist_probe(path, extension, errors)
            except Exception as exc:
                errors.append(ErrorRecord(
                    code="specialist_probe_failed",
                    message=str(exc),
                    stage="specialist",
                ))

        return FileRecord(
            path=str(rel_path).replace("\\", "/"),
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
            sidecar_exists=sidecar_exists,
            frontmatter=frontmatter,
            tags=tags,
            asset_matches=asset_matches,
            content_preview=preview,
            errors=errors,
        )

    def detect_mime(self, path: Path) -> str:
        guessed, _ = mimetypes.guess_type(str(path))
        return guessed or "application/octet-stream"

    def hash_file(self, path: Path) -> str:
        digest = sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def read_sample(self, path: Path) -> bytes:
        with path.open("rb") as f:
            return f.read(self.config.sample_size)

    def detect_binary(self, sample: bytes, mime_type: str) -> bool:
        if b"\x00" in sample:
            return True
        if mime_type.startswith("application/") and mime_type not in {
            "application/json",
            "application/rtf",
            "application/xml",
            "application/yaml",
        }:
            # conservative; refined routing can narrow this later
            if not self.looks_like_text(sample):
                return True
        return not self.looks_like_text(sample)

    def looks_like_text(self, sample: bytes) -> bool:
        if not sample:
            return True
        text_chars = sum(
            1 for b in sample
            if b in b"\t\n\r\f\b" or 32 <= b <= 126 or b >= 128
        )
        return (text_chars / max(len(sample), 1)) >= 0.85

    def decode_text(self, sample: bytes, path: Path) -> tuple[str, str]:
        raw = path.read_bytes()
        for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                return enc, raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return "unknown", raw.decode("utf-8", errors="replace")

    def make_preview(self, text: str) -> str:
        normalized = text.replace("\x00", "").strip()
        return normalized[: self.config.preview_max_chars]

    def extract_tags(self, text: str) -> list[str]:
        return sorted(set(HASHTAG_RE.findall(text)))

    def extract_frontmatter(self, text: str) -> FrontmatterRecord:
        match = FRONTMATTER_RE.search(text)
        if not match:
            return FrontmatterRecord()
        raw = match.group(1)
        keys = []
        for line in raw.splitlines():
            if ":" in line:
                key = line.split(":", 1)[0].strip()
                if key:
                    keys.append(key)
        return FrontmatterRecord(exists=True, keys=sorted(set(keys)), raw=raw)

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
                errors.append(ErrorRecord("json_parse_failed", str(exc), "specialist"))
        elif extension in {".pdf", ".docx", ".rtf"}:
            # placeholder for specialist integrations
            return

    def safe_created_at(self, stat: os.stat_result) -> str | None:
        birth = getattr(stat, "st_birthtime", None)
        if birth is None:
            return None
        return self.ts_to_iso(birth)

    def ts_to_iso(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


def manifest_to_json(manifest: ScanManifest) -> str:
    def encode(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        raise TypeError(f"Unsupported type: {type(obj)!r}")

    return json.dumps(manifest, default=encode, indent=2, ensure_ascii=False)


def main() -> None:
    source_dir = Path(".")
    scanner = Scanner(source_dir=source_dir)
    manifest = scanner.scan()
    print(manifest_to_json(manifest))


if __name__ == "__main__":
    main()


⸻

Recommended Next Engineering Step
	1.	Freeze the JSON contract.
	2.	Add test fixtures for each supported file type.
	3.	Implement specialist adapters behind interfaces.
	4.	Add golden-file tests to verify deterministic output.
	5.	Version the schema before production use.