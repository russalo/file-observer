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

import chardet
import magic


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".mdx", ".pdf", ".docx", ".rtf", ".csv", ".json", ".yaml", ".yml"
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
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
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
    ".pdf": "pdf_scanner",
    ".docx": "docx_parser",
    ".rtf": "rtf_parser",
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
    specialist_tool: str | None
    sidecar_exists: bool
    frontmatter: FrontmatterRecord
    tags: list[str]
    asset_matches: list[str]
    content_preview: str | None
    filename_date: str | None
    title: str | None
    heading_structure: list[str]
    document_keys: list[str]
    csv_headers: list[str]
    technology_hints: list[str]
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
        self._magic = magic.Magic(mime=True)

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
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield path

    def scan_file(self, path: Path) -> FileRecord:
        rel_path = path.relative_to(self.source_dir)
        stat = path.stat()
        extension = path.suffix.lower()
        errors: list[ErrorRecord] = []

        mime_type = self.detect_mime(path, errors)
        checksum = self.hash_file(path)
        created_at = self.safe_created_at(stat)
        modified_at = self.ts_to_iso(stat.st_mtime)
        stage_folder = rel_path.parts[0] if len(rel_path.parts) > 1 else ""
        directory_depth = max(len(rel_path.parts) - 1, 0)
        sidecar_exists = self.detect_sidecar(path)

        sample = self.read_sample(path)
        is_binary = self.detect_binary(sample, mime_type)
        specialist_tool = SPECIALIST_TOOLS.get(extension)
        requires_specialist_tool = specialist_tool is not None
        requires_vision = self.detect_requires_vision(
            sample, mime_type, extension, is_binary
        )

        encoding: str | None = None
        preview: str | None = None
        tags: list[str] = []
        asset_matches: list[str] = []
        frontmatter = FrontmatterRecord()
        title: str | None = None
        heading_structure: list[str] = []
        document_keys: list[str] = []
        csv_headers: list[str] = []
        technology_hints: list[str] = []

        filename_date = self.extract_filename_date(path.name)

        if not is_binary:
            try:
                encoding, text = self.decode_text(sample, path)
                preview = self.make_preview(text)
                tags = self.extract_tags(text)
                technology_hints = self.detect_technology(text)

                if extension in {".md", ".mdx"}:
                    frontmatter = self.extract_frontmatter(text)
                    asset_matches = self.extract_assets(text)
                    title = self.extract_md_title(text)
                    heading_structure = self.extract_heading_structure(text)
                    if frontmatter.exists:
                        tags = sorted(set(tags + self.tags_from_frontmatter(frontmatter.raw or "")))

                elif extension in {".html", ".htm"}:
                    title = self.extract_html_title(text)

                elif extension == ".csv":
                    csv_headers = self.extract_csv_headers(text)

                elif extension in {".yaml", ".yml"}:
                    document_keys = self.extract_yaml_keys(text)

                elif extension == ".json":
                    document_keys = self.extract_json_keys(text)

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
            specialist_tool=specialist_tool,
            sidecar_exists=sidecar_exists,
            frontmatter=frontmatter,
            tags=tags,
            asset_matches=asset_matches,
            content_preview=preview,
            filename_date=filename_date,
            title=title,
            heading_structure=heading_structure,
            document_keys=document_keys,
            csv_headers=csv_headers,
            technology_hints=technology_hints,
            errors=errors,
        )

    def detect_mime(self, path: Path, errors: list[ErrorRecord]) -> str:
        try:
            detected = self._magic.from_file(str(path))
            if detected:
                return detected
        except Exception:
            pass
        # Fallback to extension-based inference per §1.12
        guessed, _ = mimetypes.guess_type(str(path))
        errors.append(ErrorRecord(
            code="mime_type_fallback",
            message="Content-based MIME detection unavailable, used extension-based inference",
            stage="universal",
        ))
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
        if any(mime_type.startswith(p) for p in BINARY_MIME_PREFIXES):
            return True
        if mime_type in BINARY_MIME_TYPES:
            return True
        if mime_type.startswith("application/") and mime_type not in TEXT_APP_MIMES:
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

    def detect_requires_vision(
        self, sample: bytes, mime_type: str, extension: str, is_binary: bool
    ) -> bool:
        # Image files require vision
        if mime_type.startswith("image/"):
            return True
        # PDFs: check if text content is extractable from the sample
        if extension == ".pdf" and is_binary:
            # If the PDF sample contains text stream markers, it likely has
            # extractable text. Image-only PDFs typically lack these.
            has_text_markers = (
                b"/Text" in sample
                or b"BT\n" in sample
                or b"BT\r" in sample
                or b"/Font" in sample
            )
            return not has_text_markers
        return False

    def decode_text(self, sample: bytes, path: Path) -> tuple[str, str]:
        raw = path.read_bytes()
        # Use chardet for encoding detection per §1.13
        detected = chardet.detect(raw)
        if detected and detected.get("encoding"):
            enc = detected["encoding"].lower()
            confidence = detected.get("confidence", 0) or 0
            if confidence >= 0.5:
                try:
                    return enc, raw.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    pass
        # Fallback cascade
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
        stripped = CODE_STRIP_RE.sub("", text)
        return sorted(
            tag for tag in set(HASHTAG_RE.findall(stripped))
            if not HEX_COLOR_RE.match(tag) and tag.lower() not in TAG_STOP_WORDS
        )

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
                errors.append(ErrorRecord("json_parse_failed", str(exc), "specialist"))
        elif extension in {".pdf", ".docx", ".rtf"}:
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
    import sys

    source_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    scanner = Scanner(source_dir=source_dir)
    manifest = scanner.scan()
    output = manifest_to_json(manifest)

    manifest_dir = Path(__file__).resolve().parent / "manifests"
    manifest_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    manifest_path = manifest_dir / f"manifest_{timestamp}.json"
    manifest_path.write_text(output, encoding="utf-8")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
