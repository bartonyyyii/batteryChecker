from abc import ABC, abstractmethod
from battery_checker.models import DeviceStatus

class Provider(ABC):
    @abstractmethod
    def scan(self) -> list[DeviceStatus]:
        ...
