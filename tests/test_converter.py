from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from dicom_exporter.converter import (
    LAYOUT_FLAT,
    WINDOW_MINMAX,
    ConvertOptions,
    DicomConversionError,
    InputFile,
    collect_inputs,
    convert_batch,
    convert_file,
    render_preview,
)
from dicom_exporter.i18n import plural

# Pasy kolorów w obrazach testowych SC_rgb_* z pydicom (wiersz, oczekiwany kolor RGB)
SC_RGB_BANDS = [
    (5, (255, 0, 0)),
    (25, (0, 255, 0)),
    (45, (0, 0, 255)),
    (65, (0, 0, 0)),
    (75, (64, 64, 64)),
    (95, (255, 255, 255)),
]


def make_grayscale(path: Path, pixels: np.ndarray, *, with_meta: bool = True, **attributes) -> Path:
    ds = Dataset()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = generate_uid()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.set_pixel_data(pixels.astype(np.uint16), "MONOCHROME2", 16)
    for keyword, value in attributes.items():
        setattr(ds, keyword, value)
    if with_meta:
        ds.save_as(path, enforce_file_format=True)
    else:
        del ds.file_meta
        ds.save_as(path, implicit_vr=True, little_endian=True)
    return path


def convert(path, out_dir, **options) -> list[Path]:
    return convert_file(InputFile(Path(path)), out_dir, ConvertOptions(**options))


def assert_bands(image: Image.Image, tolerance: int) -> None:
    arr = np.asarray(image.convert("RGB")).astype(int)
    for row, expected in SC_RGB_BANDS:
        assert np.abs(arr[row, 50] - expected).max() <= tolerance, (row, arr[row, 50], expected)


def test_ct_to_png(tmp_path):
    [output] = convert(get_testdata_file("CT_small.dcm"), tmp_path)
    assert output.name == "CT_small.png"
    with Image.open(output) as image:
        assert image.mode == "L"
        assert image.size == (128, 128)
        assert np.asarray(image).std() > 10  # obraz nie jest jednolity


@pytest.mark.parametrize("fmt, suffix", [("JPG", ".jpg"), ("JPEG", ".jpeg")])
def test_jpeg_output(tmp_path, fmt, suffix):
    [output] = convert(get_testdata_file("MR_small.dcm"), tmp_path, fmt=fmt, quality=80)
    assert output.suffix == suffix
    with Image.open(output) as image:
        assert image.format == "JPEG"


@pytest.mark.parametrize(
    "name, tolerance",
    [
        ("SC_rgb_rle.dcm", 0),
        ("SC_rgb_rle_16bit.dcm", 0),
        ("SC_rgb_jpeg_dcmtk.dcm", 8),  # JPEG w przestrzeni YBR
        ("SC_ybr_full_422_uncompressed.dcm", 8),
    ],
)
def test_color_images(tmp_path, name, tolerance):
    path = get_testdata_file(name)
    if path is None:
        pytest.skip(f"brak pliku testowego {name}")
    [output] = convert(path, tmp_path)
    with Image.open(output) as image:
        assert image.mode == "RGB"
        assert_bands(image, tolerance)


def test_palette_color(tmp_path):
    [output] = convert(get_testdata_file("examples_palette.dcm"), tmp_path)
    with Image.open(output) as image:
        assert image.mode == "RGB"
        assert np.asarray(image).max() > 100


def test_jpeg2000_and_jpeg_ls(tmp_path):
    for name in ("MR_small_jp2klossless.dcm", "MR_small_jpeg_ls_lossless.dcm", "JPEG2000.dcm"):
        assert len(convert(get_testdata_file(name), tmp_path)) == 1


def test_multiframe_all_and_first(tmp_path):
    source = get_testdata_file("SC_rgb_rle_2frame.dcm")
    outputs = convert(source, tmp_path / "all")
    assert [p.name for p in outputs] == ["SC_rgb_rle_2frame_frame001.png", "SC_rgb_rle_2frame_frame002.png"]
    assert len(convert(source, tmp_path / "first", all_frames=False)) == 1


def test_window_from_file(tmp_path):
    pixels = np.tile(np.arange(0, 1000, 10, dtype=np.uint16), (10, 1))  # 0..990
    source = make_grayscale(tmp_path / "win.dcm", pixels, WindowCenter=500, WindowWidth=200)
    [output] = convert(source, tmp_path)
    arr = np.asarray(Image.open(output))
    assert arr[0, 0] == 0 and arr[0, 30] == 0  # 300 < okno
    assert arr[0, 70] == 255 and arr[0, 99] == 255  # 700 > okno
    assert 100 < arr[0, 50] < 150  # środek okna

    [full] = convert(source, tmp_path / "minmax", windowing=WINDOW_MINMAX)
    arr = np.asarray(Image.open(full))
    assert arr[0, 0] == 0 and arr[0, 99] == 255 and 0 < arr[0, 30] < 255


def test_rescale_and_window_are_combined(tmp_path):
    pixels = np.full((4, 4), 1024, dtype=np.uint16)
    pixels[0, 0] = 0
    # 1024 * 1 - 1024 = 0 HU; okno 0/100 -> środek szarości
    source = make_grayscale(
        tmp_path / "ct.dcm", pixels, RescaleSlope=1, RescaleIntercept=-1024, WindowCenter=0, WindowWidth=100
    )
    [output] = convert(source, tmp_path)
    arr = np.asarray(Image.open(output))
    assert 120 <= arr[1, 1] <= 135
    assert arr[0, 0] == 0


def test_monochrome1_is_inverted(tmp_path):
    pixels = np.array([[0, 100], [200, 300]], dtype=np.uint16)
    source = make_grayscale(tmp_path / "m1.dcm", pixels, PhotometricInterpretation="MONOCHROME1")
    [output] = convert(source, tmp_path)
    arr = np.asarray(Image.open(output))
    assert arr[0, 0] == 255 and arr[1, 1] == 0


def test_file_without_meta_header(tmp_path):
    source = make_grayscale(tmp_path / "old.dcm", np.arange(16).reshape(4, 4), with_meta=False)
    assert len(convert(source, tmp_path / "out")) == 1


def test_errors_are_readable(tmp_path):
    with pytest.raises(DicomConversionError, match="brak danych pikseli"):
        convert(get_testdata_file("rtplan.dcm"), tmp_path)
    text_file = tmp_path / "notatka.txt"
    text_file.write_text("to nie jest DICOM", encoding="utf-8")
    with pytest.raises(DicomConversionError):
        convert(text_file, tmp_path)


def test_batch_name_collisions_and_structure(tmp_path):
    source = get_testdata_file("CT_small.dcm")
    data = Path(source).read_bytes()
    root = tmp_path / "Badanie"
    for sub in ("seria1", "seria2"):
        (root / sub).mkdir(parents=True)
        (root / sub / "IM0001").write_bytes(data)  # bez rozszerzenia, rozpoznany po "DICM"
    (root / "DICOMDIR").write_bytes(data)
    (root / "opis.txt").write_text("x", encoding="utf-8")

    items = list(collect_inputs([root]))
    assert sorted(item.path.parent.name for item in items) == ["seria1", "seria2"]

    out = tmp_path / "out"
    results = list(convert_batch(items, out, ConvertOptions()))
    assert all(r.ok for r in results)
    assert (out / "Badanie" / "seria1" / "IM0001.png").exists()
    assert (out / "Badanie" / "seria2" / "IM0001.png").exists()

    flat = list(convert_batch(items, tmp_path / "flat", ConvertOptions(layout=LAYOUT_FLAT)))
    names = sorted(p.name for r in flat for p in r.outputs)
    assert names == ["IM0001.png", "IM0001_1.png"]


def test_existing_files_not_overwritten_by_default(tmp_path):
    source = get_testdata_file("CT_small.dcm")
    first = convert(source, tmp_path)
    second = convert(source, tmp_path)
    third = convert(source, tmp_path, overwrite=True)
    assert first[0].name == "CT_small.png"
    assert second[0].name == "CT_small_1.png"
    assert third[0].name == "CT_small.png"


def test_batch_reports_errors_without_stopping(tmp_path):
    bad = tmp_path / "zly.dcm"
    bad.write_bytes(b"\x00" * 10)
    items = [InputFile(bad), InputFile(Path(get_testdata_file("CT_small.dcm")))]
    results = {r.item.path.name: r for r in convert_batch(items, tmp_path / "out", ConvertOptions())}
    assert not results["zly.dcm"].ok
    assert results["CT_small.dcm"].ok


def test_explicitly_selected_non_dicom_files_are_skipped(tmp_path):
    text_file = tmp_path / "notatka.txt"
    text_file.write_text("to nie jest DICOM", encoding="utf-8")
    photo = tmp_path / "zdjecie.jpg"
    Image.new("RGB", (4, 4)).save(photo)
    old_format = make_grayscale(tmp_path / "IM0001", np.arange(16).reshape(4, 4), with_meta=False)
    dicom = get_testdata_file("CT_small.dcm")

    skipped = []
    items = list(collect_inputs([text_file, photo, old_format, dicom], skipped=skipped))
    assert [item.path.name for item in items] == ["IM0001", "CT_small.dcm"]
    assert skipped == [text_file, photo]


def test_preview():
    image, details = render_preview(get_testdata_file("SC_rgb_rle_2frame.dcm"), max_size=(50, 50))
    assert max(image.size) <= 50
    assert details["frames"] == "2 klatki"
    assert details["compression"] == "RLE"
    assert details["size"] == "100 × 100 px"


def test_plural():
    assert plural(1, "file") == "1 plik"
    assert plural(3, "file") == "3 pliki"
    assert plural(12, "file") == "12 plików"
    assert plural(22, "file") == "22 pliki"
