from pathlib import Path

import numpy as np
import pydicom
import pytest
from PIL import Image
from pydicom.data import get_testdata_file
from test_features import make_image

from dicom_exporter import cli
from dicom_exporter.anonymize import Anonymizer
from dicom_exporter.converter import (
    EXPORT_DICOM,
    LAYOUT_FLAT,
    ConvertOptions,
    InputFile,
    PreviewSource,
    collect_inputs,
    convert_batch,
    convert_file,
)
from dicom_exporter.overlays import format_length, info_lines, nice_length, pixel_spacing
from dicom_exporter.profiles import BUILTIN_PROFILES, convert_kwargs


@pytest.fixture
def ct(tmp_path) -> Path:
    """CT 200×100 z poziomym gradientem i danymi pacjenta."""
    return make_image(
        tmp_path / "ct.dcm",
        np.tile(np.arange(200), (100, 1)) + 500,
        Modality="CT",
        PixelSpacing=[0.5, 0.5],
        SeriesNumber=4,
        InstanceNumber=9,
        StudyDate="20250101",
        SeriesDescription="Glowa",
        PatientName="Kowalski^Jan",
        PatientID="12345",
        PatientBirthDate="19800101",
        InstitutionName="Szpital",
    )


def export(path, out_dir, **options) -> np.ndarray:
    [output] = convert_file(InputFile(Path(path)), out_dir, ConvertOptions(**options))
    with Image.open(output) as image:
        return np.asarray(image).astype(int)


# --------------------------------------------------------------------------- maskowanie


def test_masks_black_out_regions(ct, tmp_path):
    array = export(ct, tmp_path, masks=[(0, 0, 1, 0.2)])
    assert array[:20].max() == 0
    assert array[50, 100] > 0


def test_invalid_mask_is_rejected():
    with pytest.raises(ValueError):
        ConvertOptions(masks=[(0.5, 0, 0.2, 1)])


def test_preview_shows_masks(ct):
    image = PreviewSource(ct).render(0, ConvertOptions(masks=[(0, 0.5, 1, 1)]))
    assert np.asarray(image)[50:].max() == 0


# --------------------------------------------------------------------------- nakładki


def test_scale_bar_and_info_overlay(ct, tmp_path):
    plain = export(ct, tmp_path / "plain")
    overlay = export(ct, tmp_path / "overlay", overlay_scale=True, overlay_info=True)
    assert (overlay[88:, :60] != plain[88:, :60]).any()  # podziałka w lewym dolnym rogu
    assert (overlay[:15, :60] != plain[:15, :60]).any()  # tekst w lewym górnym rogu
    assert (overlay[70:, 120:] == plain[70:, 120:]).all()  # reszta obrazu bez zmian


def test_overlay_keeps_16_bit_depth(ct, tmp_path):
    [output] = convert_file(InputFile(ct), tmp_path, ConvertOptions(bit_depth=16, overlay_scale=True))
    with Image.open(output) as image:
        assert image.mode == "I;16"
        assert np.asarray(image).max() == 65535


def test_overlay_helpers(ct):
    ds = pydicom.dcmread(ct)
    assert pixel_spacing(ds) == (0.5, 0.5)
    assert nice_length(37) == 20 and nice_length(0.8) == 0.5
    assert format_length(20) == "2 cm" and format_length(5) == "5 mm"
    assert info_lines(ds, 0, 1, ConvertOptions(overlay_info=True)) == ["CT · Seria 4 · Obraz 9", "Glowa", "2025-01-01"]
    assert info_lines(ds, 1, 3, ConvertOptions(overlay_patient=True)) == ["Kowalski Jan · 12345"]
    assert not ConvertOptions(export_mode=EXPORT_DICOM, overlay_info=True).overlays_enabled


# --------------------------------------------------------------------------- anonimizacja


def test_anonymized_dicom_copies(tmp_path):
    source = Path(get_testdata_file("CT_small.dcm"))
    folder = tmp_path / "in"
    folder.mkdir()
    for name in ("a.dcm", "b.dcm"):
        (folder / name).write_bytes(source.read_bytes())
    options = ConvertOptions(export_mode=EXPORT_DICOM, layout=LAYOUT_FLAT)
    results = list(convert_batch(collect_inputs([folder]), tmp_path / "out", options))
    assert all(result.ok for result in results)

    original = pydicom.dcmread(source)
    first, second = (pydicom.dcmread(path) for path in sorted(p for r in results for p in r.outputs))
    assert first.PatientName == "ANONIM"
    assert first.PatientID.startswith("ANON-") and first.PatientID == second.PatientID != original.PatientID
    assert first.PatientIdentityRemoved == "YES"
    assert "OtherPatientIDsSequence" in original and "OtherPatientIDsSequence" not in first
    assert not any(element.tag.is_private for element in first)
    assert first.StudyDate == "" and first.get("PatientBirthDate", "") == ""
    assert first.StudyInstanceUID == second.StudyInstanceUID != original.StudyInstanceUID
    assert first.file_meta.MediaStorageSOPInstanceUID == first.SOPInstanceUID
    assert np.array_equal(first.pixel_array, original.pixel_array)


def test_anonymized_copy_with_mask_of_compressed_file(tmp_path):
    item = InputFile(Path(get_testdata_file("MR_small_jp2klossless.dcm")))
    options = ConvertOptions(export_mode=EXPORT_DICOM, masks=[(0, 0, 0.5, 0.5)], anonymize_keep_dates=True)
    [result] = convert_batch([item], tmp_path, options)
    assert result.ok, result.error
    copy, original = pydicom.dcmread(result.outputs[0]), pydicom.dcmread(item.path)
    assert not copy.file_meta.TransferSyntaxUID.is_compressed
    masked = copy.pixel_array
    assert (masked[:32, :32] == original.pixel_array.min()).all()
    assert np.array_equal(masked[32:, 32:], original.pixel_array[32:, 32:])
    assert copy.StudyDate == original.StudyDate


def test_pseudonyms_depend_on_batch():
    anonymizer = Anonymizer()
    assert anonymizer.pseudonym("123") == anonymizer.pseudonym("123") != Anonymizer().pseudonym("123")


# --------------------------------------------------------------------------- profile i CLI


@pytest.mark.parametrize("key", list(BUILTIN_PROFILES))
def test_builtin_profiles_are_valid(key):
    ConvertOptions(**convert_kwargs(BUILTIN_PROFILES[key]))


def test_cli_profile_mask_and_overlay(ct, tmp_path):
    out = tmp_path / "out"
    code = cli.main([str(ct), "-o", str(out), "--profile", "email", "--mask-top", "10", "--overlay-info", "--layout", "flat"])
    assert code == 0
    with Image.open(out / "ct.jpg") as image:
        assert image.format == "JPEG" and image.size == (200, 100)


def test_cli_anonymized_export(ct, tmp_path):
    out = tmp_path / "anon"
    assert cli.main([str(ct), "-o", str(out), "--export", "dicom", "--layout", "flat", "--anon-name", "PACJENT"]) == 0
    copy = pydicom.dcmread(out / "ct.dcm")
    assert copy.PatientName == "PACJENT" and "InstitutionName" not in copy
