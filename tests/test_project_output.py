"""Offline tests for per-board folders and safe CNC laser G-code output."""
from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from project_output import generate_gcode, project_folder, run_batch


class ProjectOutputTests(unittest.TestCase):
    def test_project_folders_derived_from_kicad_layers(self):
        root = Path('C:/tools')
        self.assertEqual(project_folder(root / 'EVSE-F_Cu.svg'), root / '_EVSE')
        self.assertEqual(project_folder(root / 'EVSE-B_Cu.svg'), root / '_EVSE')
        self.assertEqual(project_folder(root / 'Many-Parts-B_Cu.svg'), root / '_Many-Parts')
        self.assertEqual(project_folder(root / 'misc.svg'), root)

    def test_gcode_origin_direction_and_safety(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'board.png'
            im = Image.new('L', (20, 20), 255)
            for x in range(0, 5):
                im.putpixel((x, 19), 0)  # bottom-left burn, at Y0
            for x in range(15, 20):
                im.putpixel((x, 0), 0)  # top-right burn, at Y1.9
            im.save(p)
            out = generate_gcode(p, Decimal('2'), Decimal('2'), lines_per_mm=10)
            text = out.read_text()
            self.assertIn('G21 (millimetres)', text)
            self.assertIn('G0 X0 Y0 S0\nG1 X0.5 F1000 S1000', text)
            self.assertIn('G0 X2 Y1.9 S0\nG1 X1.5 F1000 S1000', text)
            self.assertTrue(text.endswith('M5\nG0 X0 Y0 (return to image origin)\n'))
            self.assertNotIn('Z', text)
            self.assertNotIn('S500', text)

    def test_long_full_line_snake(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'solid.png'
            Image.new('L', (20, 20), 0).save(p)
            text = generate_gcode(p, Decimal('2'), Decimal('2')).read_text()
            self.assertIn('G0 X0 Y0 S0\nG1 X2 F1000 S1000', text)
            self.assertIn('G0 X2 Y0.1 S0\nG1 X0 F1000 S1000', text)

    def test_invalid_power_or_speed_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'solid.png'
            Image.new('L', (20, 20), 0).save(p)
            with self.assertRaises(ValueError):
                generate_gcode(p, Decimal('2'), Decimal('2'), power=1001)
            with self.assertRaises(ValueError):
                generate_gcode(p, Decimal('2'), Decimal('2'), lines_per_mm=0)

    def test_project_batch_moves_both_layers_and_backs_up_changed_svg(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src_f = root / 'EVSE-F_Cu.svg'
            src_b = root / 'EVSE-B_Cu.svg'
            src_f.write_text('initial f', encoding='utf8')
            src_b.write_text('initial b', encoding='utf8')

            def fake_convert(src, dpi, threshold, invert, mirror, *, output_dir):
                imname = src.stem + '_laser.png'
                Image.new('L', (20, 20), 0).save(output_dir / imname)
                guide = src.stem + '_laser_settings.txt'
                (output_dir / guide).write_text('guide')
                return SimpleNamespace(source=src.name, image=imname, guide=guide,
                                       width_mm=Decimal('2'), height_mm=Decimal('2'),
                                       pixels_w=20, pixels_h=20, dpi=dpi,
                                       lasergrbl_h_if_w_mm=Decimal('2'),
                                       lasergrbl_h_error_mm=Decimal('0'))

            kwargs=dict(dpi=508, threshold=128, invert=False, mirror_x=False,
                        lines_per_mm=10, feed=1000, power=1000,
                        convert=fake_convert, combined_report=lambda r, e, d: 'report')
            code = run_batch(root, [src_b, src_f], **kwargs)
            self.assertEqual(code, 0)
            folder = root / '_EVSE'
            for side in ('F', 'B'):
                self.assertFalse((root / f'EVSE-{side}_Cu.svg').exists())
                for suffix in ('.svg', '_laser.png', '_laser.nc', '_laser_settings.txt'):
                    self.assertTrue((folder / f'EVSE-{side}_Cu{suffix}').exists())
            self.assertTrue((folder / 'LASERGRBL_SETTINGS.txt').exists())
            self.assertTrue((folder / 'lasergrbl_sizes.csv').exists())
            self.assertTrue((root / 'LASERGRBL_SETTINGS.txt').exists())
            src_f.write_text('updated f', encoding='utf8')
            self.assertEqual(run_batch(root, [src_f], **kwargs), 0)
            self.assertEqual((folder / 'EVSE-F_Cu.svg').read_text(), 'updated f')
            self.assertTrue(any(p.read_text() == 'initial f' for p in (folder / '_backups').glob('*.svg'))


    def test_failed_regeneration_does_not_destroy_previous_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / '_EVSE'
            folder.mkdir()
            old = folder / 'EVSE-F_Cu_laser.png'
            old.write_bytes(b'previous valid PNG')
            source = root / 'EVSE-F_Cu.svg'
            source.write_text('new SVG')

            def fails(src, dpi, threshold, invert, mirror, *, output_dir):
                (output_dir / old.name).write_bytes(b'partial new PNG')
                raise RuntimeError('test simulated rendering failure')

            result = run_batch(root, [source], dpi=508, threshold=128,
                               invert=False, mirror_x=False, lines_per_mm=10,
                               feed=1000, power=1000, convert=fails,
                               combined_report=lambda r, e, d: 'report')
            self.assertEqual(result, 1)
            self.assertTrue(source.exists())
            self.assertEqual(old.read_bytes(), b'previous valid PNG')
            self.assertFalse(list(folder.glob('.laser-stage-*')))


if __name__ == '__main__':
    unittest.main()
