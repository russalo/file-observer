"""v1.15 — cross-platform hardening (CI OS matrix + HEIC/HEIF/AVIF detection).

The CI matrix (ubuntu/macOS/Windows) is the live measurement; these are the
state-independent, falsify-first contracts that hold on any OS:

  - the pure-Python MIME sniff (the no-libmagic path Windows runs) disambiguates
    ISO-BMFF `ftyp` files by brand — HEIC/HEIF/AVIF (incl. the iPhone default
    photo format) are images, not `video/mp4` (the pre-v1.15 mislabel);
  - Scanner construction does NOT crash when python-magic imports but libmagic
    (the C lib) is absent — the common Windows case — it degrades to the
    fallback instead.
"""
from __future__ import annotations

import pytest

import file_observer.scanner as fo
from file_observer.scanner import Scanner, SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION


def _ftyp(brand: bytes) -> bytes:
    """A minimal ISO-BMFF header: size + 'ftyp' + major brand (offset 8) + minor."""
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00" + brand


def test_release_version_surfaces():
    # v1.15 floor — the exact current-version pin lives in the newest release test
    # (test_v1_15_1). v1.15.0 introduced LOGIC 1.5.0; later releases only grow it.
    def _v(s): return tuple(int(p) for p in s.split("."))
    assert _v(SCANNER_VERSION) >= (1, 15, 0), f"SCANNER regressed below 1.15.0: {SCANNER_VERSION!r}"
    assert _v(LOGIC_VERSION) >= (1, 5, 0), f"LOGIC regressed below 1.5.0: {LOGIC_VERSION!r}"   # HEIC MIME change
    assert SCHEMA_VERSION == "1.9", f"SCHEMA should be unchanged: {SCHEMA_VERSION!r}"


class TestHeicBrandDetection:
    """The pure-Python sniff (the no-libmagic path) must classify ftyp by brand."""

    @pytest.fixture(scope="class")
    def scanner(self, tmp_path_factory):
        return Scanner(source_dir=tmp_path_factory.mktemp("v15"))

    @pytest.mark.parametrize("brand,expect", [
        (b"heic", "image/heic"),
        (b"heix", "image/heic"),
        # generic HEIF brands relabel to image/heif in v1.15.1 (see test_v1_15_1);
        # here just assert they sniff as SOME image type, not video.
        (b"heif", "image"),
        (b"mif1", "image"),
        (b"msf1", "image"),
        (b"avif", "image/avif"),
        (b"avis", "image/avif"),
    ])
    def test_image_brands_sniff_as_image(self, scanner, brand, expect):
        got = scanner._sniff_mime(_ftyp(brand))
        assert got.startswith(expect) if expect == "image" else got == expect

    @pytest.mark.parametrize("brand", [b"isom", b"mp42", b"mp41", b"M4V ", b"qt  ", b"dash"])
    def test_video_brands_still_sniff_as_video(self, scanner, brand):
        # The regression guard: the generic ftyp→video/mp4 must still win for
        # non-image brands (we added more-specific image rules BEFORE it).
        assert scanner._sniff_mime(_ftyp(brand)) == "video/mp4"

    @pytest.mark.parametrize("brand", [b"heic", b"avif"])
    def test_heic_is_not_a_false_polyglot(self, scanner, brand):
        # scan_signatures collects ALL matching signatures; a HEIC matches both the
        # image-brand rule AND the generic ftyp→video/mp4. The image brand must
        # SUPERSEDE the generic label (like RIFF sub-types) so a real iPhone photo
        # emits ONE signature and is_polyglot stays False (it's a Stable field).
        _sig, formats, is_polyglot = scanner.scan_signatures(_ftyp(brand))
        labels = {f["format"] for f in formats}
        assert "video/mp4" not in labels, f"generic ftyp label not superseded: {labels}"
        assert is_polyglot is False


class TestNoLibmagicCrashGuard:
    """python-magic can import yet fail to construct when libmagic (the C lib) is
    absent — the common Windows case. Scanner.__init__ must degrade, not crash."""

    def test_scanner_survives_magic_construction_failure(self, tmp_path, monkeypatch):
        class _BrokenMagic:
            def __init__(self, *a, **k):
                raise OSError("failed to find libmagic")  # what Windows-no-libmagic raises
        monkeypatch.setattr(fo, "magic", type("m", (), {"Magic": _BrokenMagic}))
        s = Scanner(source_dir=tmp_path)          # must not raise
        assert s._magic is None                   # degraded to the pure-Python fallback

    def test_scan_works_with_magic_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fo, "magic", None)    # python-magic not importable at all
        (tmp_path / "a.txt").write_text("hello world")
        (tmp_path / "p.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        m = Scanner(source_dir=tmp_path).scan()    # full scan on the fallback path
        mimes = {f.filename: f.mime_type for f in m.files}
        assert mimes.get("p.png") == "image/png"   # content-sniffed, no libmagic


class TestPathEdges:
    """RFC §5: a tree with awkward-but-valid path shapes must produce records, never
    abort. Cross-platform by construction — no symlink/chmod/>MAX_PATH (those POSIX-only
    cases live in test_v1_8_1, skipped on Windows); these run on every OS in the matrix."""

    def test_awkward_names_and_deep_paths_do_not_crash(self, tmp_path):
        # Names valid on every OS in the matrix (no trailing-space/dot — Windows
        # strips those; no >MAX_PATH — those POSIX cases live in test_v1_8_1).
        deep = tmp_path
        for part in ["a", "bb", "ccc", "dddd", "eeeee"]:   # nested, safely short
            deep = deep / part
        deep.mkdir(parents=True)
        (deep / "buried.txt").write_text("deep")
        (tmp_path / "name with spaces.txt").write_text("x")
        (tmp_path / "dotted.name.v2.final.txt").write_text("y")
        (tmp_path / "café_résumé_ünïcode.md").write_text("# z")   # unicode (UTF-8 mode)
        m = Scanner(source_dir=tmp_path).scan()            # must NOT raise
        assert len(m.files) == 4
        # every record is well-formed: posix-relative path (the cross-platform
        # normalization — no backslashes even on Windows), non-empty, no None.
        assert all(f.path and "\\" not in f.path for f in m.files)
        assert any(f.path.endswith("eeeee/buried.txt") for f in m.files)


class TestTomlFallbackIsText:
    """Without libmagic, stdlib mimetypes didn't know .toml → octet-stream → the file
    was treated as BINARY (no preview/structural). v1.15 registers .toml as text/plain
    so the extension-fallback tier types it and the text tier runs. Falsify-first."""

    def test_toml_is_text_not_binary_on_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fo, "magic", None)
        (tmp_path / "c.toml").write_text('[server]\nport = 8801\n')
        rec = next(f for f in Scanner(source_dir=tmp_path).scan().files if f.filename == "c.toml")
        assert rec.mime_type == "text/plain"         # registered as text/plain, not binary
        assert rec.is_binary is False                # the bug: octet-stream → binary
        assert rec.content_preview is not None       # text tier ran

    def test_toml_extension_mime_matches_with_libmagic(self, tmp_path):
        # The side-effect guard: registering .toml must NOT turn libmagic's text/plain
        # reading into a false content-vs-extension mismatch (would inflate
        # quality.mime_mismatches). text/plain == text/plain → matches.
        (tmp_path / "c.toml").write_text('[a]\nx = 1\n')
        s = Scanner(source_dir=tmp_path)
        if s._magic is None:
            pytest.skip("needs libmagic to exercise the detected-vs-extension agreement")
        rec = next(f for f in s.scan().files if f.filename == "c.toml")
        assert rec.mime_analysis.extension_mime == "text/plain"
        assert rec.mime_analysis.matches_extension is True
