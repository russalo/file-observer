"""v1.6.0 — production-provenance dimension (falsify-first).

A corpus-scoped `provenance` vector: normalized toolchains (producer/creator),
production years (creation_date), and digitization (born_digital / scanned /
ocr_detected / unknown). Models on author_aggregate; complements it (that's WHO
authored, this is WHAT-TOOL / WHEN / digitization). Pure observation — no LOGIC
change. Synthetic inline PDFs, CI-safe.
"""
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig, SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
    PROVENANCE_VECTOR_ID, PROVENANCE_METHOD_VERSION,
)


def _sc():
    return Scanner(Path("."), ScannerConfig())


def _scan(tmp_path, files: dict):
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    cfg = ScannerConfig(enable_specialists=True)
    return Scanner(source_dir=tmp_path, config=cfg).scan()


def _prov(manifest):
    for v in manifest.vectors_collected:
        if v["vector_id"] == PROVENANCE_VECTOR_ID:
            return v
    return None


def _pdf(producer: bytes, *, text=True, image=False, count=3, year=None) -> bytes:
    out = b"%PDF-1.7\n2 0 obj<</Type/Pages/Count " + str(count).encode() + b">>endobj\n"
    if text:
        out += b"/Font\nBT (hello) Tj ET\n"
    if image:
        out += b"4 0 obj<</Subtype/Image/Filter/DCTDecode>>stream\n\xff\xd8\xff\nendstream endobj\n"
    out += b"6 0 obj<</Producer(" + producer + b")"
    if year:
        out += b"/CreationDate(D:" + str(year).encode() + b"0101000000)"
    out += b">>endobj\n%%EOF"
    return out


class TestVersions:
    def test_versions(self):
        assert SCANNER_VERSION == "1.6.0"
        assert LOGIC_VERSION == "1.4.0"      # UNCHANGED — provenance is pure aggregation
        assert SCHEMA_VERSION == "1.5"
        assert PROVENANCE_METHOD_VERSION == 1


class TestToolchainNormalization:
    def test_known_toolchains(self):
        n = _sc()._normalize_toolchain
        assert n("Adobe PDF Library 9.0") == ("Adobe PDF Library", False)
        assert n("Acrobat Distiller 8.1.0 (Windows)") == ("Adobe Acrobat Distiller", False)
        assert n("pdfplot10.hdi\\ 10.0.309.0") == ("Autodesk (HDI plot driver)", False)
        assert n("Microsoft® Word 2010") == ("Microsoft Word", False)
        assert n("Microsoft: Print To PDF") == ("Microsoft Print to PDF", False)
        assert n("Bluebeam PDF Library 21") == ("Bluebeam", False)
        assert n("pdfTeX-1.40.21") == ("TeX/LaTeX", False)

    def test_ocr_producers_flagged(self):
        assert _sc()._normalize_toolchain("Adobe Acrobat 10.116 Paper Capture Plug-in")[1] is True
        assert _sc()._normalize_toolchain("ABBYY FineReader 14")[1] is True

    def test_unknown_passthrough_strips_version(self):
        assert _sc()._normalize_toolchain("doPDF Ver 7.2 Build 367 (Windows)") == ("doPDF", False)
        assert _sc()._normalize_toolchain("WeirdConverter") == ("WeirdConverter", False)


class TestProvenanceVector:
    def test_toolchains_years_digitization(self, tmp_path):
        m = _scan(tmp_path, {
            "a.pdf": _pdf(b"Adobe PDF Library 9.0", text=True, year=2018),
            "b.pdf": _pdf(b"Adobe PDF Library 17.0", text=True, year=2022),
            "c.pdf": _pdf(b"Adobe Acrobat 10.116 Paper Capture Plug-in", text=False, image=True, year=2009),
            "d.pdf": _pdf(b"HP Scan", text=False, image=True, year=2015),
        })
        v = _prov(m)
        assert v is not None and v["method_version"] == 1 and v["scope"] == "corpus"
        s = v["summary"]
        tc = {t["name"]: t["count"] for t in s["toolchains"]}
        assert tc.get("Adobe PDF Library") == 2          # 9.0 + 17.0 normalized together
        dg = s["digitization"]
        assert dg["born_digital"] == 2
        assert dg["ocr_detected"] == 1                   # Paper Capture producer wins
        assert dg["scanned"] == 1                        # HP Scan: image-only, no text
        assert s["production_years"].get("2018") == 1
        assert s["production_years"].get("2022") == 1
        assert v["applied_to_count"] == 4

    def test_empty_corpus_registers_zero(self, tmp_path):
        m = _scan(tmp_path, {"plain.txt": b"no producer metadata here at all"})
        v = _prov(m)
        assert v is not None and v["applied_to_count"] == 0
        assert v["summary"]["distinct_toolchains"] == 0

    def test_deterministic_identity(self, tmp_path):
        files = {"a.pdf": _pdf(b"Adobe PDF Library 9.0", year=2018)}
        d1 = _prov(_scan(tmp_path, files))["identity_digest"]
        for f in tmp_path.iterdir():
            f.unlink()
        d2 = _prov(_scan(tmp_path, files))["identity_digest"]
        assert d1 == d2


class TestOOXMLProducingApp:
    def test_docx_application_extracted_and_normalized(self, tmp_path):
        import zipfile
        p = tmp_path / "d.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
            z.writestr("docProps/app.xml",
                       '<?xml version="1.0"?><Properties '
                       'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                       '<Application>Microsoft Office Word</Application><Words>42</Words></Properties>')
        meta = _sc()._extract_docx_metadata(p)
        assert meta is not None and meta.get("application") == "Microsoft Office Word"
        assert _sc()._normalize_toolchain(meta["application"]) == ("Microsoft Word", False)


class TestCorpusSurfacedFixes:
    """Bugs the corpora_infra re-scan surfaced that the ASCII synthetic cases missed."""

    def test_utf16be_literal_producer_decoded(self, tmp_path):
        # A UTF-16BE literal /Producer (FE FF BOM) must decode, not mojibake to
        # "þÿ M i c r o s o f t …" (latin-1) — then it normalizes correctly.
        producer = b"\xfe\xff" + "Microsoft Office Word 2007".encode("utf-16-be")
        m = _scan(tmp_path, {"a.pdf": _pdf(producer, text=True, year=2007)})
        rec = [f for f in m.files if f.path.endswith("a.pdf")][0]
        prod = rec.specialist_metadata["pdf"]["producer"]
        assert prod == "Microsoft Office Word 2007"
        assert _sc()._normalize_toolchain(prod) == ("Microsoft Word", False)

    def test_messy_version_suffix_stripped(self):
        raw = "doPDF Ver 7.2 Build 367 (Windows 7 Home Premium Edition (SP 1) - Version:"
        assert _sc()._normalize_toolchain(raw) == ("doPDF", False)


class TestComplementsAuthorAggregate:
    def test_both_vectors_present(self, tmp_path):
        # provenance (what-tool) and author_aggregate (who) coexist, distinct vectors
        m = _scan(tmp_path, {"a.pdf": _pdf(b"Adobe PDF Library 9.0", year=2020)})
        ids = {v["vector_id"] for v in m.vectors_collected}
        assert PROVENANCE_VECTOR_ID in ids
        assert "author_aggregate" in ids
