"""Punkt startowy aplikacji okienkowej.

`main.py --quick-png PLIK_LUB_FOLDER...` – szybka konwersja do PNG obok plików (menu kontekstowe Eksploratora).
"""

import sys

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--quick-png":
        from dicom_exporter.quick import quick_convert

        sys.exit(quick_convert(sys.argv[2:]))

    from dicom_exporter.gui import main

    main()
