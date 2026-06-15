"""v1.15.2 — MIME-guard hardening (patch).

Two facets of the specialist MIME guard being over-restrictive, both surfaced by the
v1.15.x fixture/cross-platform work:

  A. A generic OLE2 office file is detected by libmagic as `application/vnd.ms-office`,
     which the document/spreadsheet guards did not list (they had CDFV2 / x-ole-storage)
     → extraction was wrongly skipped.
  B. The `.eml` email specialist was skipped on the no-libmagic path: the guard distrusts
     extension-derived `message/rfc822` with no corroborating magic signature — but a text
     format like email HAS no magic signature even when genuine. Trust it for the (curated,
     self-validating) email namespace.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import file_observer.scanner as fo
from file_observer.scanner import (
    Scanner, ScannerConfig, olefile,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)

GEN = Path(__file__).parent / "fixtures" / "generated"


def test_release_version_surfaces():
    assert SCANNER_VERSION == "1.15.2", f"got {SCANNER_VERSION!r}"
    assert LOGIC_VERSION == "1.5.2", f"LOGIC: {LOGIC_VERSION!r}"   # extraction-dispatch change
    assert SCHEMA_VERSION == "1.9", f"SCHEMA unchanged: {SCHEMA_VERSION!r}"


@pytest.mark.skipif(olefile is None, reason="olefile not installed")
class TestVndMsOfficeGuard:
    """A) a generic OLE2 .doc detected as application/vnd.ms-office now extracts."""

    def test_generic_ole2_doc_extracts_on_full_scan(self):
        # generated.doc is a minimal OLE2 with only SummaryInformation → libmagic tags it
        # application/vnd.ms-office. Pre-fix the document guard rejected that MIME.
        m = Scanner(source_dir=GEN, config=ScannerConfig(enable_specialists=True)).scan()
        rec = next(f for f in m.files if f.filename == "generated.doc")
        if rec.mime_type != "application/vnd.ms-office":
            pytest.skip(f"libmagic tagged it {rec.mime_type!r}, not vnd.ms-office — A not exercised here")
        md = (rec.specialist_metadata or {}).get("document", {})
        assert md.get("author") == "File Observer Test"
        assert not any(e.code == "specialist_probe_failed" for e in rec.errors)


class TestEmlNoLibmagic:
    """B) .eml email extraction works on the pure-Python fallback path."""

    EML = (b"From: alice@example.com\r\nTo: bob@example.com\r\n"
           b"Subject: Hello from the fallback path\r\n\r\nBody.\r\n")

    def test_eml_extracts_without_libmagic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fo, "magic", None)            # force the no-libmagic path
        (tmp_path / "msg.eml").write_bytes(self.EML)
        rec = next(f for f in Scanner(source_dir=tmp_path,
                                      config=ScannerConfig(enable_specialists=True)).scan().files
                   if f.filename == "msg.eml")
        assert rec.specialist_tool == "email_envelope"
        md = (rec.specialist_metadata or {}).get("email")
        assert md is not None, "email specialist was guard-skipped on the no-libmagic path"
        assert md.get("subject") == "Hello from the fallback path"
        assert md.get("from") == "alice@example.com"


class TestBlastRadiusContained:
    """The relaxation must stay scoped to `email`. A lying binary-format extension
    (text content named .pdf/.docx) must STILL be guard-skipped on the no-libmagic
    path — those namespaces are NOT extension-trusted (a genuine file would have a
    magic signature). Pins EXTENSION_TRUSTED_MIMES tiny + MIME-gated (not namespace —
    so a lying .msg, binary OLE2 in the same `email` namespace, stays skipped)."""

    # .msg shares the `email` namespace but is BINARY OLE2 — a lying text .msg must
    # STAY skipped (the v1.15.2 gate is by MIME message/rfc822, not by namespace).
    @pytest.mark.parametrize("name", ["lying.pdf", "lying.docx", "lying.msg"])
    def test_lying_binary_extension_still_skipped(self, tmp_path, monkeypatch, name):
        monkeypatch.setattr(fo, "magic", None)            # no-libmagic path
        (tmp_path / name).write_text("just plain text, not really a " + name)
        rec = next(f for f in Scanner(source_dir=tmp_path,
                                      config=ScannerConfig(enable_specialists=True)).scan().files
                   if f.filename == name)
        # extension-derived MIME, no magic signature, namespace NOT trusted → no extraction
        assert rec.specialist_metadata is None
        assert any(e.code == "specialist_probe_failed" for e in rec.errors)

    def test_empty_eml_not_trusted(self, tmp_path, monkeypatch):
        # an empty/unreadable .eml leaves sample=b''; the trust must require a non-empty
        # read so parsing empty bytes can't masquerade as a successful extraction (leg-4).
        monkeypatch.setattr(fo, "magic", None)
        (tmp_path / "empty.eml").write_bytes(b"")
        rec = next(f for f in Scanner(source_dir=tmp_path,
                                      config=ScannerConfig(enable_specialists=True)).scan().files
                   if f.filename == "empty.eml")
        assert (rec.specialist_metadata or {}).get("email") is None
