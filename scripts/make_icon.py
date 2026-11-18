"""Render the route split mark into the Windows application and tray icon."""
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ASSETS = Path(__file__).resolve().parent.parent / 'assets'
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main():
    renderer = QSvgRenderer(str(ASSETS / 'app-icon.svg'))
    if not renderer.isValid():
        raise ValueError('Cannot render assets/app-icon.svg')

    # Supersample the vector once, then let Pillow resample each ICO frame.
    resolution = 1024
    canvas = QImage(resolution, resolution, QImage.Format.Format_RGBA8888)
    canvas.fill(0)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
    finally:
        painter.end()

    image = Image.frombytes('RGBA', (resolution, resolution), bytes(canvas.constBits()))
    image.save(ASSETS / 'app.ico', sizes=[(size, size) for size in ICON_SIZES])


if __name__ == '__main__':
    main()
