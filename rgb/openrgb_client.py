"""Клиент OpenRGB SDK и синхронизация цвета вентиляторов.

Протокол OpenRGB (бинарный, TCP 6742) реализован по официальной документации
``Documentation/OpenRGBSDK.md`` проекта OpenRGB (GPL-2.0-or-later). Мы говорим
на протоколе 1: он есть во всех OpenRGB начиная с 0.5 и не требует разбирать
сегменты/флаги/зоны-режимы новых версий.

Формат кадра UpdateLEDs: ``u32 data_size`` (включает свои 4 байта),
``u16 count``, затем по ``u32 r | g << 8 | b << 16`` на каждый светодиод.
Перевод контроллера в ручной режим — пакет 1100 с пустым телом.
"""
from __future__ import annotations

import dataclasses
import logging
import select
import socket
import struct
import threading
import time
from collections.abc import Sequence

from core.config import RgbConfig

log = logging.getLogger(__name__)

RGB = tuple[int, int, int]

DEFAULT_PORT = 6742
CLIENT_NAME = "Levita Display"
PROTOCOL = 1

_MAGIC = b"ORGB"
_HEADER = struct.Struct("<4sIII")  # magic, dev_id, pkt_id, size

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
DEVICE_LIST_UPDATED = 100
UPDATE_LEDS = 1050
UPDATE_ZONE_LEDS = 1051
RESIZE_ZONE = 1000
SET_CUSTOM_MODE = 1100

_VERSION_WAIT_S = 1.0


class OpenRgbError(RuntimeError):
    """Сервер недоступен или ответил не по протоколу."""


def header(dev_id: int, pkt_id: int, size: int) -> bytes:
    return _HEADER.pack(_MAGIC, dev_id, pkt_id, size)


def update_leds_payload(colors: Sequence[RGB]) -> bytes:
    body = struct.pack("<H", len(colors)) + b"".join(
        struct.pack("<I", r | (g << 8) | (b << 16)) for r, g, b in colors
    )
    return struct.pack("<I", 4 + len(body)) + body


def zone_leds_payload(zone_index: int, colors: Sequence[RGB]) -> bytes:
    body = struct.pack("<IH", zone_index, len(colors)) + b"".join(
        struct.pack("<I", r | (g << 8) | (b << 16)) for r, g, b in colors
    )
    return struct.pack("<I", 4 + len(body)) + body


@dataclasses.dataclass(frozen=True)
class RgbZone:
    index: int
    name: str
    zone_type: int
    leds_count: int
    leds_min: int
    leds_max: int


@dataclasses.dataclass(frozen=True)
class RgbDevice:
    index: int
    name: str
    led_count: int
    zones: tuple[RgbZone, ...]
    modes: tuple[str, ...]
    active_mode: int

    @property
    def mode_name(self) -> str:
        if 0 <= self.active_mode < len(self.modes):
            return self.modes[self.active_mode]
        return "?"


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._at = 0

    def take(self, fmt: str) -> int:
        (value,) = struct.unpack_from(fmt, self._data, self._at)
        self._at += struct.calcsize(fmt)
        return value

    def text(self) -> str:
        size = self.take("<H")
        raw = self._data[self._at:self._at + size]
        self._at += size
        return raw.rstrip(b"\0").decode("utf-8", errors="replace")

    def skip(self, size: int) -> None:
        self._at += size


def parse_device(index: int, data: bytes, protocol: int = PROTOCOL) -> RgbDevice:
    """Имя, число зон/светодиодов и режимы из ответа controller data."""
    r = _Reader(data)
    r.take("<I")                    # data_size
    r.take("<i")                    # type
    name = r.text()
    if protocol >= 1:
        r.text()                    # vendor
    for _ in range(4):              # description, version, serial, location
        r.text()

    modes: list[str] = []
    num_modes = r.take("<H")
    active_mode = r.take("<i")
    for _ in range(num_modes):
        modes.append(r.text())
        r.skip(4 * 9)               # value..color_mode (протокол < 3)
        r.skip(4 * r.take("<H"))    # цветов режима

    zones: list[RgbZone] = []
    num_zones = r.take("<H")
    for zone_index in range(num_zones):
        zone_name = r.text()
        zone_type = r.take("<i")
        leds_min = r.take("<I")
        leds_max = r.take("<I")
        leds_count = r.take("<I")
        r.skip(r.take("<H"))        # matrix map, если есть
        zones.append(
            RgbZone(zone_index, zone_name, zone_type, leds_count, leds_min, leds_max)
        )

    num_leds = r.take("<H")
    for _ in range(num_leds):
        r.text()
        r.skip(4)                   # led value

    # У части плат (MSI Mystic Light) общий список LED пуст, а светодиоды
    # описаны только зонами — тогда сумма зон и есть размер кадра.
    total = num_leds if num_leds > 0 else sum(z.leds_count for z in zones)
    return RgbDevice(
        index=index,
        name=name,
        led_count=total,
        zones=tuple(zones),
        modes=tuple(modes),
        active_mode=active_mode,
    )


class OpenRgbClient:
    """Одно TCP-подключение к SDK-серверу OpenRGB."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 timeout: float = 3.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self.protocol = 0
        self.devices: list[RgbDevice] = []

    # ── соединение ────────────────────────────────────────────────────

    def connect(self) -> None:
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise OpenRgbError(f"OpenRGB недоступен на {self.host}:{self.port}: {exc}") from exc
        self._sock = sock
        try:
            self.protocol = self._negotiate()
            name = CLIENT_NAME.encode() + b"\0"
            self._send(0, SET_CLIENT_NAME, name)
        except (OSError, OpenRgbError):
            self.close()
            raise
        log.info("OpenRGB: подключено, протокол %d", self.protocol)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self.devices = []

    # ── запросы ───────────────────────────────────────────────────────

    def list_devices(self, refresh: bool = False) -> list[RgbDevice]:
        self.connect()
        if self.devices and not refresh:
            return self.devices
        count_packet = self._request(0, REQUEST_CONTROLLER_COUNT, b"")
        if len(count_packet) < 4:
            raise OpenRgbError("OpenRGB: пустой ответ на запрос числа устройств")
        (count,) = struct.unpack_from("<I", count_packet, 0)
        devices = []
        for index in range(count):
            payload = struct.pack("<I", self.protocol) if self.protocol >= 1 else b""
            reply = self._request(index, REQUEST_CONTROLLER_DATA, payload)
            try:
                devices.append(parse_device(index, reply, self.protocol))
            except struct.error as exc:
                log.warning("OpenRGB: не разобрал устройство #%d: %s", index, exc)
        self.devices = devices
        return devices

    def set_custom_mode(self, device: RgbDevice) -> None:
        self.connect()
        self._send(device.index, SET_CUSTOM_MODE, b"")

    def resize_zone(self, device: RgbDevice, zone_index: int, size: int) -> None:
        """Задать число светодиодов зоны (у MSI зоны начинаются с нуля)."""
        self.connect()
        self._send(device.index, RESIZE_ZONE, struct.pack("<ii", zone_index, size))

    def set_color(
        self, device: RgbDevice, color: RGB, zone_fallback: int = 0
    ) -> None:
        """Залить все светодиоды устройства одним цветом.

        Если у платы есть общий список LED — один пакет UpdateLEDs.
        Если он пуст, а светодиоды описаны только зонами (MSI Mystic Light) —
        по пакету UpdateZoneLEDs на каждую непустую зону.
        """
        self.connect()
        if device.led_count > 0:
            colors = [color] * device.led_count
            self._send(device.index, UPDATE_LEDS, update_leds_payload(colors))
            return
        for zone in device.zones:
            count = zone.leds_count or zone_fallback
            if count <= 0:
                continue
            self._send(
                device.index,
                UPDATE_ZONE_LEDS,
                zone_leds_payload(zone.index, [color] * count),
            )

    # ── низкий уровень ────────────────────────────────────────────────

    def _negotiate(self) -> int:
        assert self._sock is not None
        self._send(0, REQUEST_PROTOCOL_VERSION, struct.pack("<I", PROTOCOL))
        reply = self._recv(_VERSION_WAIT_S, expect=REQUEST_PROTOCOL_VERSION)
        if reply is None or len(reply) < 4:
            log.info("OpenRGB: версия не ответила — считаю протокол 0")
            return 0
        (server,) = struct.unpack_from("<I", reply, 0)
        return min(PROTOCOL, server)

    def _send(self, dev_id: int, pkt_id: int, payload: bytes) -> None:
        if self._sock is None:
            raise OpenRgbError("OpenRGB: нет соединения")
        self._sock.sendall(header(dev_id, pkt_id, len(payload)) + payload)

    def _recv(self, timeout: float, expect: int | None = None) -> bytes | None:
        assert self._sock is not None
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([self._sock], [], [], left)
            if not ready:
                return None
            head = self._recv_exact(16)
            magic, dev_id, pkt_id, size = _HEADER.unpack(head)
            if magic != _MAGIC:
                raise OpenRgbError("OpenRGB: неверный magic в ответе")
            body = self._recv_exact(size) if size else b""
            if expect is not None and pkt_id == expect:
                return body
            if pkt_id == DEVICE_LIST_UPDATED:
                self.devices = []
                continue
            # ACK и прочие служебные пакеты просто пропускаем.
            log.debug("OpenRGB: пропущен пакет id=%d dev=%d size=%d", pkt_id, dev_id, size)

    def _recv_exact(self, size: int) -> bytes:
        assert self._sock is not None
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self._sock.recv(size - len(chunks))
            if not chunk:
                raise OpenRgbError("OpenRGB: соединение закрыто сервером")
            chunks.extend(chunk)
        return bytes(chunks)

    def _request(self, dev_id: int, pkt_id: int, payload: bytes) -> bytes:
        self._send(dev_id, pkt_id, payload)
        reply = self._recv(self.timeout, expect=pkt_id)
        if reply is None:
            raise OpenRgbError(f"OpenRGB: нет ответа на пакет {pkt_id}")
        return reply


# ── синхронизация с палитрой ───────────────────────────────────────────


def _lerp(a: RGB, b: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


def _lerp_hsv(a: RGB, b: RGB, t: float) -> RGB:
    """Интерполяция по HSV: оттенок идёт коротким путём и не сереет посередине."""
    from colorsys import hsv_to_rgb, rgb_to_hsv

    t = max(0.0, min(1.0, t))
    ha, sa, va = rgb_to_hsv(*(v / 255.0 for v in a))
    hb, sb, vb = rgb_to_hsv(*(v / 255.0 for v in b))
    dh = (hb - ha + 0.5) % 1.0 - 0.5
    h = (ha + dh * t) % 1.0
    s = sa + (sb - sa) * t
    v = va + (vb - va) * t
    r, g, bl = hsv_to_rgb(h, s, v)
    return (int(round(r * 255)), int(round(g * 255)), int(round(bl * 255)))


def _distance(a: RGB, b: RGB) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def _hue_delta(a: RGB, b: RGB) -> float:
    """Кратчайшая разница оттенков в градусах (0..180)."""
    from colorsys import rgb_to_hsv

    ha = rgb_to_hsv(*(v / 255.0 for v in a))[0]
    hb = rgb_to_hsv(*(v / 255.0 for v in b))[0]
    diff = abs(hb - ha) % 1.0
    return min(diff, 1.0 - diff) * 360.0


class FanSyncService:
    """Плавно ведёт цвет вентиляторов за цветом палитры.

    Отправляет не чаще ``rate_hz`` и только если цвет реально изменился.
    При недоступном OpenRGB не мешает остальному приложению: пишет в лог
    и пробует переподключиться.
    """

    def __init__(self, cfg: RgbConfig) -> None:
        self.cfg = cfg
        self._target: RGB = (255, 255, 255)
        self._current: RGB = (255, 255, 255)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: OpenRgbClient | None = None
        self._devices: list[RgbDevice] = []
        self._last_sent: RGB | None = None
        self._last_error = 0.0
        self._custom_set: set[int] = set()
        self.available = False
        self.send_rate = 0.0
        self._sent_window = 0
        self._sent_since = time.monotonic()

    def set_target(self, color: RGB) -> None:
        with self._lock:
            self._target = color

    @property
    def current(self) -> RGB:
        with self._lock:
            return self._current

    def start(self) -> None:
        if not self.cfg.enabled:
            log.info("RGB: синхронизация выключена в конфиге")
            return
        self._thread = threading.Thread(target=self._loop, name="rgb-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._client is not None:
            self._client.close()
            self._client = None

    # ── цикл ──────────────────────────────────────────────────────────

    def _loop(self) -> None:
        interval = 1.0 / max(1.0, self.cfg.rate_hz)
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._tick(interval)
            except (OpenRgbError, OSError) as exc:
                self._on_failure(exc)
            self._stop.wait(max(0.0, interval - (time.monotonic() - started)))

    def _tick(self, interval: float) -> None:
        if self._client is None or not self._client.devices:
            self._connect()
        assert self._client is not None

        target = self._target
        # Экспоненциальное приближение: 63% пути за smooth_seconds.
        if self.cfg.smooth_seconds <= 0:
            new = target
        else:
            # Один оттенок — мягко; другой цвет — быстро, чтобы не отставать.
            same_color = _hue_delta(self._current, target) < self.cfg.hue_jump_degrees
            time_constant = (
                self.cfg.smooth_seconds if same_color else self.cfg.fast_smooth_seconds
            )
            step = 1.0 - pow(0.001, interval / max(0.02, time_constant))
            new = _lerp_hsv(self._current, target, step)
        with self._lock:
            self._current = new

        if self._last_sent is not None and _distance(new, self._last_sent) < self.cfg.min_delta:
            return
        for device in self._devices:
            if device.index not in self._custom_set:
                self._client.set_custom_mode(device)
                self._custom_set.add(device.index)
            self._client.set_color(device, new, zone_fallback=self.cfg.zone_leds)
        if self._last_sent is None:
            log.info("RGB: цвет %02x%02x%02x → %d устройство(а)", *new, len(self._devices))
        self._last_sent = new
        self.available = True
        self._sent_window += 1
        now = time.monotonic()
        if now - self._sent_since >= 5.0:
            self.send_rate = self._sent_window / (now - self._sent_since)
            self._sent_window = 0
            self._sent_since = now
            log.info(
                "RGB: %.1f отправок/с, цвет #%02x%02x%02x", self.send_rate, *new
            )

    def _connect(self) -> None:
        client = OpenRgbClient(self.cfg.host, self.cfg.port)
        client.connect()
        devices = client.list_devices(refresh=True)
        chosen = [d for d in devices if self._matches(d)]
        if not chosen:
            client.close()
            raise OpenRgbError(
                "OpenRGB не нашёл подходящих устройств "
                f"(фильтр '{self.cfg.device}'); доступны: "
                + ", ".join(d.name for d in devices)
            )
        self._client = client
        self._devices = chosen
        for device in chosen:
            for zone in device.zones:
                if not self._zone_matches(zone):
                    continue
                if zone.leds_count != self.cfg.zone_leds:
                    client.resize_zone(device, zone.index, self.cfg.zone_leds)
                    log.info(
                        "RGB: зона %s -> %d LED", zone.name, self.cfg.zone_leds
                    )
        self._custom_set.clear()
        self._last_sent = None
        self.available = True
        log.info(
            "RGB: управляю %s",
            ", ".join(
                f"{d.name} ({d.led_count or self.cfg.zone_leds} LED)"
                for d in chosen
            ),
        )

    def _zone_matches(self, zone: RgbZone) -> bool:
        if zone.leds_max <= 0:
            return False
        if self.cfg.zone:
            return self.cfg.zone.lower() in zone.name.lower()
        return True

    def _matches(self, device: RgbDevice) -> bool:
        if device.led_count <= 0 and not any(
            z.leds_max > 0 for z in device.zones
        ):
            return False
        if self.cfg.device:
            return self.cfg.device.lower() in device.name.lower()
        return True

    def _on_failure(self, exc: Exception) -> None:
        self.available = False
        if self._client is not None:
            self._client.close()
            self._client = None
        self._devices = []
        self._custom_set.clear()
        self._last_sent = None
        now = time.monotonic()
        if now - self._last_error >= 10.0:
            self._last_error = now
            log.warning("RGB: %s — повторю через 5 с", exc)
        self._stop.wait(5.0)
