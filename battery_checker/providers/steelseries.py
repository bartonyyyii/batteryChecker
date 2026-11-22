import hid

from battery_checker.models import DeviceStatus
from battery_checker.providers.base import Provider


VENDOR_ID = 0x1038     #SteelSeries
PRODUCT_ID = 0x1838    #Aerox 3 Wireless
INTERFACE = 3
BATTERY_COMMAND = 0xD2
CHARGING_FLAG = 0x80


class SteelSeriesProvider(Provider):
    def scan(self) -> list[DeviceStatus]:
        info = next(
            (d for d in hid.enumerate(VENDOR_ID, PRODUCT_ID) 
            if d["interface_number"] == INTERFACE),
            None,
        )
        if info is None:
            return []

        name = info["product_string"] or "SteelSeries mouse"

        try:
            data = self._read_battery_data(info["path"])
        except OSError:
            return [DeviceStatus(name=name, level=None)]

        if len(data) < 2 or data[0] != BATTERY_COMMAND:
            return [DeviceStatus(name=name, level=None)]

        charging = bool(data[1] & CHARGING_FLAG)
        level = ((data[1] & ~CHARGING_FLAG) - 1) * 5

        if not 0 <= level <= 100:
            level = None

        return [DeviceStatus(name=name, level=level, charging=charging)]

    def _read_battery_data(self, path: bytes) -> list[int]:
        dev = hid.device()
        dev.open_path(path)
        try:
            dev.write([0x00, BATTERY_COMMAND])
            return dev.read(64, timeout_ms=1000)
        finally:
            dev.close()