"""v1.36 — defusedxml → purexml XML-dependency changeover. Falsify-first.

fo's XML hardening moves from defusedxml to purexml (pure-stdlib, zero-dep, oracle-gated-to-defusedxml
drop-in, MIT). fo OPTS INTO purexml's structural caps (RECOMMENDED_LIMITS: max_depth=1000 /
max_attributes=256 / max_bytes=100 MiB) — so it now REJECTS a pathologically-deep/oversized XML that
defusedxml dutifully parsed (a catchable LimitExceeded ⊂ ValueError → the field degrades, never crashes).

Contracts:
  - the backend is purexml + the structural limits are applied (opt-in);
  - parse output byte-identical on real files (proven 2695/0 out-of-tree; here: a real docx extracts);
  - a deep XML is REJECTED — end-to-end it DEGRADES, does not crash (never-crash floor);
  - ScanContext records purexml + the applied limits (provenance / Pillar 1);
  - the stdlib fallback never receives `limits=` (it can't take it).

Version axes: SCANNER 1.35.0→1.36.0 · LOGIC 1.19.0→1.20.0 · SCHEMA unchanged (1.21).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
    xml_fromstring, XML_STRUCTURAL_LIMITS, _xml_backend,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


class TestBackendAndLimits:
    def test_backend_is_purexml_with_limits(self):
        # the swap landed: purexml is the hardened backend and the structural caps are in force
        assert _xml_backend == "purexml", f"XML backend is {_xml_backend}, expected purexml"
        assert XML_STRUCTURAL_LIMITS is not None
        assert getattr(XML_STRUCTURAL_LIMITS, "max_depth", None) == 1000

    def test_structural_limits_reject_deep_xml(self):
        # the new defense: a pathologically-deep doc is REFUSED (defusedxml would have parsed it)
        deep = b"<a>" * 2000 + b"x" + b"</a>" * 2000
        with pytest.raises(ValueError):        # LimitExceeded/DepthExceeded ⊂ ValueError → fo's except catches it
            xml_fromstring(deep)

    def test_normal_xml_still_parses(self):
        root = xml_fromstring(b"<r><c>ok</c></r>")
        assert root.tag == "r" and root[0].text == "ok"

    def test_limit_error_is_valueerror(self):
        # load-bearing: the refusal MUST be a ValueError subclass so fo's existing XML except catches it
        deep = b"<a>" * 2000 + b"x" + b"</a>" * 2000
        try:
            xml_fromstring(deep)
            assert False, "deep XML should have been refused"
        except Exception as e:
            assert isinstance(e, ValueError), f"refusal is {type(e).__name__}, not a ValueError"


def _minimal_docx(path: Path, document_xml: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0"?><cp:coreProperties '
                   'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Deep Doc</dc:title></cp:coreProperties>')
        z.writestr("word/document.xml", '<?xml version="1.0"?>' + document_xml)
    return path


class TestEndToEnd:
    def test_deep_xml_in_docx_degrades_not_crash(self, tmp_path):
        # the never-crash floor end-to-end: a docx whose document.xml is pathologically deep must
        # DEGRADE (the specialist catches the refusal), not take the scan down.
        deep = "<a>" * 2000 + "x" + "</a>" * 2000
        _minimal_docx(tmp_path / "deep.docx", deep)
        m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()   # must not raise
        rec = next(r for r in m.files if r.path.endswith("deep.docx"))
        # the doc still appears; the deep part didn't yield word_count/headings, but no fatal crash
        assert rec is not None

    def test_real_docx_extracts_through_purexml(self):
        # a normal docx parses through purexml and yields its metadata (parse transparency)
        docx = next((f for f in FIXTURES.glob("*.docx")), None)
        if docx is None:
            pytest.skip("no docx fixture")
        m = Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True)).scan()
        rec = next(r for r in m.files if r.path.endswith(docx.name))
        doc = (rec.specialist_metadata or {}).get("document")
        assert doc is not None   # document specialist ran through purexml without error

    def test_scancontext_records_purexml_and_limits(self, tmp_path):
        (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
        m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        deps = m.context.dependencies
        assert "purexml" in deps and deps["purexml"]["available"] is True
        assert deps["purexml"]["limits"]["max_depth"] == 1000
        assert "defusedxml" not in deps   # swapped out

    def test_workers_byte_identical(self):
        m1 = Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True, workers=1)).scan()
        m2 = Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.manifest_checksum == m2.manifest_checksum


class TestVersioning:
    def test_version_floor(self):
        def _v(s): return tuple(int(p) for p in s.split("."))
        assert _v(SCANNER_VERSION) >= (1, 36, 0)
        assert _v(LOGIC_VERSION) >= (1, 20, 0)
        assert _v(SCHEMA_VERSION) >= (1, 21)   # SCHEMA unchanged — no field/shape change
