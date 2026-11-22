import threading

import pystray
from PIL import Image, ImageDraw, ImageFont

from battery_checker.providers.steelseries import SteelSeriesProvider

REFRESH_SECONDS = 60
ICON_SIZE = 64


def pick_color(level):
    if level is None:
        return (120, 120, 120)
    if level <= 20:
        return (220, 20, 20)
    if level <= 50:
        return (230,160,30)
    return (40, 170, 70)


def make_icon(level):
    text = "?" if level is None else str(level)

    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, ICON_SIZE - 1, ICON_SIZE - 1), radius=12, fill=pick_color(level))

    font_size = 30 if len(text) >= 3 else 42
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except OSError:
        font = ImageFont.load_default(size=font_size)

    draw.text((ICON_SIZE / 2, ICON_SIZE / 2), text, font=font, fill="white", anchor="mm")
    return img


class TrayApp:
    def __init__(self):
        self.provider = SteelSeriesProvider()
        self.stop_event = threading.Event()
        self.icon = pystray.Icon(
            "batteryChecker",
            icon=make_icon(None),
            title="Battery Checker",
            menu=pystray.Menu(
                pystray.MenuItem("Refresh", self.on_refresh),
                pystray.MenuItem("Quit", self.on_quit),
                ),
        )

    def update(self):
        devices = self.provider.scan()

        if not devices:
            self.icon.icon = make_icon(None)
            self.icon.title = "No SteelSeries devices found."
            return

        d = devices[0]
        self.icon.icon = make_icon(d.level)
        if d.level is None:
            self.icon.tittle = f"{d.name}: Battery level unknown"
        else:
            charging = "charging" if d.charging else ""
            self.icon.title = f"{d.name}: {d.level}% {charging}"

    def loop(self):
        while not self.stop_event.wait(REFRESH_SECONDS):
            self.update()
            self.stop_event.wait(REFRESH_SECONDS)

    def on_refresh(self, icon, item):
        self.update()

    def on_quit(self, icon, item):
        self.stop_event.set()
        icon.stop()

    def setup(self, icon):
        icon.visible = True
        threading.Thread(target=self.loop, daemon=True).start()

    def run(self):
        self.icon.run(self.setup)