"""Вывод на экран помпы через trcc-linux (bulk-протокол, PM=64/SUB=3).

Библиотека используется как зависимость: её адаптер ``BulkLcd`` делает
хендшейк и заворачивает JPEG-кадр в 64-байтный заголовок, транспорт —
WinUSB через pyusb. Наша часть: JPEG-кодирование PIL-кадра и аккуратное
закрытие устройства.

Лицензия: trcc-linux — GPL-3.0; проект распространяется под GPL-3.0.
"""
from __future__ import annotations

import io
import logging

import psutil
from PIL import Image

from display.base import DisplayBackend, DisplayOffline

log = logging.getLogger(__name__)

#: Процессы, которые держат экран, пока запущены.
_OWNERS = {"trcc.exe", "usblcdnew.exe"}


class TrccDisplayError(RuntimeError):
    pass


def check_trcc_running() -> list[str]:
    """Имена запущенных процессов штатного TRCC (они забирают устройство)."""
    found: list[str] = []
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in _OWNERS:
            found.append(name)
    return found


class TrccBackend(DisplayBackend):
    needs_keepalive = True

    def __init__(
        self,
        vid: int = 0x87AD,
        pid: int = 0x70DB,
        unit: str = "",
        jpeg_quality: int = 85,
    ) -> None:
        self._vid = vid
        self._pid = pid
        self._unit = unit
        self._quality = jpeg_quality
        self._device = None
        self._profile = None
        self._size = (0, 0)
        self._pm = 0
        self._sub = 0

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def describe(self) -> dict[str, object]:
        p = self._profile
        return {
            "size": self._size,
            "pm": self._pm,
            "sub": self._sub,
            "jpeg": bool(p.jpeg) if p else None,
            "encode_base": getattr(p, "encode_base", None),
            "portrait_mounted": getattr(p, "portrait_mounted", None),
        }

    def connect(self) -> None:
        """Открыть устройство и сделать хендшейк (без отправки кадров)."""
        if self._device is not None:
            return
        running = check_trcc_running()
        if running:
            raise TrccDisplayError(
                "Закрыт ли TRCC? Сейчас запущены: "
                + ", ".join(sorted(set(running)))
                + ". Устройство нельзя делить — выйдите из TRCC (иконка в трее → выход)."
            )

        from trcc.adapters.device import DEVICES
        from trcc.adapters.system import current_platform
        from trcc.core.registry import find_product

        product = find_product(self._vid, self._pid)
        if product is None:
            raise TrccDisplayError(
                f"trcc-linux не знает USB {self._vid:04x}:{self._pid:04x}"
            )
        platform = current_platform()
        transport = platform.open_transport(
            product.wire, product.vid, product.pid, unit=self._unit
        )
        device = DEVICES[product.wire](product, transport)
        try:
            result = device.connect()
        except Exception:
            device.disconnect()
            raise

        profile = device.profile
        if profile is None:
            device.disconnect()
            raise TrccDisplayError("хендшейк прошёл, но профиль не определён")
        self._device = device
        self._profile = profile
        self._size = profile.resolution
        self._pm = result.pm_byte
        self._sub = result.sub_byte
        self.is_connected = True
        log.info(
            "экран: PM=%s SUB=%s, %dx%d, %s",
            result.pm_byte,
            result.sub_byte,
            profile.width,
            profile.height,
            "JPEG" if profile.jpeg else "RGB565",
        )
        if not profile.jpeg:
            log.warning(
                "профиль ждёт RGB565, а бэкенд кодирует JPEG — кадры могут не принять"
            )

    def send_frame(self, rgb_image: Image.Image) -> None:
        if self._device is None or self._profile is None:
            raise DisplayOffline("экран не подключён")
        if rgb_image.size != self._size:
            rgb_image = rgb_image.resize(self._size, Image.BILINEAR)
        if rgb_image.mode != "RGB":
            rgb_image = rgb_image.convert("RGB")

        buf = io.BytesIO()
        rgb_image.save(
            buf, format="JPEG", quality=self._quality, optimize=False, subsampling=2
        )
        payload = buf.getvalue()
        try:
            ok = self._device.send(payload)
        except Exception as exc:
            self._drop()
            raise DisplayOffline(f"потеряна связь с экраном: {exc}") from exc
        if not ok:
            self._drop()
            raise DisplayOffline("устройство не приняло кадр (send вернул False)")

    def _drop(self) -> None:
        if self._device is not None:
            try:
                self._device.disconnect()
            except Exception:
                pass
        self._device = None
        self.is_connected = False
        self._size = (0, 0)

    def close(self) -> None:
        if self._device is not None:
            try:
                self._device.disconnect()
            finally:
                self._device = None
                self.is_connected = False
                log.info("экран: устройство отпущено")
