import csv
from pathlib import Path

import numpy as np
import pydicom
import pytest
from PIL import Image, ImageSequence
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from dicom_exporter import cli, naming
from dicom_exporter.converter import (
    CT_PRESETS,
    EXPORT_GIF,
    EXPORT_MONTAGE,
    EXPORT_MP4,
    LAYOUT_FLAT,
    LAYOUT_TEMPLATE,
    MONTAGE_TILE,
    RESIZE_FIT,
    RESIZE_SCALE,
    WINDOW_CUSTOM,
    WINDOW_MINMAX,
    ConvertOptions,
    DicomConversionError,
    FileResult,
    InputFile,
    PreviewSource,
    collect_inputs,
    convert_batch,
    convert_file,
    group_series,
)
from dicom_exporter.dicominfo import dataset_tags, format_size, read_dicomdir, read_file_info
from dicom_exporter.i18n import plural, set_language
from dicom_exporter.report import write_report


def make_image(path: Path, pixels, **attributes) -> Path:
    ds = Dataset()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = generate_uid()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.set_pixel_data(np.asarray(pixels).astype(np.uint16), "MONOCHROME2", 16)
    for keyword, value in attributes.items():
        setattr(ds, keyword, value)
    ds.save_as(path, enforce_file_format=True)
    return path


@pytest.fixture
def ramp(tmp_path) -> Path:
    """Obraz CT 64×64 z wartościami 0..4095 (piksel o indeksie i ma wartość i)."""
    return make_image(
        tmp_path / "ramp.dcm",
        np.arange(4096).reshape(64, 64),
        Modality="CT",
        SeriesNumber=3,
        InstanceNumber=12,
        RescaleSlope=1,
        RescaleIntercept=-1024,
        StudyDate="20260910",
        StudyDescription="Glowa",
        SeriesDescription="Osiowe",
    )


@pytest.fixture
def series(tmp_path) -> Path:
    """Seria 5 obrazów zapisanych w innej kolejności niż numery obrazów; jasność = numer * 100."""
    uid = generate_uid()
    folder = tmp_path / "seria"
    folder.mkdir()
    for instance in (3, 1, 5, 2, 4):
        make_image(
            folder / f"plik_{6 - instance}.dcm",
            np.full((21, 31), instance * 100),
            SeriesInstanceUID=uid,
            InstanceNumber=instance,
            Modality="MR",
            SeriesNumber=7,
            SeriesDescription="T2",
        )
    return folder


def convert(path, out_dir, **options) -> list[Path]:
    return convert_file(InputFile(Path(path)), out_dir, ConvertOptions(**options))


# --------------------------------------------------------------------------- głębia bitowa i kontrast


@pytest.mark.parametrize("fmt", ["PNG", "TIFF"])
def test_16bit_output_keeps_all_levels(ramp, tmp_path, fmt):
    [output] = convert(ramp, tmp_path, fmt=fmt, bit_depth=16, windowing=WINDOW_MINMAX)
    with Image.open(output) as image:
        assert image.mode == "I;16"
        array = np.asarray(image)
    assert array.min() == 0 and array.max() == 65535
    assert len(np.unique(array)) == 4096  # w 8 bitach byłoby najwyżej 256 poziomów


def test_16bit_not_allowed_for_jpeg():
    with pytest.raises(ValueError):
        ConvertOptions(fmt="JPG", bit_depth=16)


def test_custom_window_preset(ramp, tmp_path):
    center, width = CT_PRESETS["brain"]  # 40 / 80 HU
    [output] = convert(ramp, tmp_path, windowing=WINDOW_CUSTOM, window_center=center, window_width=width)
    array = np.asarray(Image.open(output)).ravel()
    assert array[1000] == 0  # -24 HU, poniżej okna
    assert 120 <= array[1064] <= 135  # 40 HU, środek okna
    assert array[1200] == 255  # 176 HU, powyżej okna


def test_preview_source_value_range(ramp):
    source = PreviewSource(ramp)
    assert source.value_range() == (-1024.0, 3071.0)
    assert source.render(0, ConvertOptions()).mode == "L"


# --------------------------------------------------------------------------- rozmiar i formaty


def test_resize_fit_and_scale(ramp, tmp_path):
    [fit] = convert(ramp, tmp_path / "fit", resize_mode=RESIZE_FIT, max_width=32, max_height=16)
    [no_upscale] = convert(ramp, tmp_path / "big", resize_mode=RESIZE_FIT, max_width=500, max_height=500)
    [scaled] = convert(ramp, tmp_path / "scale", resize_mode=RESIZE_SCALE, scale_percent=50, bit_depth=16)
    assert Image.open(fit).size == (16, 16)
    assert Image.open(no_upscale).size == (64, 64)
    with Image.open(scaled) as image:
        assert image.size == (32, 32) and image.mode == "I;16"


@pytest.mark.parametrize("fmt, pil_format", [("TIFF", "TIFF"), ("WEBP", "WEBP"), ("BMP", "BMP")])
def test_additional_formats(tmp_path, fmt, pil_format):
    [output] = convert(get_testdata_file("CT_small.dcm"), tmp_path, fmt=fmt)
    assert output.suffix == f".{fmt.lower()}"
    with Image.open(output) as image:
        assert image.format == pil_format


# --------------------------------------------------------------------------- szablony nazw


def test_name_and_folder_templates(ramp, tmp_path):
    [output] = convert(
        ramp,
        tmp_path,
        name_template="{Modality}_{SeriesNumber:03}_{InstanceNumber:04}",
        layout=LAYOUT_TEMPLATE,
    )
    assert output == tmp_path / "20260910_Glowa" / "S3_Osiowe" / "CT_003_0012.png"


def test_template_aliases_and_validation(ramp):
    ds = pydicom.dcmread(ramp)
    assert naming.render_filename("{Modalność}_{Seria}_{NrObrazu}", ds, file_stem="x") == "CT_3_12"
    assert naming.render_filename("{PatientName}", ds, file_stem="x") == "NA"
    assert naming.unknown_fields("{Foo}_{modality}") == ["Foo"]
    with pytest.raises(ValueError, match="Foo"):
        ConvertOptions(name_template="{Foo}")


def test_template_frames_and_sanitizing():
    assert naming.render_filename("{file}", None, file_stem="a", frame=2, total_frames=10) == "a_frame002"
    assert naming.render_filename("{file}-{frame}", None, file_stem="a", frame=2, total_frames=10) == "a-002"
    assert naming.sanitize('a<b>:c|d?') == "a_b__c_d_"
    assert naming.sanitize("CON") == "_CON"
    assert naming.render_folder("{file}/../x", None, file_stem="a:b") == Path("a_b") / "x"


# --------------------------------------------------------------------------- serie


def test_group_series_sorts_by_instance_number(series):
    [group] = group_series(collect_inputs([series]))
    numbers = [int(pydicom.dcmread(item.path).InstanceNumber) for item in group.items]
    assert numbers == [1, 2, 3, 4, 5]


def series_options(**extra) -> ConvertOptions:
    return ConvertOptions(layout=LAYOUT_FLAT, windowing=WINDOW_CUSTOM, window_center=300, window_width=600, **extra)


def test_series_as_gif(series, tmp_path):
    results = list(convert_batch(collect_inputs([series]), tmp_path, series_options(export_mode=EXPORT_GIF)))
    assert len(results) == 5 and all(result.ok for result in results)
    [output] = {path for result in results for path in result.outputs}
    assert output.name == "MR_S7_T2.gif"
    with Image.open(output) as image:
        means = [np.asarray(frame.convert("L")).mean() for frame in ImageSequence.Iterator(image)]
    assert len(means) == 5 and means == sorted(means)


def test_series_as_mp4(series, tmp_path):
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    results = list(convert_batch(collect_inputs([series]), tmp_path, series_options(export_mode=EXPORT_MP4, fps=5)))
    [output] = {path for result in results for path in result.outputs}
    assert output.suffix == ".mp4"
    frames, _seconds = imageio_ffmpeg.count_frames_and_secs(str(output))
    assert frames == 5


def test_series_as_montage(series, tmp_path):
    results = list(convert_batch(collect_inputs([series]), tmp_path, series_options(export_mode=EXPORT_MONTAGE)))
    [output] = {path for result in results for path in result.outputs}
    with Image.open(output) as image:  # 5 miniatur -> 3 kolumny × 2 wiersze
        assert image.size == (3 * (MONTAGE_TILE + 4) + 4, 2 * (MONTAGE_TILE + 4) + 4)


def test_multiframe_file_as_gif(tmp_path):
    item = InputFile(Path(get_testdata_file("SC_rgb_rle_2frame.dcm")))
    [result] = convert_batch([item], tmp_path, ConvertOptions(export_mode=EXPORT_GIF))
    assert result.outputs[0].name == "SC_rgb_rle_2frame.gif"
    with Image.open(result.outputs[0]) as image:
        assert image.n_frames == 2


# --------------------------------------------------------------------------- raport, informacje, DICOMDIR


def test_csv_report(tmp_path):
    ok = FileResult(InputFile(Path("a.dcm")), outputs=[tmp_path / "sub" / "a.png"])
    failed = FileResult(InputFile(Path("b.dcm")), error="Plik nie zawiera obrazu")
    from datetime import datetime

    report = write_report([failed, ok], tmp_path, datetime(2026, 9, 10, 12, 30, 0))
    assert report.name == "raport_konwersji_20260910_123000.csv"
    with report.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows[0] == ["Plik źródłowy", "Status", "Pliki wynikowe", "Błąd"]
    assert rows[1] == ["a.dcm", "OK", str(Path("sub") / "a.png"), ""]
    assert rows[2] == ["b.dcm", "BŁĄD", "", "Plik nie zawiera obrazu"]


def test_file_info(ramp):
    info = read_file_info(ramp)
    assert (info.modality, info.series_number, info.instance_number, info.frames) == ("CT", 3, 12, 1)
    assert (info.columns, info.rows) == (64, 64) and info.file_size > 0
    assert format_size(2048) == "2.0 KB"


def test_dataset_tags():
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    rows = {row.name: row for row in dataset_tags(ds)}
    assert rows["Patient ID"].tag == "(0010,0020)"
    assert rows["Pixel Data"].value.startswith("<")

    parent = Dataset()
    parent.ReferencedImageSequence = Sequence([Dataset(), Dataset()])
    parent.ReferencedImageSequence[0].ReferencedSOPInstanceUID = "1.2.3"
    [row] = dataset_tags(parent)
    assert row.vr == "SQ" and len(row.children) == 2
    assert row.children[0].children[0].value == "1.2.3"


def test_read_dicomdir():
    patients = read_dicomdir(Path(get_testdata_file("DICOMDIR")))
    assert sorted(patient.patient_id for patient in patients) == ["77654033", "98890234"]
    series = [s for patient in patients for study in patient.studies.values() for s in study.series.values()]
    assert len(series) == 13
    assert all(path.is_file() for s in series for path in s.files)


def test_english_messages(tmp_path):
    set_language("en")
    try:
        assert plural(2, "file") == "2 files"
        with pytest.raises(DicomConversionError, match="no pixel data"):
            convert(get_testdata_file("rtplan.dcm"), tmp_path)
    finally:
        set_language("pl")


def test_cli_end_to_end(ramp, tmp_path):
    out = tmp_path / "out"
    code = cli.main(
        [
            str(ramp),
            "-o", str(out),
            "--preset", "brain",
            "--max-size", "32x32",
            "--name-template", "{Modality}_{InstanceNumber}",
            "--layout", "flat",
            "--report",
        ]
    )  # fmt: skip
    assert code == 0
    assert Image.open(out / "CT_12.png").size == (32, 32)
    assert len(list(out.glob("raport_konwersji_*.csv"))) == 1
