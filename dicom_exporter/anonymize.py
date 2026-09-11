"""Anonimizacja plików DICOM – uproszczony podstawowy profil poufności (DICOM PS3.15, załącznik E)."""

from __future__ import annotations

import hashlib
import secrets

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue
from pydicom.uid import generate_uid

# Dane identyfikujące pacjenta, personel i placówkę – usuwane w całości
REMOVE_KEYWORDS = frozenset(
    {
        "PatientBirthTime", "PatientBirthName", "PatientMotherBirthName", "OtherPatientIDs",
        "OtherPatientIDsSequence", "OtherPatientNames", "PatientAddress", "PatientTelephoneNumbers",
        "PatientTelecomInformation", "PatientAge", "PatientSex", "PatientSize", "PatientWeight", "MilitaryRank",
        "BranchOfService", "EthnicGroup", "Occupation", "AdditionalPatientHistory", "PatientComments",
        "MedicalRecordLocator", "ResponsiblePerson", "ResponsiblePersonRole", "ResponsibleOrganization",
        "PatientReligiousPreference", "CountryOfResidence", "RegionOfResidence", "CurrentPatientLocation",
        "PatientInstitutionResidence", "PatientState", "IssuerOfPatientID", "IssuerOfPatientIDQualifiersSequence",
        "PatientInsurancePlanCodeSequence", "PregnancyStatus", "SmokingStatus", "LastMenstrualDate", "MedicalAlerts",
        "Allergies", "SpecialNeeds", "ReferencedPatientSequence", "InstitutionName", "InstitutionAddress",
        "InstitutionalDepartmentName", "InstitutionCodeSequence", "StationName", "DeviceSerialNumber",
        "OperatorsName", "OperatorIdentificationSequence", "PerformingPhysicianName",
        "PerformingPhysicianIdentificationSequence", "NameOfPhysiciansReadingStudy",
        "PhysiciansReadingStudyIdentificationSequence", "PhysiciansOfRecord",
        "PhysiciansOfRecordIdentificationSequence", "RequestingPhysician", "ReferringPhysicianAddress",
        "ReferringPhysicianTelephoneNumbers", "ReferringPhysicianIdentificationSequence",
        "ScheduledPerformingPhysicianName", "RequestAttributesSequence", "AdmissionID",
        "AdmittingDiagnosesDescription", "AdmittingDiagnosesCodeSequence", "FillerOrderNumberImagingServiceRequest",
        "PlacerOrderNumberImagingServiceRequest", "OrderEnteredBy", "OrderEntererLocation",
        "OrderCallbackPhoneNumber", "ImageComments", "StudyComments", "ContentCreatorName",
        "VerifyingObserverName", "VerifyingObserverSequence", "PersonName", "PersonAddress",
        "PersonTelephoneNumbers", "RequestedProcedureID", "ScheduledProcedureStepID", "PerformedProcedureStepID",
        "PerformedStationName", "PerformedLocation", "ScheduledStationName", "ScheduledProcedureStepLocation",
    }
)  # fmt: skip

# Elementy wymagane (typ 2) – zostają, ale bez wartości
EMPTY_KEYWORDS = frozenset({"PatientBirthDate", "ReferringPhysicianName", "AccessionNumber", "StudyID"})

DATE_KEYWORDS = frozenset(
    {
        "StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate", "OverlayDate", "CurveDate", "StudyTime",
        "SeriesTime", "AcquisitionTime", "ContentTime", "AcquisitionDateTime", "InstanceCreationDate",
        "InstanceCreationTime", "PerformedProcedureStepStartDate", "PerformedProcedureStepStartTime",
        "PerformedProcedureStepEndDate", "PerformedProcedureStepEndTime", "ScheduledProcedureStepStartDate",
        "ScheduledProcedureStepStartTime", "DateOfLastCalibration", "TimeOfLastCalibration",
    }
)  # fmt: skip

UID_KEYWORDS = frozenset(
    {
        "StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "ReferencedSOPInstanceUID", "FrameOfReferenceUID",
        "SynchronizationFrameOfReferenceUID", "IrradiationEventUID", "DimensionOrganizationUID", "ConcatenationUID",
        "RelatedFrameOfReferenceUID", "ReferencedFrameOfReferenceUID", "InstanceCreatorUID", "StorageMediaFileSetUID",
        "TransactionUID",
    }
)  # fmt: skip

METHOD = "DICOM Exporter: basic confidentiality profile"  # element typu LO: maks. 64 znaki


class Anonymizer:
    """Zamienia dane pacjenta i identyfikatory na pseudonimy spójne w obrębie jednej partii.

    Ten sam pacjent/badanie/seria dostaje ten sam pseudonim, więc anonimizowane pliki nadal tworzą serie.
    Losowa sól sprawia, że pseudonimów nie da się odwrócić ani powiązać między różnymi partiami.
    """

    def __init__(self, patient_name: str = "ANONIM", keep_dates: bool = False) -> None:
        self.patient_name = patient_name.strip() or "ANONIM"
        self.keep_dates = keep_dates
        self._salt = secrets.token_hex(16)

    def pseudonym(self, value: str) -> str:
        return "ANON-" + hashlib.sha256(f"{self._salt}|{value}".encode()).hexdigest()[:12].upper()

    def uid(self, value: str) -> str:
        return generate_uid(entropy_srcs=[self._salt, value])

    def apply(self, ds: Dataset) -> Dataset:
        original_id = str(ds.get("PatientID") or "")

        def clean(dataset: Dataset, element) -> None:
            if element.tag.is_private:
                del dataset[element.tag]
                return
            keyword = element.keyword
            if keyword in REMOVE_KEYWORDS:
                del dataset[element.tag]
            elif keyword == "PatientName":
                element.value = self.patient_name
            elif keyword == "PatientID":
                element.value = self.pseudonym(str(element.value or ""))
            elif keyword in EMPTY_KEYWORDS:
                element.value = ""
            elif keyword in UID_KEYWORDS and element.value:
                if isinstance(element.value, (MultiValue, list)):
                    element.value = [self.uid(str(value)) for value in element.value]
                else:
                    element.value = self.uid(str(element.value))
            elif keyword in DATE_KEYWORDS and not self.keep_dates:
                element.value = ""

        ds.walk(clean)
        ds.PatientName = self.patient_name
        ds.PatientID = self.pseudonym(original_id)
        ds.PatientIdentityRemoved = "YES"
        ds.DeidentificationMethod = METHOD
        meta = getattr(ds, "file_meta", None)
        if meta is not None and "SOPInstanceUID" in ds:
            meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        return ds
