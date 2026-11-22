from dataclasses import dataclass

@dataclass
class DeviceStatus:
    name: str
    level: int | None
    charging: bool = False