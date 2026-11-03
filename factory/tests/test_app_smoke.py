"""Smoke test of the factory window (spec 4: construct it under xvfb when there is one; skip otherwise).

Skips cleanly when tkinter isn't installed (the cloud Python) or there is no screen. On Linux without $DISPLAY it
starts its own Xvfb when that program is installed. The back end is faked; nothing is built or signed for real
beyond a throwaway key in a temporary folder.
"""

import datetime as dt
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from factory import build as B                                       # noqa: E402
from factory.build import FactorySettings                            # noqa: E402
from factory.controller import Backend, Controller, Notice          # noqa: E402

PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
           b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND"
           b"\xaeB`\x82")


@pytest.fixture(scope="module")
def display():
    if os.name == "nt" or os.environ.get("DISPLAY"):
        yield
        return
    xvfb = shutil.which("Xvfb")
    if not xvfb:
        pytest.skip("no screen and no Xvfb")
    num = 90 + os.getpid() % 100
    proc = subprocess.Popen([xvfb, f":{num}", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"] = f":{num}"
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                tk.Tk().destroy()
                break
            except tk.TclError:
                if time.monotonic() > deadline or proc.poll() is not None:
                    pytest.skip("Xvfb didn't start")
                time.sleep(0.2)
        yield
    finally:
        os.environ.pop("DISPLAY", None)
        proc.terminate()
        proc.wait(5)


@pytest.fixture
def root(display):
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no screen")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def controller(tmp_path):
    repo = tmp_path / "repo"
    (repo / "hub" / "simtelemetry").mkdir(parents=True)
    video = tmp_path / "video"
    video.mkdir()
    for name in B.VIDEO_FILES.values():
        (video / name).write_bytes(b"video")
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"MZ")
    settings = FactorySettings(shipments=tmp_path / "Shipments", edge=edge, keys_dir=tmp_path / "keys",
                               repo_root=repo, video_dir=video)
    opened = []
    return Controller(settings, settings_file=tmp_path / "cfg" / "settings.json", backend=Backend(),
                      opener=opened.append, today=lambda: dt.date(2026, 11, 3))


def pump(root, n=5):
    for _ in range(n):
        root.update()


def test_window_builds_and_edits_a_cafe(root, controller, tmp_path):
    from factory.app import FactoryApp, MessageDialog, RebuildDialog, SettingsDialog, UpgradeDialog
    app = FactoryApp(root, controller)
    pump(root)
    assert app.banner.winfo_manager() == "pack"                  # no keys yet: the red banner shows
    assert app.buttons["build"].instate(["disabled"])

    app.on_new()
    pump(root)
    app.vars["name"].set("Apex Lounge")
    app.vars["rigs"].set("6")
    pump(root)
    assert controller.profile.name == "Apex Lounge" and controller.profile.rigs == 6
    assert app.vars["price"].get() == "30000"                    # the list price followed the rigs
    assert app.rig_entries[5][1].winfo_manager() == "grid" and app.rig_entries[6][1].winfo_manager() == ""
    app.vars["variant"].set("unbranded")
    pump(root)
    assert app.vars["price"].get() == "" and "needs a price" in app.problem_labels["price_inr"].cget("text")
    assert app.nb.tab(3, "text") == "Branding & price (1 to fix)"
    app.vars["price"].set("45,000")
    app.feature_vars["challenges"].set(False)
    app.vars["wifi_on"].set(True)
    pump(root)
    assert "Wi-Fi name" in app.problem_labels["wifi"].cget("text")
    app.vars["ssid"].set("Apex Guest")
    app.vars["wifi_pw"].set("racing123")
    logo = tmp_path / "logo.png"
    logo.write_bytes(PNG_1PX)
    controller.choose_logo(logo)
    app.fill_form()
    app.on_save()
    pump(root)
    assert not controller.dirty and controller.path is not None
    assert app._logo_image is not None
    assert app.listbox.get(0).startswith("Apex Lounge")

    controller.setup_keys()
    usb = tmp_path / "usb"
    usb.mkdir()
    controller.copy_key_to(usb)
    app.refresh_state()
    pump(root)
    assert app.banner.winfo_manager() == ""
    assert not app.buttons["build"].instate(["disabled"])

    dialogs = [
        app.show_notice(Notice("error", "Build package", "The installer couldn't be made.", details="log")),
        app.show_notice(Notice("upgrade", "Upgrade code ready", "Send this code.", code="PW1-abc", folder=tmp_path)),
        app.show_notice(Notice("rebuild", "Rebuild all", "1 of 1 built.", rows=[("Apex", "Built", "Built.", "x")])),
        SettingsDialog(app),
    ]
    pump(root)
    assert isinstance(dialogs[0], MessageDialog) and isinstance(dialogs[1], UpgradeDialog)
    assert isinstance(dialogs[2], RebuildDialog)
    dialogs[1].copy("PW1-abc")
    assert root.clipboard_get() == "PW1-abc"
    for d in dialogs:
        d.destroy()
    app._tick()
    pump(root)
