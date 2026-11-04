"""Project folders and safe raster GRBL output for the KiCad SVG converter.

Binary mode burns black pixels of the converted 1-bit PNG.
Grayscale mode uses antialiased luminance rendered from the original SVG.
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
from tempfile import TemporaryDirectory

import pymupdf
from PIL import Image, ImageOps

PROJECT_RE = re.compile(r'^(?P<name>.+)-(?P<layer>F_Cu|B_Cu)\.svg$', re.IGNORECASE)
REPORT_NAME = 'LASERGRBL_SETTINGS.txt'


def project_folder(svg: Path) -> Path:
    """Only recognized KiCad copper layers get a project folder."""
    match = PROJECT_RE.fullmatch(svg.name)
    return svg.parent / ('_' + match.group('name')) if match else svg.parent


def fmt_mm(value: Decimal | float) -> str:
    """Enough decimal places for typical GRBL 0.02 mm and 0.1 mm steps."""
    return f'{float(value):.4f}'.rstrip('0').rstrip('.') or '0'


def _grayscale_svg_pixels(svg_source: Path, count_x: int, count_y: int,
                          *, invert: bool, mirror_x: bool) -> bytes:
    """Render antialiased SVG at the G-code X/Y sampling density.

    Do not use the 1-bit output PNG: its grayscale edge information
    has already been discarded by thresholding.
    """
    with pymupdf.open(svg_source) as svg:
        page = svg[0]
        width, height = page.rect.width, page.rect.height
        if width <= 0 or height <= 0:
            raise ValueError('SVG has an empty page rectangle')
        matrix = pymupdf.Matrix(count_x / width, count_y / height)
        pix = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csGRAY,
                             alpha=False)
        if pix.width != count_x or pix.height != count_y:
            raise ValueError('SVG grayscale raster size differs from NC grid')
        image = Image.frombytes('L', (count_x, count_y), pix.samples)
    if invert:
        image = ImageOps.invert(image)
    if mirror_x:
        image = ImageOps.mirror(image)
    return image.tobytes()


def _binary_png_pixels(png: Path) -> tuple[bytes, int, int]:
    with Image.open(png) as raw:
        gray = raw.convert('L')
        width, height = gray.size
        return gray.tobytes(), width, height


def generate_gcode(png: Path, width_mm: Decimal, height_mm: Decimal, *,
                   lines_per_mm: int = 10, feed: int = 1000, power: int = 1000,
                   mode: str = 'binary', svg_source: Path | None = None,
                   invert: bool = False, mirror_x: bool = False) -> Path:
    """Generate binary or grayscale raster G-code using the same X/Y pitch.

    Black -> full S, white -> S0. In grayscale mode antialiased SVG edges
    are mapped to intermediate laser powers. Rapid moves always have S0;
    rows are serpentine, starting from the page's lower-left corner.
    """
    if mode not in ('binary', 'grayscale'):
        raise ValueError('mode must be binary or grayscale')
    if lines_per_mm not in (10, 20):
        raise ValueError('lines_per_mm must be 10 or 20 (same for X and Y)')
    if not 1 <= feed <= 30000 or not 1 <= power <= 1000:
        raise ValueError('feed must be 1..30000 and power 1..1000; check GRBL $30')
    w, h = float(width_mm), float(height_mm)
    if not all(map(math.isfinite, (w, h))) or w <= 0 or h <= 0:
        raise ValueError('SVG physical dimensions must be positive and finite')
    count_x, count_y = math.ceil(w * lines_per_mm), math.ceil(h * lines_per_mm)
    if count_x * count_y > 12_000_000:
        raise ValueError('G-code raster exceeds 12 million cells; reduce lines_per_mm')

    if mode == 'grayscale':
        if svg_source is None:
            raise ValueError('grayscale requires the original SVG file')
        pixels = _grayscale_svg_pixels(svg_source, count_x, count_y,
                                      invert=invert, mirror_x=mirror_x)
        source_width = count_x
        source_height = count_y
    else:
        pixels, source_width, source_height = _binary_png_pixels(png)

    indices_x = ([min(source_width - 1, int((x + 0.5) * source_width /
                                          (w * lines_per_mm)))
                  for x in range(count_x)] if mode == 'binary'
                 else list(range(count_x)))
    widths = [fmt_mm(min(w, i / lines_per_mm)) for i in range(count_x + 1)]
    output = png.with_suffix('.nc')
    temporary = output.with_name(output.name + '.tmp')
    try:
        with temporary.open('w', encoding='ascii', newline='\n') as out:
            out.write('G21 (millimetres)\nG90 (absolute)\nG94 (feed per minute)\n')
            out.write('G0 X0 Y0\nM3 S0\n')
            for row in range(count_y):
                y_mm = row / lines_per_mm
                y = fmt_mm(y_mm)
                image_y = (count_y - row - 1 if mode == 'grayscale' else
                           min(source_height - 1, max(0, source_height - 1 -
                               int((y_mm + 0.5 / lines_per_mm) * source_height / h))))
                offset = image_y * source_width
                active_power = 0
                last_end = ''
                positions = (range(count_x - 1, -1, -1) if row % 2 else
                             range(count_x))
                for i in positions:
                    value = pixels[offset + indices_x[i]]
                    if mode == 'binary':
                        strength = power if value < 128 else 0
                    else:
                        strength = (power * (255 - value) + 127) // 255
                    start = widths[i + 1] if row % 2 else widths[i]
                    end = widths[i] if row % 2 else widths[i + 1]
                    if strength != active_power:
                        if active_power:
                            out.write(f'G1 X{last_end} F{feed} S{active_power}\n')
                            if not strength:
                                out.write('S0\n')
                        if strength and not active_power:
                            if start == end:
                                continue
                            out.write(f'G0 X{start} Y{y} S0\n')
                        active_power = strength
                    last_end = end
                if active_power:
                    out.write(f'G1 X{last_end} F{feed} S{active_power}\n')
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
                  quality: int, feed: int, power: int, mode: str = 'binary') -> None:
    header = ('G-code: horizontal bidirectional raster, black=laser ON, '
              'origin=lower left (X0 Y0), M3, no Z moves.\n'
              f'Raster mode: {mode}; density X=Y={quality} samples/mm; '
              f'pitch={fmt_mm(1 / quality)} mm; F{feed}; S{power}. '
              'Verify $30, $32, scale, orientation and laser polarity before running.\n\n')
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
              power: int, convert, combined_report, mode: str = 'binary') -> int:
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
            # Stage every generated file first: a failed SVG/NC conversion must
            # not overwrite a previously successful project output.
            with TemporaryDirectory(prefix='.laser-stage-', dir=target_dir) as stage_name:
                stage = Path(stage_name)
                result = convert(svg, dpi, threshold, invert, mirror_x, output_dir=stage)
                nc = generate_gcode(stage / result.image, result.width_mm,
                                    result.height_mm, lines_per_mm=lines_per_mm,
                                    feed=feed, power=power, mode=mode, svg_source=svg,
                                    invert=invert, mirror_x=mirror_x)
                for generated in (result.image, nc.name, result.guide):
                    (stage / generated).replace(target_dir / generated)
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
                          {r.source: '.' for r in rows}, lines_per_mm, feed, power, mode)
    write_summary(folder, all_results, all_errors, dpi, combined_report,
                  locations, lines_per_mm, feed, power, mode)
    print(f'Done: {len(all_results)} OK / {len(all_errors)} ERROR; output folders:',
          ', '.join(sorted({loc for loc in locations.values()})) or '(none)')
    return 1 if all_errors else 0
