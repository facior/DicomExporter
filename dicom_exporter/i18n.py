"""Tłumaczenia komunikatów i interfejsu (polski i angielski)."""

from __future__ import annotations

LANGUAGES = {"pl": "Polski", "en": "English"}
DEFAULT_LANGUAGE = "pl"
_language = DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else DEFAULT_LANGUAGE


def get_language() -> str:
    return _language


def t(key: str, **values) -> str:
    """Tekst w bieżącym języku; `values` wstawiane są w miejsca {nazwa}."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry[1] if _language == "en" else entry[0]
    return text.format(**values) if values else text


def plural(count: int, key: str) -> str:
    """Liczba z poprawną formą rzeczownika, np. "5 plików" / "5 files"."""
    forms = PLURALS[key]
    if _language == "en":
        form = forms[3] if count == 1 else forms[4]
    elif count == 1:
        form = forms[0]
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        form = forms[1]
    else:
        form = forms[2]
    return f"{count} {form}"


# (pl: 1, 2-4, 5+ ; en: 1, wiele)
PLURALS: dict[str, tuple[str, str, str, str, str]] = {
    "file": ("plik", "pliki", "plików", "file", "files"),
    "image": ("obraz", "obrazy", "obrazów", "image", "images"),
    "frame": ("klatka", "klatki", "klatek", "frame", "frames"),
    "series": ("seria", "serie", "serii", "series", "series"),
    "study": ("badanie", "badania", "badań", "study", "studies"),
    "item": ("element", "elementy", "elementów", "item", "items"),
    "byte": ("bajt", "bajty", "bajtów", "byte", "bytes"),
    "area": ("obszar", "obszary", "obszarów", "area", "areas"),
}

# klucz: (polski, angielski)
STRINGS: dict[str, tuple[str, str]] = {
    # --- Błędy konwersji
    "err_not_found": ("Plik nie istnieje", "File does not exist"),
    "err_access": ("Brak dostępu do pliku", "Access to the file was denied"),
    "err_not_dicom": ("To nie jest prawidłowy plik DICOM: {error}", "Not a valid DICOM file: {error}"),
    "err_no_pixels": ("Plik nie zawiera obrazu (brak danych pikseli)", "The file contains no image (no pixel data)"),
    "err_decode": (
        "Nie można zdekodować obrazu (kodowanie: {syntax}): {error}",
        "Cannot decode the image (encoding: {syntax}): {error}",
    ),
    "err_layout": ("Nieobsługiwany układ pikseli: {shape} ({photometric})", "Unsupported pixel layout: {shape} ({photometric})"),
    "err_save": ("Nie można zapisać pliku: {error}", "Cannot save the file: {error}"),
    "err_unexpected": ("Nieoczekiwany błąd: {error}", "Unexpected error: {error}"),
    "err_series_empty": ("Seria nie zawiera żadnego obrazu", "The series contains no images"),
    "err_mp4": ("Eksport MP4 wymaga pakietu imageio-ffmpeg", "MP4 export requires the imageio-ffmpeg package"),
    "err_video": ("Nie można zapisać wideo: {error}", "Cannot write the video: {error}"),
    "err_dicomdir": ("Nie można odczytać pliku DICOMDIR: {error}", "Cannot read the DICOMDIR file: {error}"),
    "err_opt_format": ("Nieobsługiwany format: {value}", "Unsupported format: {value}"),
    "err_opt_bit_depth": ("Głębia bitowa musi wynosić 8 lub 16", "Bit depth must be 8 or 16"),
    "err_opt_bit_depth_format": ("16 bitów obsługują tylko formaty PNG i TIFF", "Only PNG and TIFF support 16 bits"),
    "err_opt_quality": ("Jakość musi mieścić się w zakresie 1–100", "Quality must be between 1 and 100"),
    "err_opt_window": ("Nieznany tryb kontrastu: {value}", "Unknown contrast mode: {value}"),
    "err_opt_window_width": ("Szerokość okna musi być większa od zera", "Window width must be greater than zero"),
    "err_opt_resize": ("Nieprawidłowe ustawienia zmiany rozmiaru", "Invalid resize settings"),
    "err_opt_layout": ("Nieznany układ folderów: {value}", "Unknown folder layout: {value}"),
    "err_opt_export": ("Nieznany tryb eksportu: {value}", "Unknown export mode: {value}"),
    "err_opt_fps": ("Liczba klatek na sekundę musi mieścić się w zakresie 1–60", "Frames per second must be between 1 and 60"),
    "err_template": ("Nieznane pola w szablonie: {fields}", "Unknown template fields: {fields}"),
    "err_opt_mask": ("Nieprawidłowy obszar maskowania", "Invalid mask area"),
    "err_opt_anonymize_name": (
        "Podaj nazwę pacjenta dla anonimizowanych kopii",
        "Enter a patient name for anonymized copies",
    ),
    # --- Nakładki
    "overlay_series": ("Seria {number}", "Series {number}"),
    "overlay_image": ("Obraz {number}", "Image {number}"),
    "overlay_frame": ("Klatka {current}/{total}", "Frame {current}/{total}"),
    "overlay_slice": ("Poz. {value} mm", "Loc. {value} mm"),
    # --- Profile eksportu
    "profile_presentation": ("Prezentacja (JPG Full HD z podziałką)", "Presentation (Full HD JPG with scale bar)"),
    "profile_analysis16": ("Analiza (PNG 16-bit, pełny zakres)", "Analysis (16-bit PNG, full range)"),
    "profile_email": ("E-mail (małe JPG)", "E-mail (small JPG)"),
    "profile_anonymized_dicom": ("Anonimizowane kopie DICOM", "Anonymized DICOM copies"),
    "profile_cine_mp4": ("Wideo serii (MP4 z opisem)", "Series video (MP4 with labels)"),
    "cli_profile": ("gotowy profil ustawień (jawnie podane opcje mają pierwszeństwo)", "built-in settings profile (explicit options take precedence)"),
    "cli_mask": (
        "zamaskuj prostokąt X0,Y0,X1,Y1 podany jako ułamki wymiarów, np. 0,0,1,0.1 (można powtarzać)",
        "mask the rectangle X0,Y0,X1,Y1 given as fractions of the size, e.g. 0,0,1,0.1 (repeatable)",
    ),
    # w opisach opcji wiersza poleceń znak procentu zapisujemy jako %% (wymóg argparse)
    "cli_mask_top": ("zamaskuj górny pasek o podanej wysokości w %%", "mask a top band of the given height in %%"),
    "cli_mask_bottom": ("zamaskuj dolny pasek o podanej wysokości w %%", "mask a bottom band of the given height in %%"),
    "cli_bad_mask": ("oczekiwano X0,Y0,X1,Y1 w zakresie 0–1, np. 0,0,1,0.1", "expected X0,Y0,X1,Y1 between 0 and 1, e.g. 0,0,1,0.1"),
    "cli_overlay_scale": ("dodaj podziałkę w mm", "add a scale bar in mm"),
    "cli_overlay_info": ("dodaj informacje o obrazie (seria, numer, data)", "add image information (series, number, date)"),
    "cli_overlay_patient": ("dodaj dane pacjenta (imię i ID) – dane osobowe!", "add patient data (name and ID) – personal data!"),
    "cli_anon_name": ("nazwa pacjenta w anonimizowanych kopiach (domyślnie ANONIM)", "patient name in anonymized copies (default ANONIM)"),
    "cli_keep_dates": ("zachowaj daty badań w anonimizowanych kopiach", "keep study dates in anonymized copies"),
    # --- Opis obrazu i tagi
    "uncompressed": ("bez kompresji", "uncompressed"),
    "series_fallback": ("seria", "series"),
    "tag_item": ("Element {index}", "Item {index}"),
    "tag_more_items": ("… i {count} więcej", "… and {count} more"),
    # --- Raport CSV
    "report_prefix": ("raport_konwersji", "conversion_report"),
    "report_source": ("Plik źródłowy", "Source file"),
    "report_status": ("Status", "Status"),
    "report_outputs": ("Pliki wynikowe", "Output files"),
    "report_error": ("Błąd", "Error"),
    "report_ok": ("OK", "OK"),
    "report_failed": ("BŁĄD", "ERROR"),
    # --- Wiersz poleceń
    "cli_description": (
        "Konwersja plików DICOM do obrazów, animacji i kolaży.",
        "Convert DICOM files to images, animations and contact sheets.",
    ),
    "cli_inputs": ("pliki, foldery lub pliki DICOMDIR", "files, folders or DICOMDIR files"),
    "cli_output": ("folder docelowy", "output folder"),
    "cli_format": ("format obrazów", "image format"),
    "cli_bit_depth": ("głębia bitowa dla PNG i TIFF (8 lub 16)", "bit depth for PNG and TIFF (8 or 16)"),
    "cli_quality": ("jakość JPG/JPEG/WebP 1–100 (domyślnie 95)", "JPG/JPEG/WebP quality 1–100 (default 95)"),
    "cli_window": (
        "kontrast: dicom = okno z pliku, minmax = pełny zakres, custom = --center/--width",
        "contrast: dicom = window from file, minmax = full range, custom = --center/--width",
    ),
    "cli_preset": ("gotowe okno CT (włącza tryb custom)", "CT window preset (enables custom mode)"),
    "cli_center": ("środek okna dla trybu custom", "window center for custom mode"),
    "cli_width": ("szerokość okna dla trybu custom", "window width for custom mode"),
    "cli_max_size": ("zmniejsz do maksymalnych wymiarów, np. 1024x768", "downscale to fit within, e.g. 1024x768"),
    "cli_scale": ("skaluj o podany procent (1–400)", "scale by percent (1–400)"),
    "cli_name": (
        "szablon nazwy pliku, np. {Modality}_{SeriesNumber:03}_{InstanceNumber:04}",
        "file name template, e.g. {Modality}_{SeriesNumber:03}_{InstanceNumber:04}",
    ),
    "cli_layout": (
        "układ folderów: flat = jeden folder, source = jak źródło, template = --folder-template",
        "folder layout: flat = single folder, source = like the source, template = --folder-template",
    ),
    "cli_folder_template": ("szablon folderów, np. {StudyDate}/{SeriesNumber}", "folder template, e.g. {StudyDate}/{SeriesNumber}"),
    "cli_export": (
        "tryb eksportu: images = osobne obrazy; gif, mp4, montage = jeden plik na serię",
        "export mode: images = separate images; gif, mp4, montage = one file per series",
    ),
    "cli_fps": ("klatki na sekundę dla GIF i MP4 (domyślnie 10)", "frames per second for GIF and MP4 (default 10)"),
    "cli_first_frame": ("z plików wieloklatkowych tylko pierwsza klatka", "only the first frame of multi-frame files"),
    "cli_overwrite": ("nadpisuj istniejące pliki", "overwrite existing files"),
    "cli_report": ("zapisz raport CSV w folderze docelowym", "save a CSV report in the output folder"),
    "cli_workers": ("liczba wątków (domyślnie automatycznie)", "number of threads (default: automatic)"),
    "cli_lang": ("język komunikatów", "message language"),
    "cli_bad_size": ("oczekiwano formatu SZERxWYS, np. 1024x768", "expected WIDTHxHEIGHT, e.g. 1024x768"),
    "cli_bad_range": ("wartość musi mieścić się w zakresie {low}–{high}", "value must be between {low} and {high}"),
    "cli_no_files": ("Nie znaleziono plików DICOM.", "No DICOM files found."),
    "cli_skipped": ("Pominięto (to nie jest plik DICOM): {path}", "Skipped (not a DICOM file): {path}"),
    "cli_ok_line": ("[{done}/{total}] {path} -> {images}", "[{done}/{total}] {path} -> {images}"),
    "cli_error_line": ("[{done}/{total}] BŁĄD {path}: {error}", "[{done}/{total}] ERROR {path}: {error}"),
    "cli_report_saved": ("Raport: {path}", "Report: {path}"),
    "summary": ("Przekonwertowano {files} ({images})", "Converted {files} ({images})"),
    "summary_errors": (", błędy: {count}", ", errors: {count}"),
    # --- O programie
    "cap_input": ("Pliki wejściowe", "Input files"),
    "cap_input_text": (
        "DICOM: .dcm, .dicom, .dic, .ima, pliki bez rozszerzenia oraz płyty z plikiem DICOMDIR",
        "DICOM: .dcm, .dicom, .dic, .ima, files without an extension and discs with a DICOMDIR file",
    ),
    "cap_compression": ("Kompresja", "Compression"),
    "cap_compression_text": (
        "bez kompresji, JPEG, JPEG Lossless, JPEG-LS, JPEG 2000, RLE",
        "uncompressed, JPEG, JPEG Lossless, JPEG-LS, JPEG 2000, RLE",
    ),
    "cap_images": ("Rodzaje obrazów", "Image types"),
    "cap_images_text": (
        "skala szarości (MONOCHROME1/2), RGB, YBR, paleta kolorów; 8–32 bity; pliki wieloklatkowe",
        "grayscale (MONOCHROME1/2), RGB, YBR, palette color; 8–32 bits; multi-frame files",
    ),
    "cap_output": ("Formaty wyjściowe", "Output formats"),
    "cap_output_text": (
        "PNG i TIFF (8 lub 16 bitów), JPG, JPEG, WebP, BMP; serie jako GIF, MP4 lub kolaż; anonimizowane kopie DICOM",
        "PNG and TIFF (8 or 16-bit), JPG, JPEG, WebP, BMP; series as GIF, MP4 or a contact sheet; anonymized DICOM copies",
    ),
    "cap_contrast": ("Jasność i kontrast", "Brightness and contrast"),
    "cap_contrast_text": (
        "okno z pliku, pełny zakres min–max, własne okno oraz presety CT (mózg, płuca, kości, tkanki miękkie…)",
        "window from the file, full min–max range, custom window and CT presets (brain, lung, bone, soft tissue…)",
    ),
    "cap_processing": ("Przetwarzanie", "Processing"),
    "cap_processing_text": (
        "wsadowe i równoległe; profile, szablony nazw i folderów, zmiana rozmiaru, maskowanie napisów, "
        "podziałka i opisy na obrazie, raport CSV",
        "batch and parallel; profiles, name and folder templates, resizing, masking burned-in text, "
        "scale bar and labels on images, CSV report",
    ),
    "sc_add": ("Dodaj pliki", "Add files"),
    "sc_delete": ("Usuń zaznaczone pliki z listy", "Remove selected files from the list"),
    "sc_select_all": ("Zaznacz wszystkie pliki na liście", "Select all files in the list"),
    "sc_about": ("Okno „O programie”", "“About” window"),
    "sc_tab": ("Następna karta w oknie", "Next tab in a window"),
    "sc_escape": ("Zamknij okno dialogowe", "Close a dialog"),
    "sc_wheel": ("Kółko myszy", "Mouse wheel"),
    "sc_zoom": ("Powiększanie podglądu (przeciągnij, aby przesunąć)", "Zoom the preview (drag to pan)"),
    "sc_double_click": ("Dwuklik", "Double-click"),
    "sc_fit": ("Dopasuj podgląd do okna", "Fit the preview"),
    "sc_frames": ("Poprzednia / następna klatka lub obraz serii", "Previous / next frame or series image"),
    "sc_ctrl_wheel_key": ("Ctrl + kółko myszy", "Ctrl + mouse wheel"),
    "sc_space_key": ("Spacja", "Space"),
    "sc_play": ("Odtwarzanie serii w podglądzie", "Play the series in the preview"),
    "sc_right_drag_key": ("Prawy przycisk + przeciąganie", "Right button + drag"),
    "sc_window_drag": ("Jasność (w pionie) i kontrast (w poziomie)", "Brightness (vertical) and contrast (horizontal)"),
    "privacy_note": (
        "Pliki są przetwarzane wyłącznie na tym komputerze – program nie wysyła ich ani żadnych danych o nich "
        "do internetu (jedyne połączenie to opcjonalne sprawdzanie aktualizacji na GitHubie). "
        "Zapisane obrazy nie zawierają metadanych DICOM, ale dane pacjenta mogą być wpalone w sam obraz "
        "(np. napisy na zdjęciach USG), a szablony nazw mogą je umieścić w nazwach plików.",
        "Files are processed only on this computer – neither they nor any data about them is sent to the internet "
        "(the only connection is the optional update check on GitHub). "
        "Saved images contain no DICOM metadata, but patient data may be burned into the image itself "
        "(e.g. ultrasound annotations) and name templates can put it into file names.",
    ),
    "medical_note": (
        "Program nie jest wyrobem medycznym – eksportowane obrazy nie są przeznaczone do celów diagnostycznych.",
        "This software is not a medical device – exported images are not intended for diagnostic use.",
    ),
    # --- Okno główne
    "app_subtitle": ("Konwersja obrazów DICOM do PNG, JPG, TIFF, GIF i MP4", "Convert DICOM images to PNG, JPG, TIFF, GIF and MP4"),
    "theme_dark": ("Ciemny motyw", "Dark theme"),
    "language": ("Język", "Language"),
    "btn_about": ("O programie", "About"),
    "version": ("Wersja {version}", "Version {version}"),
    "files_title": ("Pliki do konwersji", "Files to convert"),
    "no_files": ("Brak plików", "No files"),
    "btn_add_files": ("Dodaj pliki", "Add files"),
    "btn_add_folder": ("Dodaj folder", "Add folder"),
    "btn_open_disc": ("Otwórz płytę", "Open disc"),
    "btn_remove": ("Usuń", "Remove"),
    "btn_clear": ("Wyczyść listę", "Clear list"),
    "col_name": ("Nazwa pliku", "File name"),
    "col_modality": ("Modalność", "Modality"),
    "col_series": ("Seria", "Series"),
    "col_frames": ("Klatki", "Frames"),
    "col_dims": ("Wymiary", "Dimensions"),
    "col_size": ("Rozmiar", "Size"),
    "col_status": ("Status", "Status"),
    "col_location": ("Lokalizacja", "Location"),
    "status_pending": ("Oczekuje", "Pending"),
    "status_queued": ("W kolejce", "Queued"),
    "status_ok": ("Gotowe", "Done"),
    "status_ok_count": ("Gotowe ({images})", "Done ({images})"),
    "status_error": ("Błąd: {error}", "Error: {error}"),
    "status_cancelled": ("Anulowano", "Cancelled"),
    "menu_convert_selected": ("Konwertuj tylko zaznaczone", "Convert selected only"),
    "menu_show_result": ("Pokaż wynik", "Show result"),
    "menu_open_location": ("Otwórz lokalizację pliku", "Open file location"),
    "menu_remove": ("Usuń z listy", "Remove from list"),
    "drop_title": ("Przeciągnij tutaj pliki lub foldery DICOM", "Drag DICOM files or folders here"),
    "drop_title_no_dnd": ("Dodaj pliki lub foldery DICOM", "Add DICOM files or folders"),
    "drop_subtitle": ("albo kliknij, aby wybrać pliki z dysku  (Ctrl+O)", "or click to choose files from disk  (Ctrl+O)"),
    "drop_supported": (
        "Obsługiwane: .dcm, .dicom, .dic, .ima, pliki DICOM bez rozszerzenia oraz płyty z plikiem DICOMDIR",
        "Supported: .dcm, .dicom, .dic, .ima, DICOM files without an extension and discs with a DICOMDIR file",
    ),
    "output_folder": ("Folder docelowy", "Output folder"),
    "btn_choose": ("Wybierz…", "Browse…"),
    "btn_open": ("Otwórz", "Open"),
    "btn_cancel": ("Anuluj", "Cancel"),
    "btn_convert": ("Konwertuj", "Convert"),
    "btn_close": ("Zamknij", "Close"),
    "open_report": ("Otwórz raport", "Open report"),
    "status_ready": ("Dodaj pliki, aby rozpocząć", "Add files to get started"),
    "status_scanning": ("Wyszukiwanie plików DICOM…", "Looking for DICOM files…"),
    "status_added": ("Dodano {files}", "Added {files}"),
    "status_nothing_added": ("Nie znaleziono nowych plików DICOM", "No new DICOM files found"),
    "status_skipped": (" · pominięto {files} spoza formatu DICOM", " · skipped {files} that are not DICOM"),
    "status_reading_disc": ("Wczytywanie zawartości płyty…", "Reading the disc contents…"),
    "status_converting": ("Konwertowanie… {done} z {total}", "Converting… {done} of {total}"),
    "status_cancelling": ("Anulowanie… trwające pliki zostaną dokończone", "Cancelling… files in progress will be finished"),
    "status_cancelled_prefix": ("Anulowano · {summary}", "Cancelled · {summary}"),
    "status_report_failed": (" · nie udało się zapisać raportu: {error}", " · could not save the report: {error}"),
    "dialog_choose_files": ("Wybierz pliki DICOM", "Choose DICOM files"),
    "dialog_dicom_files": ("Pliki DICOM", "DICOM files"),
    "dialog_all_files": ("Wszystkie pliki (np. DICOM bez rozszerzenia)", "All files (e.g. DICOM without an extension)"),
    "dialog_choose_folder": ("Wybierz folder z plikami DICOM", "Choose a folder with DICOM files"),
    "dialog_choose_output": ("Wybierz folder docelowy", "Choose the output folder"),
    "dialog_open_disc": ("Otwórz płytę – wskaż plik DICOMDIR", "Open disc – choose the DICOMDIR file"),
    "ask_open_dicomdir": (
        "Folder „{folder}” zawiera plik DICOMDIR (płyta z badaniami).\n\n"
        "Otworzyć przegląd płyty, aby wybrać pacjentów, badania i serie?\n"
        "Wybierz „Nie”, aby dodać wszystkie pliki z folderu.",
        "The folder “{folder}” contains a DICOMDIR file (a disc with studies).\n\n"
        "Open the disc browser to choose patients, studies and series?\n"
        "Choose “No” to add all files from the folder.",
    ),
    "dicomdir_empty": ("Plik DICOMDIR nie zawiera żadnych obrazów.", "The DICOMDIR file contains no images."),
    "msg_choose_output": ("Wybierz folder docelowy.", "Choose an output folder."),
    "msg_output_error": ("Nie można utworzyć folderu docelowego:\n{error}", "Cannot create the output folder:\n{error}"),
    "msg_invalid_options": ("Nieprawidłowe ustawienia eksportu:\n{error}", "Invalid export settings:\n{error}"),
    "msg_output_missing": ("Folder docelowy jeszcze nie istnieje.", "The output folder does not exist yet."),
    "msg_close_converting": (
        "Konwersja jest w toku. Czy na pewno zamknąć program?",
        "A conversion is in progress. Do you really want to quit?",
    ),
    "msg_no_result": ("Zaznaczone pliki nie mają jeszcze wyników konwersji.", "The selected files have no conversion results yet."),
    "msg_fatal": ("Konwersja przerwana:\n{error}", "Conversion stopped:\n{error}"),
    "notify_title": ("DICOM Exporter – konwersja zakończona", "DICOM Exporter – conversion finished"),
    "notify_errors": ("Szczegóły błędów: kolumna „Status” i raport CSV.", "Error details: the “Status” column and the CSV report."),
    # --- Podgląd
    "tab_preview": ("Podgląd", "Preview"),
    "tab_tags": ("Tagi DICOM", "DICOM tags"),
    "tab_export": ("Eksport", "Export"),
    "preview_select": ("Wybierz plik z listy,\naby zobaczyć podgląd", "Select a file in the list\nto see a preview"),
    "preview_loading": ("Wczytywanie…", "Loading…"),
    "preview_error": ("Brak podglądu\n{error}", "No preview\n{error}"),
    "tip_zoom_out": ("Pomniejsz", "Zoom out"),
    "tip_zoom_in": ("Powiększ (kółko myszy)", "Zoom in (mouse wheel)"),
    "tip_fit": ("Dopasuj do okna (dwuklik)", "Fit to window (double-click)"),
    "tip_prev_frame": ("Poprzednia klatka (←)", "Previous frame (←)"),
    "tip_next_frame": ("Następna klatka (→)", "Next frame (→)"),
    "frame_counter": ("Klatka {current} / {total}", "Frame {current} / {total}"),
    "contrast_title": ("Jasność i kontrast", "Brightness and contrast"),
    "window_dicom": ("Okno z pliku DICOM (zalecane)", "Window from the DICOM file (recommended)"),
    "window_minmax": ("Pełny zakres jasności (min–max)", "Full brightness range (min–max)"),
    "window_custom": ("Własne okno", "Custom window"),
    "btn_window_from_file": ("Z pliku", "From file"),
    "tip_window_from_file": ("Ustaw suwaki na okno zapisane w pliku", "Set the sliders to the window stored in the file"),
    "window_center": ("Środek (C)", "Center (C)"),
    "window_width": ("Szerokość (W)", "Width (W)"),
    "window_hint": (
        "Wartości w jednostkach obrazu (dla CT: HU); presety są przeznaczone dla CT.\n"
        "W podglądzie: prawy przycisk + przeciąganie zmienia jasność i kontrast.",
        "Values in image units (HU for CT); presets are meant for CT.\n"
        "In the preview: right button + drag changes brightness and contrast.",
    ),
    "tip_play": ("Odtwarzaj / zatrzymaj (Spacja) – tempo jak „Klatki na sekundę” w eksporcie", "Play / pause (Space) – speed as “Frames per second” in Export"),
    "series_counter": ("Obraz {current} / {total} serii", "Image {current} / {total} of series"),
    "masks_title": ("Maskowanie napisów", "Mask burned-in text"),
    "masks_hint": (
        "Zaczernione obszary są stosowane do wszystkich eksportowanych plików – także do anonimizowanych kopii DICOM.",
        "Blacked-out areas apply to all exported files – including anonymized DICOM copies.",
    ),
    "masks_none": ("brak masek", "no masks"),
    "btn_mask_top": ("Górny pasek", "Top band"),
    "btn_mask_bottom": ("Dolny pasek", "Bottom band"),
    "btn_mask_draw": ("Rysuj", "Draw"),
    "btn_mask_clear": ("Wyczyść", "Clear"),
    "tip_mask_top": ("Zamaskuj górne 10% obrazu", "Mask the top 10% of the image"),
    "tip_mask_bottom": ("Zamaskuj dolne 10% obrazu", "Mask the bottom 10% of the image"),
    "tip_mask_draw": ("Przeciągnij w podglądzie, aby zaznaczyć obszar do zaczernienia", "Drag in the preview to select an area to black out"),
    "tip_mask_clear": ("Usuń wszystkie maski", "Remove all masks"),
    "preset_brain": ("Mózg", "Brain"),
    "preset_soft_tissue": ("Tkanki miękkie", "Soft tissue"),
    "preset_lung": ("Płuca", "Lung"),
    "preset_bone": ("Kości", "Bone"),
    "preset_mediastinum": ("Śródpiersie", "Mediastinum"),
    "preset_liver": ("Wątroba", "Liver"),
    # --- Tagi
    "tags_search": ("Szukaj w tagach (tag, nazwa lub wartość)", "Search tags (tag, name or value)"),
    "tag_col_tag": ("Tag", "Tag"),
    "tag_col_name": ("Nazwa", "Name"),
    "tag_col_value": ("Wartość", "Value"),
    "tags_hint": ("Dwuklik kopiuje wartość do schowka", "Double-click copies the value to the clipboard"),
    "tags_no_file": ("Wybierz plik z listy, aby zobaczyć jego tagi", "Select a file in the list to see its tags"),
    "tags_no_match": ("Brak tagów pasujących do wyszukiwania", "No tags match the search"),
    "tag_copied": ("Skopiowano wartość do schowka", "Value copied to the clipboard"),
    # --- Eksport
    "export_mode": ("Tryb eksportu", "Export mode"),
    "export_images": ("Osobne obrazy", "Separate images"),
    "export_gif": ("Seria jako animacja GIF", "Series as a GIF animation"),
    "export_mp4": ("Seria jako wideo MP4", "Series as an MP4 video"),
    "export_montage": ("Seria jako kolaż miniatur", "Series as a contact sheet"),
    "export_hint_images": ("Każda klatka zostanie zapisana jako osobny obraz.", "Every frame is saved as a separate image."),
    "export_hint_gif": (
        "Pliki z tej samej serii (i klatki pliku wieloklatkowego) zostaną połączone w jedną animację.",
        "Files from the same series (and frames of a multi-frame file) are combined into one animation.",
    ),
    "export_hint_mp4": (
        "Pliki z tej samej serii (i klatki pliku wieloklatkowego) zostaną połączone w jedno wideo.",
        "Files from the same series (and frames of a multi-frame file) are combined into one video.",
    ),
    "export_hint_montage": (
        "Każda seria trafi na jeden obraz z miniaturami (maks. 100, równomiernie wybranych).",
        "Each series is placed on one image with thumbnails (up to 100, evenly sampled).",
    ),
    "fps": ("Klatki na sekundę", "Frames per second"),
    "image_format": ("Format obrazu", "Image format"),
    "bit_depth": ("Głębia bitowa", "Bit depth"),
    "bit_depth_hint": (
        "16 bitów: tylko PNG i TIFF, obrazy w skali szarości – zachowuje tysiące odcieni zamiast 256.",
        "16-bit: PNG and TIFF only, grayscale images – keeps thousands of shades instead of 256.",
    ),
    "quality": ("Jakość (JPG, JPEG, WebP)", "Quality (JPG, JPEG, WebP)"),
    "resize": ("Rozmiar", "Size"),
    "resize_none": ("Oryginalny", "Original"),
    "resize_fit": ("Zmniejsz do maksymalnych wymiarów", "Shrink to maximum dimensions"),
    "resize_scale": ("Skaluj procentowo", "Scale by percent"),
    "names": ("Nazwy plików", "File names"),
    "folders": ("Foldery", "Folders"),
    "btn_fields": ("Pola", "Fields"),
    "layout_flat": ("Wszystko w jednym folderze", "Everything in one folder"),
    "layout_source": ("Jak w dodanych folderach", "Like the added folders"),
    "layout_template": ("Według szablonu (np. badanie → seria)", "From a template (e.g. study → series)"),
    "example": ("Przykład: {path}", "Example: {path}"),
    "example_none": ("Przykład nazwy pojawi się po wybraniu pliku z listy", "A name example appears after selecting a file"),
    "options": ("Opcje", "Options"),
    "switch_all_frames": ("Wszystkie klatki z plików wieloklatkowych", "All frames of multi-frame files"),
    "switch_overwrite": ("Nadpisuj istniejące pliki", "Overwrite existing files"),
    "switch_report": ("Zapisz raport CSV po konwersji", "Save a CSV report after conversion"),
    "field_file": ("nazwa pliku źródłowego", "source file name"),
    "field_frame": ("numer klatki", "frame number"),
    "field_Modality": ("modalność (CT, MR…)", "modality (CT, MR…)"),
    "field_SeriesNumber": ("numer serii", "series number"),
    "field_InstanceNumber": ("numer obrazu", "image number"),
    "field_SeriesDescription": ("opis serii", "series description"),
    "field_StudyDate": ("data badania", "study date"),
    "field_StudyDescription": ("opis badania", "study description"),
    "field_BodyPartExamined": ("badana część ciała", "body part examined"),
    "field_PatientID": ("ID pacjenta (dane osobowe!)", "patient ID (personal data!)"),
    "profile": ("Profil eksportu", "Export profile"),
    "profile_custom": ("Własne ustawienia", "Custom settings"),
    "tip_save_profile": ("Zapisz bieżące ustawienia jako profil", "Save the current settings as a profile"),
    "tip_delete_profile": ("Usuń wybrany profil użytkownika", "Delete the selected user profile"),
    "profile_name_prompt": ("Nazwa nowego profilu:", "Name of the new profile:"),
    "profile_delete_confirm": ("Usunąć profil „{name}”?", "Delete the profile “{name}”?"),
    "export_dicom": ("Anonimizowane kopie DICOM", "Anonymized DICOM copies"),
    "export_hint_dicom": (
        "Każdy plik zostanie zapisany jako kopia DICOM bez danych osobowych (ustawienia obrazu nie są używane).",
        "Every file is saved as a DICOM copy without personal data (image settings are not used).",
    ),
    "overlays": ("Nakładki na obraz", "Image overlays"),
    "switch_overlay_scale": ("Podziałka w milimetrach", "Scale bar in millimetres"),
    "switch_overlay_info": ("Informacje o obrazie (seria, numer, data)", "Image information (series, number, date)"),
    "switch_overlay_patient": ("Dane pacjenta (imię i nazwisko, ID)", "Patient data (name, ID)"),
    "overlay_hint": (
        "Nakładki są widoczne w podglądzie. Podziałka wymaga informacji o rozmiarze piksela w pliku.",
        "Overlays are shown in the preview. The scale bar needs pixel size information in the file.",
    ),
    "anonymization": ("Anonimizacja", "Anonymization"),
    "anonymize_hint": (
        "Usuwane są dane pacjenta, lekarzy i placówki oraz tagi prywatne; identyfikatory są zamieniane spójnie, "
        "więc serie pozostają seriami. Maski z karty Podgląd zostaną wypalone w obraz. "
        "Uwaga: nazwy plików i folderów źródłowych (pola {file}, układ „jak w dodanych folderach”) mogą zawierać dane osobowe.",
        "Patient, physician and institution data and private tags are removed; identifiers are replaced consistently, "
        "so series stay series. Masks from the Preview tab are burned into the image. "
        "Note: source file and folder names ({file} field, “like the added folders” layout) may contain personal data.",
    ),
    "anonymize_name": ("Nazwa pacjenta w kopii", "Patient name in the copy"),
    "switch_keep_dates": ("Zachowaj daty badań", "Keep study dates"),
    "shell_open": ("Otwórz w DICOM Exporter", "Open in DICOM Exporter"),
    "shell_convert": ("Konwertuj do PNG (obok pliku)", "Convert to PNG (next to the file)"),
    "switch_context_menu": ("Polecenia w menu kontekstowym Eksploratora", "Commands in the Explorer context menu"),
    "context_menu_hint": (
        "„Otwórz w DICOM Exporter” i „Konwertuj do PNG” dla plików .dcm/.dicom i folderów (w Windows 11 pod "
        "„Pokaż więcej opcji”). Po przeniesieniu programu w inne miejsce włącz ponownie.",
        "“Open in DICOM Exporter” and “Convert to PNG” for .dcm/.dicom files and folders (in Windows 11 under "
        "“Show more options”). After moving the program, turn it on again.",
    ),
    "context_menu_error": ("Nie udało się zmienić menu kontekstowego:\n{error}", "Could not change the context menu:\n{error}"),
    "quick_title": ("Szybka konwersja do PNG", "Quick conversion to PNG"),
    "quick_done": ("Obrazy PNG zapisano obok plików źródłowych.", "PNG images were saved next to the source files."),
    "btn_show_files": ("Pokaż pliki", "Show files"),
    "update_available": ("Dostępna nowa wersja {version} – pobierz", "New version {version} available – download"),
    "switch_check_updates": (
        "Sprawdzaj aktualizacje przy uruchomieniu (połączenie z GitHubem)",
        "Check for updates at startup (connects to GitHub)",
    ),
    # --- Okna dialogowe
    "about_title": ("O programie {app}", "About {app}"),
    "about_description": (
        "Konwersja obrazów DICOM do PNG, JPG, TIFF, WebP, BMP, GIF i MP4 – pojedynczo lub wsadowo.",
        "Convert DICOM images to PNG, JPG, TIFF, WebP, BMP, GIF and MP4 – one by one or in batches.",
    ),
    "tab_general": ("Ogólne", "General"),
    "tab_features": ("Możliwości", "Features"),
    "tab_shortcuts": ("Skróty klawiszowe", "Keyboard shortcuts"),
    "about_author": ("Autor", "Author"),
    "about_email": ("E-mail", "E-mail"),
    "about_privacy": ("Prywatność", "Privacy"),
    "about_disclaimer": ("Zastrzeżenie", "Disclaimer"),
    "dicomdir_title": ("Płyta DICOM", "DICOM disc"),
    "dicomdir_heading": ("Wybierz, co dodać z płyty", "Choose what to add from the disc"),
    "dicomdir_subtitle": (
        "{path}\nZaznacz pacjentów, badania lub serie (Ctrl lub Shift – wiele naraz).",
        "{path}\nSelect patients, studies or series (Ctrl or Shift – several at once).",
    ),
    "dicomdir_col_item": ("Pacjent / badanie / seria", "Patient / study / series"),
    "dicomdir_col_images": ("Obrazy", "Images"),
    "dicomdir_col_date": ("Data", "Date"),
    "dicomdir_unknown_patient": ("Nieznany pacjent", "Unknown patient"),
    "dicomdir_study": ("Badanie", "Study"),
    "dicomdir_series": ("Seria", "Series"),
    "dicomdir_selected": ("Zaznaczono: {files}", "Selected: {files}"),
    "btn_select_all": ("Zaznacz wszystko", "Select all"),
    "btn_select_none": ("Odznacz", "Select none"),
    "btn_add_selected": ("Dodaj zaznaczone", "Add selected"),
}
