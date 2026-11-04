"""Inline SVG icon set, tinted at runtime (no external icon theme needed)."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..core.paths import resource_path
from .theme import colors

_ICON_PATHS: dict[str, str] = {
    "dashboard": (
        '<rect x="3" y="3" width="7" height="9" rx="2"/>'
        '<rect x="14" y="3" width="7" height="5" rx="2"/>'
        '<rect x="14" y="12" width="7" height="9" rx="2"/>'
        '<rect x="3" y="16" width="7" height="5" rx="2"/>'
    ),
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
    "wallet": (
        '<path d="M3 7a2 2 0 0 1 2-2h13a1 1 0 0 1 1 1v2"/>'
        '<path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3"/>'
        '<path d="M21 10h-5a2 2 0 0 0 0 4h5v-4z"/><path d="M16 12h.01"/>'
    ),
    "target": (
        '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>'
        '<circle cx="12" cy="12" r="1.4"/>'
    ),
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "settings": (
        '<path d="M4 6h9M17 6h3M4 12h2M10 12h10M4 18h7M15 18h5"/>'
        '<circle cx="15" cy="6" r="2"/><circle cx="8" cy="12" r="2"/>'
        '<circle cx="13" cy="18" r="2"/>'
    ),
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
    "sun": (
        '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4"/>'
        '<path d="M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
    ),
    "moon": '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z"/>',
    "trending-up": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "trending-down": '<path d="m3 7 6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
    "income": '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',
    "expense": '<path d="M12 5v14"/><path d="m6 13 6 6 6-6"/>',
    "transfer": (
        '<path d="M4 7h13"/><path d="m14 4 3 3-3 3"/>'
        '<path d="M20 17H7"/><path d="m10 14-3 3 3 3"/>'
    ),
    "calendar": (
        '<rect x="3" y="5" width="18" height="16" rx="2"/>'
        '<path d="M3 10h18M8 3v4M16 3v4"/>'
    ),
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 19h16"/>',
    "upload": '<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M4 4h16"/>',
    "trash": (
        '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>'
        '<path d="M10 11v6M14 11v6"/>'
    ),
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "alert": '<path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 9v5M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    "database": (
        '<ellipse cx="12" cy="5" rx="8" ry="3"/>'
        '<path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
        '<path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>'
    ),
    "palette": (
        '<path d="M12 3a9 9 0 1 0 0 18h1.4a1.9 1.9 0 0 0 0-3.8H12a2.2 2.2 0 0 1 0-4.4h4.2A4.8 4.8 0 0 0 21 8.1 5.1 5.1 0 0 0 15.9 3H12Z"/>'
        '<circle cx="7.5" cy="10" r="1"/><circle cx="9.5" cy="6.5" r="1"/>'
        '<circle cx="14" cy="6.2" r="1"/>'
    ),
    "credit-card": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    "bank": (
        '<path d="m3 10 9-6 9 6"/><path d="M5 10v8M9 10v8M15 10v8M19 10v8M3 21h18"/>'
    ),
    "cash": (
        '<rect x="2" y="6" width="20" height="12" rx="2"/>'
        '<circle cx="12" cy="12" r="3"/><path d="M6 10h.01M18 14h.01"/>'
    ),
    "investment": '<path d="M3 20h18"/><path d="m5 16 5-5 4 4 6-8"/><path d="M15 7h5v5"/>',
    "loan": (
        '<path d="M6 3h9l4 4v14H6z"/><path d="M9 11h7M9 15h5"/>'
    ),
    "savings": (
        '<path d="M12 3v3M8 6h8a5 5 0 0 1 5 5v2a5 5 0 0 1-5 5h-1l-2 3-2-3h-2a5 5 0 0 1-5-5v-2a5 5 0 0 1 5-5Z"/>'
        '<path d="M9 11h.01"/>'
    ),
    "filter": '<path d="M3 5h18l-7 8v6l-4 2v-8Z"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "more": '<path d="M5 12h.01M12 12h.01M19 12h.01"/>',
    "sparkles": (
        '<path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8Z"/>'
        '<path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9Z"/>'
    ),
    "shield": (
        '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z"/>'
        '<path d="m9 12 2 2 4-4"/>'
    ),
    "arrow-right": '<path d="M4 12h16"/><path d="m14 6 6 6-6 6"/>',
    "refresh": (
        '<path d="M20 7v5h-5"/><path d="M4 17v-5h5"/>'
        '<path d="M5.5 9a7 7 0 0 1 11.5-2L20 12M4 12l3 5a7 7 0 0 0 11.5-2"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "archive": (
        '<rect x="3" y="4" width="18" height="4" rx="1"/>'
        '<path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4"/>'
    ),
    "tag": '<path d="M3 12V4h8l10 10-8 8L3 12Z"/><path d="M8 8h.01"/>',
    "home": (
        '<path d="M3 11.5 12 4l9 7.5"/>'
        '<path d="M5 10v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9"/>'
        '<path d="M9.5 20v-5.5h5V20"/>'
    ),
    "car": (
        '<path d="M5 16h14l-1.4-4.5a2 2 0 0 0-1.9-1.5H8.3a2 2 0 0 0-1.9 1.5L5 16Z"/>'
        '<path d="M4 16v3h2.5v-1.5h11V19H20v-3"/>'
        '<circle cx="7.5" cy="16" r="1"/><circle cx="16.5" cy="16" r="1"/>'
    ),
}

_APP_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="28" fill="#3D6DF2"/>
  <circle cx="104" cy="24" r="34" fill="#5B85FF" opacity="0.55"/>
  <circle cx="20" cy="112" r="28" fill="#2F5EE0" opacity="0.5"/>
  <path d="M34 47a8 8 0 0 1 8-8h45a5 5 0 0 1 5 5v10"
        fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round"/>
  <path d="M34 47v34a8 8 0 0 0 8 8h46a6 6 0 0 0 6-6v-10"
        fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round"/>
  <path d="M94 61H79a10 10 0 0 0 0 20h15V61Z"
        fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linejoin="round"/>
  <path d="M78 71h.1" fill="none" stroke="#FFFFFF" stroke-width="7" stroke-linecap="round"/>
</svg>
"""


def _render(svg: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """Return a tinted icon; colours are resolved against the active theme."""
    color = color or colors().muted
    return _cached_icon(name, color, size)


@lru_cache(maxsize=512)
def _cached_icon(name: str, color: str, size: int) -> QIcon:
    fragment = _ICON_PATHS.get(name, _ICON_PATHS["info"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"'
        f' viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        f"{fragment}</svg>"
    )
    return QIcon(_render(svg, size))


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    ico = resource_path("finboard.ico")
    if ico.exists():
        return QIcon(str(ico))
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        renderer = QSvgRenderer(QByteArray(_APP_SVG.encode("utf-8")))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(pixmap)
    return result


def set_button_icon(button, name: str, color: str | None = None, size: int = 18) -> None:
    button.setIcon(icon(name, color, size))
    button.setIconSize(QSize(size, size))
