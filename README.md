# DICOM Exporter

Aplikacja do konwersji obrazów DICOM do **PNG, JPG, JPEG, TIFF, WebP i BMP**, eksportu całych serii jako
**animacja GIF, wideo MP4 lub kolaż miniatur** oraz tworzenia **anonimizowanych kopii DICOM** – pojedynczo lub wsadowo.
Interfejs po polsku i angielsku.

## Funkcje

**Dodawanie plików**
- wiele plików naraz (`Ctrl+O`), całe foldery (rekurencyjnie) i przeciąganie plików/folderów do okna,
- okno wyboru pokazuje domyślnie tylko pliki DICOM; pliki bez rozszerzenia (np. `IM00001`) – po przełączeniu filtra,
- pliki spoza formatu DICOM są rozpoznawane po zawartości i pomijane,
- **płyty CD/DVD z plikiem DICOMDIR**: przycisk „Otwórz płytę” (lub dodanie folderu płyty) pokazuje drzewo
  pacjent → badanie → seria, z którego wybierasz, co dodać.

**Lista plików**
- kolumny: nazwa, status, modalność, seria, liczba klatek, wymiary, rozmiar i lokalizacja; sortowanie kliknięciem nagłówka,
- menu pod prawym przyciskiem: „Konwertuj tylko zaznaczone”, „Pokaż wynik”, „Otwórz lokalizację pliku”, „Usuń z listy”,
- dwuklik na przekonwertowanym pliku otwiera wynik.

**Podgląd i tagi**
- powiększanie kółkiem myszy, przesuwanie przeciąganiem, dopasowanie do okna dwuklikiem,
- **jasność i kontrast pod prawym przyciskiem myszy** (w pionie jasność, w poziomie kontrast),
- przewijanie klatek i **obrazów serii** strzałkami ← →, suwakiem lub `Ctrl` + kółko myszy,
- **odtwarzanie serii** (przycisk ▶ lub `Spacja`) w tempie ustawionym jako „Klatki na sekundę”,
- karta „Tagi DICOM”: pełne drzewo tagów z wyszukiwarką; dwuklik kopiuje wartość.

**Jasność i kontrast**
- okno zapisane w pliku (Window Center/Width, VOI LUT, Rescale – także Enhanced CT/MR), pełny zakres min–max
  lub **własne okno** z suwakami i podglądem na żywo,
- presety CT: mózg, tkanki miękkie, płuca, kości, śródpiersie, wątroba.

**Eksport**
- **profile eksportu**: gotowe („Prezentacja”, „Analiza 16-bit”, „E-mail”, „Anonimizowane kopie DICOM”, „Wideo serii”)
  oraz własne profile zapisywane przyciskiem obok listy,
- formaty: PNG, JPG, JPEG, TIFF, WebP, BMP; jakość dla JPG/JPEG/WebP,
- **PNG i TIFF 16-bitowe** – obrazy w skali szarości zachowują tysiące odcieni zamiast 256,
- zmiana rozmiaru: zmniejszenie do maksymalnych wymiarów albo skalowanie procentowe,
- **nakładki na obraz**: podziałka w milimetrach, informacje o obrazie (seria, numer, data) i – opcjonalnie – dane pacjenta,
- **szablony nazw plików** z danych DICOM, np. `{Modality}_{SeriesNumber:03}_{InstanceNumber:04}`
  (także polskie aliasy: `{Modalność}_{Seria}_{NrObrazu}`),
- układ folderów: jeden folder, jak w źródle albo **według szablonu**, np. `{StudyDate}_{StudyDescription}/S{SeriesNumber}_{SeriesDescription}`,
- tryby serii: pliki z tej samej serii (lub klatki pliku wieloklatkowego) łączone w **GIF**, **MP4** albo **kolaż miniatur**,
- **raport CSV** po konwersji (co się udało, co nie i dlaczego) – otwiera się poprawnie w Excelu.

**Prywatność**
- **anonimizowane kopie DICOM**: usuwane są dane pacjenta, lekarzy, placówki i tagi prywatne; identyfikatory
  (pacjent, badanie, seria, obraz) zamieniane są na pseudonimy spójne w obrębie jednej konwersji, więc serie
  pozostają seriami; daty można zachować lub wyczyścić,
- **maskowanie napisów wpalonych w obraz** (np. dane pacjenta na zdjęciach USG): gotowy górny/dolny pasek albo
  dowolne prostokąty rysowane myszą w podglądzie; maski działają dla wszystkich formatów, także kopii DICOM.

**Wygoda**
- postęp widoczny na ikonie aplikacji na pasku zadań, powiadomienie Windows i miganie paska zadań po zakończeniu,
- motyw jasny/ciemny, język polski/angielski (zmiana bez utraty listy plików), zapamiętywanie ustawień,
- równoległa konwersja w kilku wątkach, anulowanie, błędny plik nie przerywa partii.

## Pobieranie i instalacja

Gotowe wersje są w zakładce [Releases](https://github.com/facior/DicomExporter/releases):

- **`DicomExporter-X.Y.Z-setup.exe`** – instalator (bez uprawnień administratora); dodaje skrót w menu Start
  i – opcjonalnie – polecenia w menu kontekstowym Eksploratora dla plików `.dcm`/`.dicom` i folderów:
  „Otwórz w DICOM Exporter” oraz „Konwertuj do PNG (obok pliku)”,
- **`DicomExporter-X.Y.Z-portable.zip`** – wersja przenośna: rozpakuj i uruchom `DicomExporter.exe`.

W folderze programu jest też `dicom-exporter-cli.exe` – wersja do wiersza poleceń (opcje opisane niżej).
Przy uruchomieniu program sprawdza, czy na GitHubie jest nowsza wersja – można to wyłączyć w oknie „O programie”.

## Uruchomienie ze źródeł (Windows)

Wymagany Python 3.10 lub nowszy. Kliknij dwukrotnie **`run.bat`** – przy pierwszym uruchomieniu skrypt utworzy
środowisko `.venv` i zainstaluje zależności. Pliki lub foldery można też upuścić bezpośrednio na `run.bat`.

Ręcznie:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Ustawienia (także maski i własne profile) są zapisywane w `%APPDATA%\DicomExporter\settings.json`.

## Pola szablonów nazw

| Pole | Znaczenie |
| --- | --- |
| `{file}` / `{Plik}` | nazwa pliku źródłowego |
| `{frame}` / `{Klatka}` | numer klatki (dopisywany automatycznie przy wielu klatkach) |
| `{Modality}` / `{Modalność}` | modalność (CT, MR…) |
| `{SeriesNumber}` / `{Seria}` | numer serii |
| `{InstanceNumber}` / `{NrObrazu}` | numer obrazu |
| `{StudyDate}`, `{StudyDescription}`, `{SeriesDescription}`, `{BodyPartExamined}` | data i opisy badania/serii |
| dowolne słowo kluczowe DICOM | np. `{PatientID}`, `{AccessionNumber}` |

Po dwukropku można podać format liczby: `{InstanceNumber:04}` → `0007`. Brakujące wartości są zastępowane przez `NA`.
W anonimizowanych kopiach pola pacjenta przyjmują wartości pseudonimów.

## Wiersz poleceń

```bat
.venv\Scripts\python -m dicom_exporter D:\Badania -o D:\Eksport --profile presentation --mask-top 10
.venv\Scripts\python -m dicom_exporter D:\Badania -o D:\Anonimowe --export dicom --mask-top 8 --anon-name BADANIE
.venv\Scripts\python -m dicom_exporter D:\Badania -o D:\Eksport -f png --bit-depth 16 --preset lung ^
    --name-template "{Modality}_{SeriesNumber:03}_{InstanceNumber:04}" --layout template --report
```

| Opcja | Znaczenie |
| --- | --- |
| `-o, --output` | folder docelowy (wymagany) |
| `--profile` | `presentation`, `analysis16`, `email`, `anonymized_dicom`, `cine_mp4` (jawne opcje mają pierwszeństwo) |
| `-f, --format` | `png` (domyślnie), `jpg`, `jpeg`, `tiff`, `webp`, `bmp` |
| `--bit-depth` | `8` lub `16` (PNG, TIFF) |
| `-q, --quality` | jakość JPG/WebP 1–100 (domyślnie 95) |
| `--window` | `dicom` (domyślnie), `minmax`, `custom` (z `--center` i `--width`) |
| `--preset` | `brain`, `soft_tissue`, `lung`, `bone`, `mediastinum`, `liver` |
| `--max-size` / `--scale` | zmniejsz do np. `1024x768` / skaluj o procent |
| `--name-template` | szablon nazwy pliku |
| `--layout` | `flat`, `source` (domyślnie), `template` (z `--folder-template`) |
| `--export` | `images` (domyślnie), `gif`, `mp4`, `montage`, `dicom` (anonimizowane kopie) |
| `--fps` | klatki na sekundę dla GIF/MP4 |
| `--mask X0,Y0,X1,Y1` | zamaskuj prostokąt podany jako ułamki wymiarów (można powtarzać) |
| `--mask-top` / `--mask-bottom` | zamaskuj górny / dolny pasek o wysokości w % |
| `--overlay-scale`, `--overlay-info`, `--overlay-patient` | nakładki: podziałka, informacje o obrazie, dane pacjenta |
| `--anon-name`, `--keep-dates` | nazwa pacjenta i zachowanie dat w anonimizowanych kopiach |
| `--first-frame` | z plików wieloklatkowych tylko pierwsza klatka |
| `--overwrite` | nadpisuj istniejące pliki |
| `--report` | zapisz raport CSV |
| `--lang` | `pl` (domyślnie) lub `en` |
| `-j, --workers` | liczba wątków |

Jako wejście można podać także plik `DICOMDIR` – zostaną dodane wszystkie obrazy z płyty.
Kod wyjścia: `0` – sukces, `1` – brak plików lub błędne opcje, `2` – część plików się nie przekonwertowała.

## Uwagi

- Anonimizacja realizuje uproszczony podstawowy profil poufności DICOM (PS3.15, zał. E). Przed udostępnieniem danych
  sprawdź wynik – napisy wpalone w obraz trzeba zamaskować, a nazwy plików i folderów źródłowych mogą zawierać dane osobowe.
- Zwykłe obrazy wynikowe nie zawierają metadanych DICOM, ale szablony nazw i nakładka „Dane pacjenta” mogą umieścić
  dane osobowe w nazwach plików lub na obrazie.
- Program nie jest wyrobem medycznym – eksportowane obrazy nie są przeznaczone do celów diagnostycznych.
- Powiadomienie po konwersji pojawi się tylko wtedy, gdy powiadomienia są włączone w ustawieniach Windows.

## Struktura projektu

```
main.py                        start aplikacji okienkowej
dicom_exporter/converter.py    konwersja: piksele, okna, maski, rozmiar, zapis, serie, kopie DICOM
dicom_exporter/anonymize.py    anonimizacja zbiorów danych DICOM
dicom_exporter/overlays.py     nakładki: podziałka i opisy na obrazie
dicom_exporter/profiles.py     gotowe profile eksportu
dicom_exporter/naming.py       szablony nazw plików i folderów
dicom_exporter/dicominfo.py    kolumny listy, tagi DICOM, odczyt DICOMDIR
dicom_exporter/report.py       raport CSV
dicom_exporter/i18n.py         tłumaczenia (PL/EN)
dicom_exporter/gui.py          główne okno
dicom_exporter/preview.py      podgląd: powiększanie, okno pod prawym przyciskiem, rysowanie masek
dicom_exporter/dialogs.py      okna „O programie” i wyboru z płyty
dicom_exporter/widgets.py      motyw, ikony i pomocnicze widżety
dicom_exporter/winshell.py     pasek zadań, powiadomienia, Eksplorator
dicom_exporter/cli.py          wiersz poleceń
dicom_exporter/quick.py        szybka konwersja do PNG z menu kontekstowego Eksploratora
dicom_exporter/updates.py      sprawdzanie nowych wersji na GitHubie
cli_main.py                    start wersji konsolowej (dicom-exporter-cli.exe)
packaging/                     budowanie .exe (PyInstaller), instalator (Inno Setup), ikona
.github/workflows/             testy i automatyczne wydania (GitHub Actions)
tests/                         testy (pytest)
```

Testy: `.venv\Scripts\pip install pytest` i `.venv\Scripts\python -m pytest tests`.

## Budowanie i wydania

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python packaging\build.py              :: dist\DicomExporter + wersja przenośna ZIP
.venv\Scripts\python packaging\build.py --installer  :: dodatkowo instalator (wymaga Inno Setup 6)
```

Wydania tworzą się automatycznie na GitHubie (GitHub Actions): zmień `__version__` w `dicom_exporter/__init__.py`,
zrób commit i wypchnij tag, np. `git tag v1.1.0` oraz `git push origin v1.1.0`. Workflow uruchomi testy, zbuduje
instalator i wersję przenośną i dołączy je do wydania. Testy uruchamiają się też przy każdym pushu na `main`.

## Autor

**Łukasz Kubieniec** – [lukasz.kubieniec00@gmail.com](mailto:lukasz.kubieniec00@gmail.com) · [GitHub](https://github.com/facior)

Dane autora są zapisane w `dicom_exporter/__init__.py` i wyświetlane w stopce okna oraz w oknie „O programie”
(przycisk w nagłówku lub klawisz `F1`). Okno ma karty: **Ogólne** (autor, kontakt, prywatność, zastrzeżenie),
**Możliwości** oraz **Skróty klawiszowe**.
