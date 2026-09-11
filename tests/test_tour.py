from PIL import Image

from dicom_exporter import tour
from dicom_exporter.i18n import STRINGS

AREA = (0, 0, 1360, 900)
BUBBLE = (380, 210)


def test_every_step_has_texts():
    for step in tour.STEPS:
        assert f"tour_{step.key}_title" in STRINGS and f"tour_{step.key}_text" in STRINGS
    assert tour.STEPS[0].targets is None  # powitanie bez strzałki


def test_bubble_is_placed_next_to_the_target_and_inside_the_window():
    targets = [(40, 160, 800, 720), (840, 100, 1320, 480), (560, 780, 800, 830), (1180, 10, 1340, 50), (20, 20, 300, 60)]
    for target in targets:
        x, y, side = tour.place_bubble(target, BUBBLE, AREA, gap=64, margin=16)
        bubble = (x, y, x + BUBBLE[0], y + BUBBLE[1])
        assert x >= 16 and y >= 16 and bubble[2] <= AREA[2] - 16 and bubble[3] <= AREA[3] - 16
        assert side in ("below", "above", "right", "left")
        assert tour.intersect(bubble, target) is None, (target, side)
    assert tour.place_bubble(None, BUBBLE, AREA, gap=64, margin=16) == ((1360 - 380) // 2, (900 - 210) // 2, "center")


def test_arrow_leads_from_the_bubble_to_the_target():
    target = (40, 160, 800, 720)
    x, y, side = tour.place_bubble(target, BUBBLE, AREA, gap=88, margin=16)
    panel = (x, y, x + BUBBLE[0], y + BUBBLE[1])
    start, _control, end = tour.arrow_path(panel, target, side, gap=8)
    assert side == "right"
    assert start[0] < panel[0] and target[2] < end[0] < start[0]
    assert tour.arrow_path(panel, target, "center", gap=8) is None


def test_scene_dims_everything_except_the_spotlight():
    snapshot = Image.new("RGB", (400, 300), "white")
    scene = tour.render_scene(
        snapshot,
        (100, 100, 200, 160),
        (240, 60, 380, 200),
        ((236, 130), (220, 100), (206, 130)),
        dark=False,
        panel_color="#fafafa",
        border_color="#b9c0ca",
        scale=1.0,
    )
    assert scene.size == snapshot.size
    assert scene.getpixel((150, 130)) == (255, 255, 255)  # podświetlony element
    assert max(scene.getpixel((20, 280))) < 130  # przyciemnione tło
    assert scene.getpixel((310, 130)) == (250, 250, 250)  # dymek
