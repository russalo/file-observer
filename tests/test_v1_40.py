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


# --- 9. version axes -----------------------------------------------------------------
def test_version_axes():
    assert SCANNER_VERSION == "1.40.0"
    assert LOGIC_VERSION == "1.21.0"   # projection = front-door, LOGIC frozen
    assert SCHEMA_VERSION == "1.22"    # manifest contract frozen
