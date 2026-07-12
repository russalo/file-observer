"""v1.41 — lexicon self-sweep over file-derived metadata (#136 detection half, Phase 2).

Falsify-first. The core falsification: a benign term that lives ONLY in a metadata field
(a filename, a doc author, frontmatter) and NOT in the body must be caught by the new
`lexicon_match.metadata` sub-block while the body scan reports zero — the coverage gap the
body scan structurally can't reach. Plus: dedup (a body-only term stays out of metadata),
binary-file namespace creation, dormant-without-lexicon byte-identical, bounded, determinism.

Values-neutral: the only lexicon terms here are benign fruit/animal placeholder words.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest

from file_observer.scanner import (
    LEXICON_METADATA_MAX_CHARS,
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
    compute_manifest_checksum,
    manifest_to_json,
)

LEX = {"lexicon_id": "test", "categories": {
    "fruit":  ["banana", "cherry", "kiwi"],
    "animal": ["otter", "walrus", "heron"],
}}


def _scan(tree: Path, *, lexicon=LEX, workers: int = 1):
    return Scanner(tree, ScannerConfig(enable_specialists=True, lexicon=lexicon, workers=workers)).scan()


def _lex(record):
    return (record.specialist_metadata or {}).get("lexicon_match")


def _png(path: Path, w: int = 3, h: int = 3):
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = (len(ihdr).to_bytes(4, "big") + b"IHDR" + ihdr + zlib.crc32(b"IHDR" + ihdr).to_bytes(4, "big"))
    iend = (0).to_bytes(4, "big") + b"IEND" + zlib.crc32(b"IEND").to_bytes(4, "big")
    path.write_bytes(sig + chunk + iend)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    # filename carries a fruit term; body carries NOTHING in the lexicon → metadata-only hit
    (tmp_path / "banana_notes.md").write_text("The quick brown fox jumps over the lazy dog.\n", encoding="utf-8")
    # body carries an animal term; filename carries nothing → body-only (dedup: metadata must be 0)
    (tmp_path / "plain.md").write_text("I watched an otter by the river today.\n", encoding="utf-8")
    # doc author (specialist_metadata) carries an animal term; filename/body carry nothing
    (tmp_path / "report.rtf").write_text(r"{\rtf1\ansi{\info{\author walrus}}Body text here.}", encoding="utf-8")
    # BINARY image, filename carries a fruit term → no body scan, namespace must be CREATED
    _png(tmp_path / "cherry_pic.png")
    return tmp_path


# --- 1. the core falsification: metadata-only hit --------------------------------------
def test_metadata_only_hit_caught(tree: Path):
    m = _scan(tree)
    by = {f.filename: f for f in m.files}
    lx = _lex(by["banana_notes.md"])
    assert lx is not None
    assert lx["total_hits"] == 0                                  # body: no lexicon term
    assert lx["metadata"]["total_hits"] >= 1                      # filename "banana" caught
    assert lx["metadata"]["categories"]["fruit"]["count"] >= 1


def test_specialist_metadata_swept(tree: Path):
    """A term in an extracted metadata field (RTF document.author) is caught by the metadata
    sweep. (RTF is a text format, so the `{\\author walrus}` markup is ALSO in the body — the
    body scan catches it too; the point here is the sweep DOES reach specialist_metadata.)"""
    m = _scan(tree)
    rtf = next(f for f in m.files if f.filename == "report.rtf")
    lx = _lex(rtf)
    assert lx["metadata"]["categories"]["animal"]["count"] >= 1   # author "walrus" swept from metadata


# --- 2. dedup: a body-only term does NOT show up in the metadata block ------------------
def test_body_only_not_in_metadata(tree: Path):
    m = _scan(tree)
    plain = next(f for f in m.files if f.filename == "plain.md")
    lx = _lex(plain)
    assert lx["categories"]["animal"]["count"] >= 1              # body: "otter"
    assert lx["metadata"]["total_hits"] == 0                     # content_preview NOT swept


# --- 3. binary file: no body scan, namespace CREATED with a zero body block -------------
def test_binary_file_creates_namespace_with_zero_body(tree: Path):
    m = _scan(tree)
    png = next(f for f in m.files if f.filename == "cherry_pic.png")
    lx = _lex(png)
    assert lx is not None, "namespace must be created on a binary file with a metadata hit"
    assert lx["total_hits"] == 0 and lx["total_tokens"] == 0     # zero body block (no body scan)
    assert lx["metadata"]["categories"]["fruit"]["count"] >= 1   # filename "cherry"


def test_metadata_hit_sets_safety_flag(tree: Path):
    """The lexicon_match flag fires on a metadata-only hit (body OR metadata)."""
    m = _scan(tree)
    png = next(f for f in m.files if f.filename == "cherry_pic.png")
    assert "lexicon_match" in png.safety_flags


# --- 4. dormant without a lexicon: byte-identical --------------------------------------
def test_dormant_without_lexicon_byte_identical(tree: Path):
    with_lex = _scan(tree)
    no_lex = Scanner(tree, ScannerConfig(enable_specialists=True)).scan()
    # no lexicon → no lexicon_match namespace at all
    for f in no_lex.files:
        assert "lexicon_match" not in (f.specialist_metadata or {})
    # and the no-lexicon manifest is unaffected by the v1.41 code (checksum stable)
    again = Scanner(tree, ScannerConfig(enable_specialists=True)).scan()
    assert compute_manifest_checksum(no_lex) == compute_manifest_checksum(again)


# --- 5. bounded: a huge metadata string is capped, doesn't hang ------------------------
def test_metadata_text_bounded(tmp_path: Path):
    huge = "banana " * 40000                                     # ~280 KB > LEXICON_METADATA_MAX_CHARS
    (tmp_path / "big.md").write_text(f"---\nsummary: {huge}\n---\nbody\n", encoding="utf-8")
    m = _scan(tmp_path)                                          # must complete, not hang
    lx = _lex(next(f for f in m.files if f.filename == "big.md"))
    # capped: metadata tokens can't exceed ~cap/1 (one token per ~7 chars) — finite + bounded
    assert lx["metadata"]["total_tokens"] <= LEXICON_METADATA_MAX_CHARS


# --- 5b. FP hygiene: fo-schema dict KEYS must NOT be swept (leg-1 finding) -------------
def test_schema_keys_not_swept(tmp_path: Path):
    """A dict KEY in specialist_metadata is an fo SCHEMA field name (`width`/`make`/`producer`/…),
    fo's own vocabulary — not file content. It must NOT be counted, or a lexicon containing a
    schema word (`make`, `title`, `author`) would false-positive on nearly every file. The image
    metadata keys are `width`/`height`/`bit_depth` with INT values, so a lexicon of those words can
    only hit via the (excluded) keys."""
    _png(tmp_path / "pic.png", 3, 3)
    key_lex = {"lexicon_id": "k", "categories": {"schema": ["width", "height", "bit_depth"]}}
    m = _scan(tmp_path, lexicon=key_lex)
    lx = _lex(next(f for f in m.files if f.filename == "pic.png"))
    assert lx is not None and lx["metadata"]["total_hits"] == 0, "fo-schema keys must not be swept"


# --- 6. determinism: workers 1 vs 2 byte-identical -------------------------------------
def test_determinism_across_workers(tree: Path):
    assert compute_manifest_checksum(_scan(tree, workers=1)) == compute_manifest_checksum(_scan(tree, workers=2))


# --- leg-4 PR-bot findings -------------------------------------------------------------
def test_vector_aggregates_metadata_hits(tree: Path):
    """leg-4/Codex: the corpus `lexicon` vector must count metadata-only matches, not just body —
    else a consumer reading the vector summary misses exactly what v1.41 adds."""
    m = _scan(tree)
    lexvec = next(v for v in m.vectors_collected if v["vector_id"] == "lexicon")
    s = lexvec["summary"]
    # banana_notes.md (filename fruit, metadata-only) + cherry_pic.png (filename fruit) both count
    assert s["files_matched"] >= 2
    assert s["category_hits"].get("fruit", 0) >= 2          # metadata fruit hits aggregated in


def test_binary_zero_body_has_provenance(tree: Path):
    """leg-4/Codex: a binary file's synthesized zero body block needs an audit trail (a text file
    gets it from the body scan; a binary file's body was never scanned)."""
    m = _scan(tree)
    png = next(f for f in m.files if f.filename == "cherry_pic.png")
    prov = png.signal_provenance or {}
    assert "specialist_metadata.lexicon_match" in prov, "synthesized zero body needs provenance"
    assert prov["specialist_metadata.lexicon_match"]["trigger"] == "lexicon_no_body"
    assert "specialist_metadata.lexicon_match.metadata" in prov   # the metadata sweep provenance too


# --- 7. version axes ------------------------------------------------------------------
def test_version_axes():
    assert tuple(int(p) for p in SCANNER_VERSION.split(".")) >= (1, 41, 0)   # floor (v1.42 bumped SCANNER)
    assert LOGIC_VERSION == "1.22.0"    # v1.41 set these; v1.42 froze them (front-door)
    assert SCHEMA_VERSION == "1.23"
