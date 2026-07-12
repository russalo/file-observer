"""v1.40 — field trust classification + `--trusted-only` safe-mode projection +
`--schema` trust annotation (#136).

Falsify-first. The core falsification: a planted attacker token on every
file-derived surface (filename, content_preview, a tag, a frontmatter value, AND a
chatlog speaker LABEL — which surfaces as a dict KEY, the case that nulling string
VALUES alone would miss) must appear in the NORMAL manifest and be COMPLETELY ABSENT
from `--trusted-only` output. Plus: default byte-identical, marker + path_id,
fo-derived fields kept, checksum self-consistency, completeness guard, `--schema`
trust annotation, CLI + MCP, version axes.

Values-neutral: the only "attacker" strings here are benign canary tokens.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from file_observer.scanner import (
    FIELD_TRUST,
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
    build_schema_document,
    compute_manifest_checksum,
    manifest_to_json,
    manifest_to_jsonl,
    scan_to_json,
)

# --- canaries: benign tokens standing in for attacker-controlled free text -----------
FN_CANARY = "Zinjfname"          # in a filename
PREVIEW_CANARY = "Zinjpreview"   # in a file body → content_preview
TAG_CANARY = "Zinjtag"           # a frontmatter tag
FM_CANARY = "Zinjfmtitle"        # a frontmatter title value → structural
SPEAKER_CANARY = "Zinjspeaker"   # a chatlog speaker LABEL → a dict KEY in speaker_turn_counts
ALL_CANARIES = (FN_CANARY, PREVIEW_CANARY, TAG_CANARY, FM_CANARY, SPEAKER_CANARY)


@pytest.fixture
def planted_tree(tmp_path: Path) -> Path:
    """A tree seeded with the canaries across the file-derived surfaces."""
    md = tmp_path / f"{FN_CANARY}_notes.md"
    md.write_text(
        f"---\ntitle: {FM_CANARY}\ntags: [{TAG_CANARY}]\n---\n\n"
        f"Body text where {PREVIEW_CANARY} appears in the preview window.\n",
        encoding="utf-8",
    )
    convo = tmp_path / "conversation.txt"
    convo.write_text(
        f"{SPEAKER_CANARY}: Hello there, how are you doing today my friend?\n"
        f"Bob: I am doing quite well, thank you very much for asking.\n"
        f"{SPEAKER_CANARY}: That is good to hear, shall we continue our chat?\n"
        f"Bob: Yes of course, I would be happy to keep talking with you.\n",
        encoding="utf-8",
    )
    return tmp_path


def _scan(tree: Path, *, trusted_only: bool):
    cfg = ScannerConfig(enable_specialists=True, trusted_only=trusted_only)
    return Scanner(tree, cfg).scan()


# --- 1. default byte-identical -------------------------------------------------------
def test_default_manifest_byte_identical(planted_tree: Path):
    """trusted_only=False must be byte-identical to the no-arg default path — the
    front-door contract (LOGIC/SCHEMA frozen)."""
    m = _scan(planted_tree, trusted_only=False)
    default = manifest_to_json(m)
    assert manifest_to_json(m, trusted_only=False) == default
    doc = json.loads(default)
    assert "trusted_only" not in doc
    for fr in doc["files"]:
        assert "path_id" not in fr
    # checksum unchanged under the explicit-default arg
    assert compute_manifest_checksum(m) == compute_manifest_checksum(m, trusted_only=False)


# --- 2. the leak falsification (values AND keys) -------------------------------------
def test_canaries_present_in_normal_output(planted_tree: Path):
    """Proves the fixture actually produces each canary — otherwise the leak test is
    vacuous. (If a canary is missing here, fix the fixture, not the assertion.)"""
    m = _scan(planted_tree, trusted_only=False)
    out = manifest_to_json(m)
    for c in ALL_CANARIES:
        assert c in out, f"fixture did not surface {c} in the normal manifest"


def test_no_canary_leaks_into_trusted_only(planted_tree: Path):
    """THE core falsification: no attacker-controlled string reaches --trusted-only
    output — neither as a string VALUE nor as a dict KEY (the speaker-label case)."""
    m = _scan(planted_tree, trusted_only=True)
    out = manifest_to_json(m, trusted_only=True)
    for c in ALL_CANARIES:
        assert c not in out, f"{c} leaked into --trusted-only output"


# --- 3. shape-stable marker + path_id ------------------------------------------------
def test_marker_and_path_id(planted_tree: Path):
    m = _scan(planted_tree, trusted_only=True)
    doc = json.loads(manifest_to_json(m, trusted_only=True))
    assert doc["trusted_only"] is True
    for fr in doc["files"]:
        # file-derived fields nulled but present (shape-stable, D1)
        assert fr["path"] is None
        assert fr["filename"] is None
        assert fr["content_preview"] is None
        # fo-derived correlation handle present, a 64-hex sha256
        assert isinstance(fr["path_id"], str) and len(fr["path_id"]) == 64
        int(fr["path_id"], 16)  # hex


def test_fo_derived_fields_kept(planted_tree: Path):
    m = _scan(planted_tree, trusted_only=True)
    doc = json.loads(manifest_to_json(m, trusted_only=True))
    for fr in doc["files"]:
        assert isinstance(fr["size_bytes"], int)
        assert isinstance(fr["checksum_sha256"], str) and len(fr["checksum_sha256"]) == 64
        assert isinstance(fr["mime_type"], str)
        assert isinstance(fr["is_binary"], bool)
        assert isinstance(fr["is_chatlog"], bool)
        assert isinstance(fr["safety_flags"], list)


def test_specialist_numeric_leaves_kept_strings_nulled(tmp_path: Path):
    """In specialist_metadata, numeric leaves survive; string leaves (and free-text
    keys) do not. Uses a real PNG so image.width/height (ints) are present."""
    import struct
    import zlib

    def _png(path: Path, w: int, h: int):
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        chunk = (len(ihdr).to_bytes(4, "big") + b"IHDR" + ihdr
                 + zlib.crc32(b"IHDR" + ihdr).to_bytes(4, "big"))
        iend = (0).to_bytes(4, "big") + b"IEND" + zlib.crc32(b"IEND").to_bytes(4, "big")
        path.write_bytes(sig + chunk + iend)

    _png(tmp_path / "pic.png", 7, 11)
    m = _scan(tmp_path, trusted_only=True)
    doc = json.loads(manifest_to_json(m, trusted_only=True))
    png = next(f for f in doc["files"] if f["specialist_tool"] == "image_structure")
    meta = png["specialist_metadata"]["image"]
    assert meta["width"] == 7 and meta["height"] == 11   # numeric leaves kept


# --- 4. checksum self-consistency ----------------------------------------------------
def test_trusted_only_checksum_self_consistent_and_distinct(planted_tree: Path):
    m = _scan(planted_tree, trusted_only=True)
    doc = json.loads(manifest_to_json(m, trusted_only=True))
    # the emitted checksum matches a recompute over the projected content
    assert doc["manifest_checksum"] == compute_manifest_checksum(m, trusted_only=True)
    # and it differs from the default (projection changes content)
    assert compute_manifest_checksum(m, trusted_only=True) != compute_manifest_checksum(m)


# --- 5. completeness guard -----------------------------------------------------------
def test_every_file_record_field_is_classified(planted_tree: Path):
    """Every field in a real FileRecord must be in FIELD_TRUST — so the classification
    cannot silently drift as fields are added (mirrors the v1.13 --schema guards)."""
    m = _scan(planted_tree, trusted_only=False)
    doc = json.loads(manifest_to_json(m))
    for fr in doc["files"]:
        for key in fr:
            assert key in FIELD_TRUST, f"FileRecord field {key!r} is not classified in FIELD_TRUST"


# --- 6. --schema trust annotation ----------------------------------------------------
def test_schema_trust_annotation():
    schema = build_schema_document()
    assert schema["schema_doc_version"] >= 3
    # find the FileRecord field descriptors and check the trust attribute
    fr_fields = _find_filerecord_fields(schema)
    by_name = {f["name"]: f for f in fr_fields}
    assert by_name["content_preview"]["trust"] == "file_derived"
    assert by_name["size_bytes"]["trust"] == "fo_derived"
    assert by_name["specialist_metadata"]["trust"] == "mixed"
    # every FileRecord field carries a trust attribute
    for f in fr_fields:
        assert f.get("trust") in {"fo_derived", "file_derived", "mixed"}


def _find_filerecord_fields(schema: dict) -> list[dict]:
    """Locate the FileRecord field list wherever --schema nests it (any list whose
    elements are field descriptors including `content_preview`)."""
    found: list[dict] = []

    def walk(obj):
        if isinstance(obj, list):
            if any(isinstance(x, dict) and x.get("name") == "content_preview" for x in obj):
                found.extend(x for x in obj if isinstance(x, dict) and "name" in x)
            for v in obj:
                walk(v)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)

    walk(schema)
    assert found, "FileRecord fields not found in --schema output"
    return found


# --- 7. CLI end-to-end ---------------------------------------------------------------
def test_cli_trusted_only_stdout(planted_tree: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "file_observer.scanner", str(planted_tree),
         "--specialists", "--trusted-only", "--stdout"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    for c in ALL_CANARIES:
        assert c not in out, f"{c} leaked via the CLI --trusted-only --stdout path"
    doc = json.loads(out)
    assert doc["trusted_only"] is True


# --- 8. MCP surface ------------------------------------------------------------------
def test_mcp_scan_file_trusted_only(planted_tree: Path):
    mcp = pytest.importorskip("file_observer.mcp_server")
    md = planted_tree / f"{FN_CANARY}_notes.md"
    normal = mcp.scan_file(str(md), specialists=True)
    trusted = mcp.scan_file(str(md), specialists=True, trusted_only=True)
    n = json.dumps(normal)
    t = json.dumps(trusted)
    assert PREVIEW_CANARY in n            # normal echoes it
    assert PREVIEW_CANARY not in t        # trusted-only does not
    assert FM_CANARY not in t


def test_mcp_scan_summary_trusted_only_nulls_path_and_summary(planted_tree: Path):
    """scan_summary builds a custom dict (not via the manifest projection); in trusted-only
    it must still null the directory `path` (consistency with meta.source_dir) and the
    `summary` prose, keeping only counts + fo/operator-derived signal."""
    mcp = pytest.importorskip("file_observer.mcp_server")
    out = json.loads(mcp.scan_summary(str(planted_tree), specialists=True, trusted_only=True))
    assert out["trusted_only"] is True
    assert out["path"] is None            # directory-path string nulled
    assert out["summary"] is None         # prose dropped
    assert isinstance(out["stats"], dict) and isinstance(out["notable"], dict)  # counts kept
    for c in ALL_CANARIES:
        assert c not in json.dumps(out), f"{c} leaked via MCP scan_summary --trusted-only"
    # non-vacuous: without trusted_only the directory path IS echoed
    normal = json.loads(mcp.scan_summary(str(planted_tree), specialists=True))
    assert normal["path"] == str(planted_tree)


# --- 10. manifest-LEVEL leak falsification (the v1.40.0 post-commit self-review catch) ---
# The first cut projected files[] ONLY; attacker strings still leaked through the
# manifest-LEVEL blocks (a real file path survived via quality.duplicate_clusters on the
# examples/ tree). These canaries surface ONLY at the manifest level — duplicate clusters,
# per-directory summary, the scan-root path, the author vector summary + the summary prose,
# and the delta path lists — so they are silent to the files[]-only projection.
DUP_CANARY = "Zinjdupfile"        # duplicate-file name → quality.duplicate_clusters[].paths
DIR_CANARY = "Zinjsubdir"         # subdirectory name  → quality.per_directory_summary[].directory
SRC_CANARY = "Zinjsrcroot"        # scan-root dir name  → meta.source_dir
AUTHOR_CANARY = "Zinjrtfauthor"   # RTF author → author_aggregate vector summary + summary prose
DELTA_CANARY = "Zinjdeltafile"    # added-file name → delta.added
ML_CANARIES = (DUP_CANARY, DIR_CANARY, SRC_CANARY, AUTHOR_CANARY)


@pytest.fixture
def manifest_level_tree(tmp_path: Path) -> Path:
    """A canary-named scan root that TRIGGERS the manifest-level blocks: a subdir, two
    identical-content files (a duplicate cluster), and an RTF with a canary author."""
    root = tmp_path / SRC_CANARY
    sub = root / f"{DIR_CANARY}_docs"
    sub.mkdir(parents=True)
    dup = "identical body for duplicate clustering\n"
    (sub / f"{DUP_CANARY}_a.txt").write_text(dup, encoding="utf-8")
    (sub / f"{DUP_CANARY}_b.txt").write_text(dup, encoding="utf-8")   # same checksum → cluster
    (sub / "doc.rtf").write_text(
        r"{\rtf1\ansi\deff0{\info{\author " + AUTHOR_CANARY + r"}{\title Doc}}\f0 Body text.}",
        encoding="utf-8",
    )
    return root


def test_manifest_level_canaries_present_in_normal(manifest_level_tree: Path):
    """Non-vacuous guard: each manifest-level canary really surfaces in the NORMAL manifest
    (otherwise the leak test below is meaningless). Fix the fixture, never this assertion."""
    m = _scan(manifest_level_tree, trusted_only=False)
    out = manifest_to_json(m)
    for c in ML_CANARIES:
        assert c in out, f"fixture did not surface manifest-level canary {c}"


def test_no_manifest_level_canary_leaks_into_trusted_only(manifest_level_tree: Path):
    """THE manifest-level falsification: no attacker string reaches --trusted-only through
    ANY manifest-level block — duplicate_clusters paths, per_directory directory,
    meta.source_dir, the author vector summary, or the summary prose."""
    m = _scan(manifest_level_tree, trusted_only=True)
    out = manifest_to_json(m, trusted_only=True)
    for c in ML_CANARIES:
        assert c not in out, f"{c} leaked into --trusted-only through a manifest-level block"


def test_manifest_level_blocks_shape_stable_in_trusted_only(manifest_level_tree: Path):
    """Scrubbed blocks keep their fo-derived scalars (shape-stable, D1) — only the
    file-derived strings go null/empty; the vector envelope survives, its summary drops."""
    m = _scan(manifest_level_tree, trusted_only=True)
    doc = json.loads(manifest_to_json(m, trusted_only=True))
    assert doc["meta"]["source_dir"] is None
    assert doc["summary"] is None
    clusters = doc["quality"]["duplicate_clusters"]
    assert clusters, "expected a duplicate cluster in the fixture"
    for c in clusters:
        assert c["paths"] == []                                      # path list scrubbed
        assert isinstance(c["count"], int) and c["count"] >= 2       # fo count kept
        assert isinstance(c["checksum_sha256"], str) and len(c["checksum_sha256"]) == 64
    for entry in doc["quality"]["per_directory_summary"]:
        assert entry["directory"] is None                            # dir path scrubbed
        assert isinstance(entry["total_files"], int)                 # counts kept
    assert doc["vectors_collected"], "expected at least one vector (author_aggregate)"
    for v in doc["vectors_collected"]:
        assert v["summary"] == {}                                    # free-text payload dropped
        assert isinstance(v["vector_id"], str)                       # envelope kept
        assert isinstance(v["applied_to_count"], int)


def test_no_delta_path_leaks_into_trusted_only(tmp_path: Path):
    """delta.{added,modified,unchanged,removed,rescan_candidates} are file-path lists — a
    canary-named added file must NOT reach --trusted-only, and the lists project to []."""
    root = tmp_path / "deltaroot"
    root.mkdir()
    (root / "stable.txt").write_text("unchanged across scans\n", encoding="utf-8")
    m1 = Scanner(root, ScannerConfig(enable_specialists=True)).scan()
    prev = tmp_path / "prev.json"
    prev.write_text(manifest_to_json(m1), encoding="utf-8")
    (root / f"{DELTA_CANARY}.txt").write_text("brand new file\n", encoding="utf-8")
    cfg = ScannerConfig(enable_specialists=True, previous_manifest=str(prev), trusted_only=True)
    m2 = Scanner(root, cfg).scan()
    out = manifest_to_json(m2, trusted_only=True)
    doc = json.loads(out)
    assert doc["delta"] is not None                                  # delta actually ran
    for key in ("added", "modified", "unchanged", "removed", "rescan_candidates"):
        assert doc["delta"][key] == [], f"delta.{key} path list not scrubbed"
    assert DELTA_CANARY not in out
    # non-vacuous: the added path IS present without --trusted-only
    m3 = Scanner(root, ScannerConfig(enable_specialists=True, previous_manifest=str(prev))).scan()
    assert DELTA_CANARY in manifest_to_json(m3)


# --- 11. sibling serialization surfaces (leg-4 PR-bot findings) ----------------------
# The manifest-level fix covered manifest_to_json's object path; the PR bots caught the
# SIBLING serialization surfaces that project separately: the JSONL header (built from the
# raw manifest, Codex P1), scan_to_json (didn't thread trusted_only, Codex P1), and the
# projected manifest_checksum (stale when projected at serialize-time, Codex P2).

def test_jsonl_trusted_only_no_manifest_level_leak(manifest_level_tree: Path):
    """--trusted-only --format jsonl: the HEADER line (meta/summary/quality/delta/vectors)
    must be projected too, not just the per-file record lines."""
    m = _scan(manifest_level_tree, trusted_only=True)
    out = manifest_to_jsonl(m, trusted_only=True)
    for c in ML_CANARIES + ALL_CANARIES:
        assert c not in out, f"{c} leaked into --trusted-only JSONL output"
    header = json.loads(out.splitlines()[0])
    assert header["trusted_only"] is True
    assert header["meta"]["source_dir"] is None
    assert header["summary"] is None
    for cl in header["quality"]["duplicate_clusters"]:
        assert cl["paths"] == []
    for v in header["vectors_collected"]:
        assert v["summary"] == {}
    # projected checksum in the header is self-consistent
    assert header["manifest_checksum"] == compute_manifest_checksum(m, trusted_only=True)


def test_scan_to_json_trusted_only_projects(planted_tree: Path):
    """scan_to_json(path, trusted_only=True) must emit the PROJECTED JSON, not scan safe-mode
    then serialize the raw manifest (Codex P1)."""
    out = scan_to_json(planted_tree, specialists=True, trusted_only=True)
    for c in ALL_CANARIES:
        assert c not in out, f"{c} leaked via scan_to_json(trusted_only=True)"
    doc = json.loads(out)
    assert doc["trusted_only"] is True
    for fr in doc["files"]:
        assert fr["path"] is None and isinstance(fr["path_id"], str)
    # and the normal one-shot still echoes them (non-vacuous)
    assert any(c in scan_to_json(planted_tree, specialists=True) for c in ALL_CANARIES)


def test_projected_checksum_consistent_when_projected_at_serialize(manifest_level_tree: Path):
    """Codex P2: a manifest scanned NORMALLY then projected only at serialization (the MCP
    scan_directory path) must still embed the PROJECTED checksum, not the unprojected one."""
    m = _scan(manifest_level_tree, trusted_only=False)   # config.trusted_only is False
    normal_checksum = m.manifest_checksum
    doc = json.loads(manifest_to_json(m, trusted_only=True))
    assert doc["manifest_checksum"] == compute_manifest_checksum(m, trusted_only=True)
    assert doc["manifest_checksum"] != normal_checksum   # projection changed the content
    # JSONL header path is consistent the same way
    jheader = json.loads(manifest_to_jsonl(m, trusted_only=True).splitlines()[0])
    assert jheader["manifest_checksum"] == compute_manifest_checksum(m, trusted_only=True)


def test_mcp_guard_trusted_only_no_path_leak(manifest_level_tree: Path):
    """Codex P2: the MCP max_files guard fires BEFORE the scan and returned the resolved
    directory path in its message — in trusted-only that re-exposes a file-derived path."""
    mcp = pytest.importorskip("file_observer.mcp_server")
    summ = mcp.scan_summary(str(manifest_level_tree), specialists=True, max_files=1, trusted_only=True)
    doc = json.loads(summ)
    assert doc.get("guarded") is True and doc.get("trusted_only") is True
    assert SRC_CANARY not in summ, "scan_summary guard leaked the scan-root path in trusted-only"
    direc = mcp.scan_directory(str(manifest_level_tree), specialists=True, max_files=1, trusted_only=True)
    assert SRC_CANARY not in direc, "scan_directory guard leaked the scan-root path in trusted-only"
    # non-vacuous: without trusted_only the guard DOES name the path
    assert SRC_CANARY in mcp.scan_summary(str(manifest_level_tree), specialists=True, max_files=1)


# --- 9. version axes -----------------------------------------------------------------
def test_version_axes():
    assert SCANNER_VERSION == "1.40.0"
    assert LOGIC_VERSION == "1.21.0"   # projection = front-door, LOGIC frozen
    assert SCHEMA_VERSION == "1.22"    # manifest contract frozen
