"""Integration test: actual SVG rendering, project grouping, NC and reruns."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class FullPipelineTests(unittest.TestCase):
    def test_two_evse_layers_are_moved_and_rendered(self):
        project_root = Path(__file__).resolve().parent.parent
        script = project_root / 'svg_to_png_batch.py'
        with tempfile.TemporaryDirectory(prefix='laser test ') as tmp:
            folder = Path(tmp)
            for layer in ('F', 'B'):
                (folder / f'EVSE-{layer}_Cu.svg').write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" '
                    'width="3mm" height="2mm" viewBox="0 0 3 2">'
                    '<rect width="3" height="2" fill="black"/>'
                    '</svg>', encoding='utf-8',
                )
            args = [
                sys.executable, str(script), '--folder', str(folder),
                '--dpi', '254', '--gcode-lines-per-mm', '10',
                '--gcode-feed', '1000', '--gcode-power', '1000',
            ]
            result = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
            out = folder / '_EVSE'
            self.assertTrue(out.is_dir())
            for layer in ('F', 'B'):
                stem = f'EVSE-{layer}_Cu'
                self.assertFalse((folder / (stem + '.svg')).exists())
                self.assertTrue((out / (stem + '.svg')).exists())
                self.assertTrue((out / (stem + '_laser.png')).exists())
                self.assertTrue((out / (stem + '_laser_settings.txt')).exists())
                nc = (out / (stem + '_laser.nc')).read_text()
                self.assertIn('G21', nc)
                self.assertIn('G0 X0 Y0', nc)
                self.assertIn('G1 X3 F1000 S1000', nc)
                self.assertTrue(nc.endswith('M5\nG0 X0 Y0 (return to image origin)\n'))
            self.assertTrue((out / 'LASERGRBL_SETTINGS.txt').exists())
            self.assertTrue((out / 'lasergrbl_sizes.csv').exists())
            self.assertTrue((folder / 'LASERGRBL_SETTINGS.txt').exists())
            rerun = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(rerun.returncode, 0, rerun.stdout + '\n' + rerun.stderr)
            self.assertIn('No SVG files found', rerun.stdout)


if __name__ == '__main__':
    unittest.main()
