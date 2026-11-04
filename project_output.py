"""Project folders and safe raster GRBL output for the KiCad SVG converter.

G-code intentionally burns black regions of the *already converted* 1-bit PNG.
The page's lower-left corner is X0 Y0; no Z-axis motion is emitted.
"""
from __future__ import annotations

import csv
import filecmp
import math
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from PIL import Image

PROJECT_RE = re.compile(r'^(?P<name>.+)-(?P<layer>F_Cu|B_Cu)\.svg$', re.IGNORECASE)
REPORT_NAME = 'LASERGRBL_SETTINGS.txt'


def project_folder(svg: Path) -> Path:
    """Only recognized KiCad copper layers get a project folder."""
    match = PROJECT_RE.fullmatch(svg.name)
    return svg.parent / ('_' + match.group('name')) if match else svg.parent


def fmt_mm(value: Decimal | float) -> str:
    """Enough decimal places for typical GRBL 0.02 mm and 0.1 mm steps."""
    return f'{float(value):.4f}'.rstrip('0').rstrip('.') or '0'


def generate_gcode(png: Path, width_mm: Decimal, height_mm: Decimal, *,
                   lines_per_mm: int = 10, feed: int = 1000, power: int = 1000) -> Path:
    """Write black-pixel-only, bidirectional raster moves in millimetres.

    S0 is set before each rapid and between every two burn runs. Raster
    row 0 corresponds to the bottom of the PNG (SVG Y axis is downward).
    No firmware-specific homing or Z commands are included.
    """
    if not 1 <= lines_per_mm <= 50:
        raise ValueError('lines_per_mm must be 1..50')
    if not 1 <= feed <= 30000 or not 1 <= power <= 1000:
        raise ValueError('feed must be 1..30000 and power 1..1000; check GRBL $30')
    w, h = float(width_mm), float(height_mm)
    if not all(map(math.isfinite, (w, h))) or w <= 0 or h <= 0:
        raise ValueError('SVG physical dimensions must be positive and finite')
    count_x, count_y = math.ceil(w * lines_per_mm), math.ceil(h * lines_per_mm)
    if count_x * count_y > 12_000_000:
        raise ValueError('G-code raster exceeds 12 million cells; reduce lines_per_mm')
    output = png.with_suffix('.nc')
    temporary = output.with_name(output.name + '.tmp')
    with Image.open(png) as raw:
        gray = raw.convert('L')
        iw, ih = gray.size
        pixels = gray.tobytes()
    indices_x = [min(iw - 1, int((x + 0.5) * iw / (w * lines_per_mm)))
                 for x in range(count_x)]
    widths = [fmt_mm(min(w, i / lines_per_mm)) for i in range(count_x + 1)]
    try:
        with temporary.open('w', encoding='ascii', newline='\n') as out:
            out.write('G21 (millimetres)\nG90 (absolute)\nG94 (feed per minute)\n')
            out.write('G0 X0 Y0\nM3 S0\n')
            for row in range(count_y):
                y_mm = row / lines_per_mm
                y = fmt_mm(y_mm)
                iy = min(ih - 1, max(0, ih - 1 - int((y_mm + 0.5 / lines_per_mm) * ih / h)))
                offset = iy * iw
                runs: list[tuple[int, int]] = []
                start = None
                for i, source_x in enumerate(indices_x):
                    black = pixels[offset + source_x] < 128
                    if black and start is None:
                        start = i
                    if not black and start is not None:
                        runs.append((start, i))
                        start = None
                if start is not None:
                    runs.append((start, count_x))
                if row % 2:
                    runs.reverse()
                for lo, hi in runs:
                    x_start = widths[hi] if row % 2 else widths[lo]
                    x_end = widths[lo] if row % 2 else widths[hi]
                    if x_start == x_end:
                        continue
                    out.write(f'G0 X{x_start} Y{y} S0\n')
                    out.write(f'G1 X{x_end} F{feed} S{power}\n')
                    out.write('S0\n')
            out.write('M5\nG0 X0 Y0 (return to image origin)\n')
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def move_source_with_backup(source: Path, dest: Path) -> None:
    """Move input only after output generation; back up changed existing SVGs."""
    if source == dest:
        return
    if dest.exists():
        if filecmp.cmp(source, dest, shallow=False):
            source.unlink()  # both files were byte-for-byte identical
            return
        backups = dest.parent / '_backups'
        backups.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup = backups / f'{dest.stem}_{stamp}{dest.suffix}'
        dest.replace(backup)
        try:
            source.replace(dest)
        except Exception:
            backup.replace(dest)
            raise
    else:
        source.replace(dest)


def write_summary(folder: Path, results: list, errors: list[tuple[str, str]],
                  dpi: int, combined_report, locations: dict[str, str],
                  quality: int, feed: int, power: int) -> None:
    header = ('G-code: horizontal bidirectional raster, black=laser ON, '
              'origin=lower left (X0 Y0), M3, no Z moves.\n'
              f'Raster: {quality} lines/mm; F{feed}; S{power}. '
              'Verify $30, scale, orientation and laser polarity before running.\n\n')
    lines = ['Files:', *(f'{name} -> {location}' for name, location in locations.items()), '']
    text = header + '\n'.join(lines) + combined_report(results, errors, dpi)
    (folder / REPORT_NAME).write_text(text, encoding='utf-8-sig')
    with (folder / 'lasergrbl_sizes.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['Folder', 'SVG', 'PNG', 'Gcode_NC', 'Guide_TXT', 'SVG_W_mm',
                         'SVG_H_mm', 'PNG_PX_W', 'PNG_PX_H', 'DPI',
                         'H_if_W_entered_mm', 'H_delta_mm', 'Status'])
        for r in results:
            loc = locations.get(r.source, '.')
            writer.writerow([loc, r.source, r.image, Path(r.image).with_suffix('.nc').name,
                             r.guide, str(r.width_mm), str(r.height_mm), r.pixels_w,
                             r.pixels_h, r.dpi, f'{r.lasergrbl_h_if_w_mm:.6f}',
                             f'{r.lasergrbl_h_error_mm:+.6f}', 'OK'])
        for name, error in errors:
            writer.writerow(['', name, '', '', '', '', '', '', '', '', '', '', 'ERROR: ' + error])


def run_batch(folder: Path, files: list[Path], *, dpi: int, threshold: int,
              invert: bool, mirror_x: bool, lines_per_mm: int, feed: int,
              power: int, convert, combined_report) -> int:
    """Organize F/B copper pairs into _project folders and generate PNG/NC/TXT."""
    if not files:
        print('No SVG files found beside start.cmd; existing project folders unchanged.')
        return 0
    all_results: list = []
    all_errors: list[tuple[str, str]] = []
    by_dir: dict[Path, list] = defaultdict(list)
    locations: dict[str, str] = {}
    for idx, svg in enumerate(files, 1):
        target_dir = project_folder(svg)
        print(f'[{idx}/{len(files)}] {svg.name} -> {target_dir.name}/')
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            result = convert(svg, dpi, threshold, invert, mirror_x, output_dir=target_dir)
            nc = generate_gcode(target_dir / result.image, result.width_mm,
                                result.height_mm, lines_per_mm=lines_per_mm,
                                feed=feed, power=power)
            move_source_with_backup(svg, target_dir / svg.name)
            all_results.append(result)
            by_dir[target_dir].append(result)
            locations[svg.name] = '.' if target_dir == folder else target_dir.name
            print(f'  OK: {result.image} + {nc.name}; image {result.pixels_w}x{result.pixels_h}')
        except Exception as exc:
            all_errors.append((svg.name, f'{type(exc).__name__}: {exc}'))
            print(f'  ERROR: {type(exc).__name__}: {exc}')
    for directory, rows in by_dir.items():
        if directory != folder:
            write_summary(directory, rows, [], dpi, combined_report,
                          {r.source: '.' for r in rows}, lines_per_mm, feed, power)
    write_summary(folder, all_results, all_errors, dpi, combined_report,
                  locations, lines_per_mm, feed, power)
    print(f'Done: {len(all_results)} OK / {len(all_errors)} ERROR; output folders:',
          ', '.join(sorted({loc for loc in locations.values()})) or '(none)')
    return 1 if all_errors else 0
