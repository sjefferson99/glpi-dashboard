"""scripts/demo.py's `shot` still finds what it shoots, so the README images can be retaken after a UI change."""
import importlib.util
import struct
from pathlib import Path

import httpx
import pytest

from demo_glpi import demo_dataset

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "demo.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def demo_data(base_url, fake_glpi):
    """The session's app, re-read from the demo dataset; the `dashboard` fixture puts the test data back."""
    fake_glpi.data = demo_dataset()
    r = httpx.post(base_url + "/api/refresh", timeout=10)
    assert r.status_code == 200 and r.json()["error"] is None


def _png_size(path):
    """Width and height from a PNG's IHDR chunk."""
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", head[16:24])


@pytest.mark.parametrize("tab", ["Summary", "In flight", "Recurring changes", "CMDB", "Risk analysis",
                                 "Record explorer"])
def test_shot_of_a_tab_is_the_whole_page(demo, browser, base_url, demo_data, tmp_path, tab):
    out = tmp_path / "shots" / "tab.png"
    demo.shoot(browser, base_url, out, tab=tab)
    width, height = _png_size(out)
    assert width == 1280 and height >= 800


@pytest.mark.parametrize("link", ["#list=high-priority", "#search=vpn&closed=1"])
def test_shot_of_a_dialog_is_cropped_to_it(demo, browser, base_url, demo_data, tmp_path, link):
    out = tmp_path / "dialog.png"
    demo.shoot(browser, base_url, out, link=link, element="#list")
    width, height = _png_size(out)
    assert 600 < width < 1280 and 100 < height < 800
