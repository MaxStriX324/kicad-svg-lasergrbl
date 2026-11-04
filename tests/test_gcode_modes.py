"""Regression tests for binary/grayscale laser power and XY raster density."""
from decimal import Decimal
from pathlib import Path
import re
import tempfile
import unittest

from PIL import Image
from project_output import generate_gcode

HALF_EDGE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="2mm" height="1mm" '
    'viewBox="0 0 2 1"><rect width="0.155" height="1" fill="black"/></svg>'
)


class LaserModesTests(unittest.TestCase):
    def test_grayscale_is_rendered_from_svg_not_thresholded_png(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            svg = path / 'board.svg'
            svg.write_text(HALF_EDGE, encoding='utf-8')
            png = path / 'board.png'
            Image.new('L', (40, 20), 255).save(png)  # intentionally all white
            gray = generate_gcode(
                png, Decimal('2'), Decimal('1'), mode='grayscale',
                svg_source=svg, lines_per_mm=10,
            ).read_text(encoding='ascii')
            powers = [int(value) for value in re.findall(r'\bS(\d+)\b', gray)]
            self.assertIn(1000, powers)
            self.assertTrue(any(0 < value < 1000 for value in powers), powers)
            self.assertIn('G1 X0.1 F1000 S1000\nG1 X0.2 F1000 S', gray)
            binary = generate_gcode(
                png, Decimal('2'), Decimal('1'), mode='binary',
                lines_per_mm=10,
            ).read_text(encoding='ascii')
            self.assertNotIn('S1000', binary)
            self.assertEqual(set(int(x) for x in re.findall(r'\bS(\d+)\b', binary)), {0})

    def test_20_samples_per_mm_on_both_axes(self):
        with tempfile.TemporaryDirectory() as temp:
            png = Path(temp) / 'solid.png'
            Image.new('L', (40, 20), 0).save(png)
            code = generate_gcode(
                png, Decimal('2'), Decimal('1'), mode='binary',
                lines_per_mm=20,
            ).read_text(encoding='ascii')
            self.assertIn('G0 X0 Y0 S0\nG1 X2 F1000 S1000', code)
            self.assertIn('G0 X2 Y0.05 S0\nG1 X0 F1000 S1000', code)
            self.assertIn('G0 X0 Y0.1 S0\nG1 X2 F1000 S1000', code)
            self.assertEqual(code.count('G0 X'), 22)  # initial + 20 raster rows + end
            self.assertTrue(code.endswith('M5\nG0 X0 Y0 (return to image origin)\n'))

    def test_mirror_and_inversion_affect_grayscale_nc(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            svg = path / 'board.svg'
            svg.write_text(HALF_EDGE, encoding='utf-8')
            png = path / 'board.png'
            Image.new('L', (40, 20), 255).save(png)
            def run(**kwargs):
                return generate_gcode(
                    png, Decimal('2'), Decimal('1'), mode='grayscale',
                    svg_source=svg, lines_per_mm=10, **kwargs,
                ).read_text(encoding='ascii')
            original = run()
            inverted = run(invert=True)
            mirrored = run(mirror_x=True)
            self.assertNotEqual(original, inverted)
            self.assertNotEqual(original, mirrored)
            self.assertIn('G0 X0', original)
            self.assertIn('G0 X1.8', mirrored)

    def test_reject_invalid_modes_and_sampling(self):
        with tempfile.TemporaryDirectory() as temp:
            png = Path(temp) / 'solid.png'
            Image.new('L', (20, 20), 0).save(png)
            with self.assertRaises(ValueError):
                generate_gcode(png, Decimal('2'), Decimal('2'), mode='unknown')
            with self.assertRaises(ValueError):
                generate_gcode(png, Decimal('2'), Decimal('2'), mode='grayscale')
            for density in (0, 5, 40, 51):
                with self.assertRaises(ValueError):
                    generate_gcode(png, Decimal('2'), Decimal('2'),
                                   lines_per_mm=density)


if __name__ == '__main__':
    unittest.main()
