"""Treści okna „O programie”: możliwości programu i skróty klawiszowe."""

from .i18n import t


def capabilities() -> list[tuple[str, str]]:
    return [
        (t(key), t(f"{key}_text"))
        for key in ("cap_input", "cap_compression", "cap_images", "cap_output", "cap_contrast", "cap_processing")
    ]


def shortcuts() -> list[tuple[str, str]]:
    return [
        ("Ctrl+O", t("sc_add")),
        ("Delete", t("sc_delete")),
        ("Ctrl+A", t("sc_select_all")),
        ("F1", t("sc_about")),
        ("← / →", t("sc_frames")),
        (t("sc_ctrl_wheel_key"), t("sc_frames")),
        (t("sc_space_key"), t("sc_play")),
        (t("sc_wheel"), t("sc_zoom")),
        (t("sc_right_drag_key"), t("sc_window_drag")),
        (t("sc_double_click"), t("sc_fit")),
        ("Ctrl+Tab", t("sc_tab")),
        ("Esc", t("sc_escape")),
    ]


def privacy_note() -> str:
    return t("privacy_note")


def medical_note() -> str:
    return t("medical_note")
