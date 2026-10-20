"""Offline regression tests for KiCad SVG -> LaserGRBL PNG conversion."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from PIL import Image

from svg_to_png_batch import convert, pixel_dims, svg_mm


def svg_file(folder: Path, filename: str, width: str, height: str, shapes: str = '') -> Path:
    path = folder / filename
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'viewBox="0 0 100 50">'
        '<rect x="0" y="0" width="100" height="50" fill="black"/>'
        f'{shapes}</svg>', encoding='utf-8'
    )
    return path


class ConverterTests(unittest.TestCase):
    def test_physical_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(svg_mm(svg_file(root, 'mm.svg', '100mm', '50mm')),
                             (Decimal('100'), Decimal('50')))
            self.assertEqual(svg_mm(svg_file(root, 'in.svg', '1in', '0.5in')),
                             (Decimal('25.4'), Decimal('12.70')))

    def test_unknown_units_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = svg_file(Path(tmp), 'px.svg', '100px', '50px')
            with self.assertRaises(ValueError):
                svg_mm(path)

    def test_pixel_grid(self):
        self.assertEqual(pixel_dims(Decimal('100'), Decimal('50'), 508), (2000, 1000))

    def test_export_png_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = svg_file(root, 'Тестовая плата.svg', '100mm', '50mm',
                           '<rect x="10" y="10" width="40" height="20" fill="white"/>')
            result = convert(src, dpi=508, threshold=128, invert=False, mirror_x=False)
            self.assertEqual((result.pixels_w, result.pixels_h), (2000, 1000))
            self.assertEqual((result.width_mm, result.height_mm),
                             (Decimal('100'), Decimal('50')))
            with Image.open(root / result.image) as image:
                self.assertEqual(image.size, (2000, 1000))
                self.assertEqual(set(image.convert('L').getdata()), {0, 255})
            guide = (root / result.guide).read_text(encoding='utf-8-sig')
            self.assertIn('100,0000', guide)
            self.assertIn('50,0000', guide)

    def test_invert_flips_color(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = svg_file(root, 'invert.svg', '25.4mm', '12.7mm')
            original = convert(src, 254, 128, False, False)
            with Image.open(root / original.image) as image:
                self.assertEqual(image.convert('L').getpixel((50, 50)), 0)
            inverted = convert(src, 254, 128, True, False)
            with Image.open(root / inverted.image) as image:
                self.assertEqual(image.convert('L').getpixel((50, 50)), 255)


if __name__ == '__main__':
    unittest.main()
