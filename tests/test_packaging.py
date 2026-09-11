import io
import json
from pathlib import Path

from PIL import Image
from pydicom.data import get_testdata_file

from dicom_exporter import __version__, updates
from dicom_exporter.converter import collect_inputs
from dicom_exporter.quick import convert_in_place


def opener_returning(payload):
    return lambda request, timeout: io.BytesIO(json.dumps(payload).encode())


def test_newer_release_is_detected():
    release = updates.check_for_update(opener=opener_returning({"tag_name": "v99.0.0", "html_url": "https://example/r"}))
    assert release == updates.Release("99.0.0", "https://example/r")


def test_current_prerelease_and_draft_are_ignored():
    assert updates.check_for_update(opener=opener_returning({"tag_name": f"v{__version__}"})) is None
    assert updates.check_for_update(opener=opener_returning({"tag_name": "v99.0.0", "prerelease": True})) is None
    assert updates.check_for_update(opener=opener_returning({"tag_name": "v99.0.0", "draft": True})) is None


def test_network_errors_are_silent():
    def failing(request, timeout):
        raise OSError("brak sieci")

    assert updates.check_for_update(opener=failing) is None


def test_version_comparison():
    assert updates.is_newer("v1.10.0", "1.9.9")
    assert not updates.is_newer("1.0", "1.0.0")
    assert updates.parse_version("v2") == (2, 0, 0)


def test_quick_convert_saves_png_next_to_sources(tmp_path):
    data = Path(get_testdata_file("CT_small.dcm")).read_bytes()
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "obraz.dcm").write_bytes(data)
    results = list(convert_in_place(collect_inputs([tmp_path])))
    assert all(result.ok for result in results)
    for folder in ("a", "b"):
        with Image.open(tmp_path / folder / "obraz.png") as image:
            assert image.format == "PNG"
