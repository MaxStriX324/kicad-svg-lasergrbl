"""Test rebuilding organized KiCad layers without moving them to the root."""
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from project_output import find_svg_inputs, project_folder, run_batch


class RebuildTests(unittest.TestCase):
    def test_rebuild_existing_keeps_binary_and_grayscale_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / '_EVSE'
            folder.mkdir()
            svg = folder / 'EVSE-F_Cu.svg'
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" '
                'width="2mm" height="1mm" viewBox="0 0 2 1">'
                '<rect width="0.15" height="1" fill="black"/></svg>',
                encoding='utf-8',
            )

            def fake_convert(src, dpi, threshold, invert, mirror, *, output_dir):
                name = src.stem + '_laser.png'
                guide = src.stem + '_laser_settings.txt'
                Image.new('L', (40, 20), 0).save(output_dir / name)
                (output_dir / guide).write_text('guide', encoding='utf-8')
                return SimpleNamespace(
                    source=src.name, image=name, guide=guide,
                    width_mm=Decimal('2'), height_mm=Decimal('1'),
                    pixels_w=40, pixels_h=20, dpi=dpi,
                    lasergrbl_h_if_w_mm=Decimal('1'),
                    lasergrbl_h_error_mm=Decimal('0'),
                )

            kwargs = dict(
                dpi=508, threshold=128, invert=False, mirror_x=False,
                lines_per_mm=10, feed=1000, power=1000,
                convert=fake_convert, combined_report=lambda a, b, c: 'test',
            )
            self.assertEqual(find_svg_inputs(root), [])
            self.assertEqual(project_folder(svg), folder)
            self.assertEqual(find_svg_inputs(root, rebuild_existing=True), [svg])
            self.assertEqual(run_batch(root, [svg], mode='binary', **kwargs), 0)
            binary = folder / 'EVSE-F_Cu_laser.nc'
            self.assertTrue(binary.is_file())
            self.assertEqual(run_batch(root, [svg], mode='grayscale', **kwargs), 0)
            gray = folder / 'EVSE-F_Cu_laser_grayscale.nc'
            self.assertTrue(gray.is_file())
            powers = [int(x) for x in re.findall(r'\bS(\d+)\b', gray.read_text())]
            self.assertTrue(any(0 < x < 1000 for x in powers))
            self.assertTrue(binary.is_file())
            self.assertFalse((folder / '_EVSE').exists())
            self.assertTrue(svg.is_file())

            # Newly supplied root files take priority over existing project SVGs.
            new = root / svg.name
            new.write_text('new source', encoding='utf-8')
            self.assertEqual(find_svg_inputs(root, rebuild_existing=True), [new])


if __name__ == '__main__':
    unittest.main()
