#!/usr/bin/env python3
"""KiCad SVG -> 1-bit-looking RGB PNG for LaserGRBL, with per-board TXT size guides.

Requirements: PyMuPDF, Pillow. Never crops and never assumes unspecified SVG units.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET

import pymupdf
from PIL import Image, ImageOps

MM_PER_INCH = Decimal('25.4')
UNITS = {
    'mm': Decimal(1), 'cm': Decimal(10), 'in': MM_PER_INCH,
    'pt': MM_PER_INCH / Decimal(72), 'pc': MM_PER_INCH / Decimal(6),
    'q': Decimal('0.25'),
}
LENGTH_RE = re.compile(r'^\s*(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?\s*([A-Za-z]*)\s*$')
REPORT_NAME = 'LASERGRBL_SETTINGS.txt'


@dataclass
class Result:
    source: str
    image: str
    guide: str
    width_mm: Decimal
    height_mm: Decimal
    pixels_w: int
    pixels_h: int
    dpi: int
    diff_w_mm: Decimal
    diff_h_mm: Decimal
    lasergrbl_h_if_w_mm: Decimal
    lasergrbl_h_error_mm: Decimal
    inverted: bool
    mirrored: bool


def parse_length(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    match = LENGTH_RE.fullmatch(raw)
    if not match:
        return None
    number, power, unit = match.groups()
    multiplier = UNITS.get(unit.lower())
    if multiplier is None:
        return None
    value = Decimal(number)
    if power:
        value *= Decimal(10) ** int(power)
    return value * multiplier


def svg_mm(path: Path) -> tuple[Decimal, Decimal]:
    root = ET.parse(path).getroot()
    if root.tag.rsplit('}', 1)[-1] != 'svg':
        raise ValueError('Файл не является SVG')
    w, h = parse_length(root.get('width')), parse_length(root.get('height'))
    if w is None or h is None or w <= 0 or h <= 0:
        raise ValueError('Нет корректных физических размеров SVG (mm/cm/in/pt). Экспортируйте в KiCad с Fit page to board.')
    return w, h


def pixel_dims(width_mm: Decimal, height_mm: Decimal, dpi: int) -> tuple[int, int]:
    """Pick ~DPI raster dimensions with best feasible aspect ratio for LaserGRBL.

    LaserGRBL locks W/H ratio. Prefer a nearby pixel grid preserving SVG ratio
    rather than independently rounding axes with up to half-pixel ratio error.
    The ±1-pixel search keeps the effective pixel density close to chosen DPI.
    """
    ppm = Decimal(dpi) / MM_PER_INCH
    nominal_w = width_mm * ppm
    nominal_h = height_mm * ppm
    base_w = int(nominal_w.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    base_h = int(nominal_h.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    options = []
    for px_w in range(max(1, base_w - 1), base_w + 2):
        for px_h in range(max(1, base_h - 1), base_h + 2):
            # Candidate axes must be no more than 1.25 px from nominal size.
            if abs(Decimal(px_w) - nominal_w) > Decimal('1.25'):
                continue
            if abs(Decimal(px_h) - nominal_h) > Decimal('1.25'):
                continue
            ratio_error = abs(width_mm * Decimal(px_h) / Decimal(px_w) - height_mm)
            density_deviation = abs(Decimal(px_w) - nominal_w) + abs(Decimal(px_h) - nominal_h)
            options.append((ratio_error, density_deviation, px_w, px_h))
    if not options:
        return base_w, base_h
    _, _, px_w, px_h = min(options)
    return px_w, px_h


def ru(value: Decimal, digits: int = 4) -> str:
    return f'{value:.{digits}f}'.replace('.', ',')


def guide_text(r: Result) -> str:
    color = 'ИНВЕРСИЯ ВКЛЮЧЕНА' if r.inverted else 'без инверсии'
    mirror = 'ГОРИЗОНТАЛЬНОЕ ЗЕРКАЛО ВКЛЮЧЕНО' if r.mirrored else 'без зеркалирования'
    return f'''НАСТРОЙКИ LaserGRBL 4.9.4 — плата из KiCad
====================================================
Исходный SVG:  {r.source}
Готовый PNG:   {r.image}

1. РАЗМЕР, ЭКСПОРТИРОВАННЫЙ KICAD
   Ширина SVG:   {ru(r.width_mm)} мм
   Высота SVG:   {ru(r.height_mm)} мм
   Это размеры всей страницы SVG. Если KiCad добавил поля, они входят в размер.

2. ЧТО ВВЕСТИ В LASERGRBL
   File -> Open File -> {r.image}
   В окне Import Raster Image:
     Conversion Tool: Line To Line Tracing (для чёрно-белого растра)
     Resize: Nearest Neighbour (если доступен)
     Не обрезать, не поворачивать и не зеркалировать повторно.
     Quality: ориентировочно {ru(Decimal(r.dpi) / MM_PER_INCH, 2)} lines/mm (шаг ~{ru(MM_PER_INCH / Decimal(r.dpi), 4)} мм).
     Это стартовая настройка; подберите под пятно лазера и материал.
   Нажмите Next -> Target Image -> Image Size and Position [mm]:
     Autosize: ВЫКЛЮЧИТЬ (снять галочку)
     Size W:   {ru(r.width_mm)} мм   <-- ВВЕСТИ ВРУЧНУЮ
     Size H:   примерно {ru(r.lasergrbl_h_if_w_mm)} мм (выставится автоматически)
     Исходная высота KiCad: {ru(r.height_mm)} мм
     Offset X/Y: выбрать под положение заготовки на столе.

   ВНИМАНИЕ: LaserGRBL фиксирует соотношение сторон PNG.
   После ввода W программа может изменить H. Разница с исходным SVG
   по высоте: {ru(r.lasergrbl_h_error_mm, 4)} мм (знак сохранён).
   Если введёте H самостоятельно, может измениться W.

3. ИЗОБРАЖЕНИЕ
   Размер PNG:    {r.pixels_w} x {r.pixels_h} пикселей
   Записанный DPI: {r.dpi}
   При обычном чтении только из DPI приблизительный размер:
     {ru(Decimal(r.pixels_w) * MM_PER_INCH / Decimal(r.dpi))} x {ru(Decimal(r.pixels_h) * MM_PER_INCH / Decimal(r.dpi))} мм
   Поэтому рекомендуется ручной ввод W (см. выше), а не Autosize.
   Флаги: {color}; {mirror}.
   ЧЁРНОЕ = лазер работает; БЕЛОЕ = лазер выключен (для стандартной интерпретации LaserGRBL).
   Полярность слоя Cu/Mask и необходимость зеркалирования проверьте по технологии платы.

4. ДО НАЧАЛА ГРАВИРОВКИ
   Скорость, S-MAX и режим M3/M4 — только по результатам проб на материале.
   Сверьте $100/$101 (шагов/мм) в GRBL, сделайте тест рамки/контрольного размера.
   Размер в файле НЕ гарантирует механическую точность CNC3018.
   При запуске нового материала проверьте направление и габариты движения.
'''


def convert(path: Path, dpi: int, threshold: int, invert: bool, mirror_x: bool) -> Result:
    w_mm, h_mm = svg_mm(path)
    px_w, px_h = pixel_dims(w_mm, h_mm, dpi)
    if px_w < 1 or px_h < 1 or px_w * px_h > 120_000_000:
        raise ValueError('Размер PNG недопустим или более 120 млн пикселей')

    with pymupdf.open(path) as svg:
        page = svg[0]
        page_w_pt, page_h_pt = page.rect.width, page.rect.height
        if page_w_pt <= 0 or page_h_pt <= 0:
            raise ValueError('SVG имеет пустую область страницы')
        measured_w = Decimal(str(page_w_pt)) * MM_PER_INCH / Decimal(72)
        measured_h = Decimal(str(page_h_pt)) * MM_PER_INCH / Decimal(72)
        if abs(measured_w - w_mm) > Decimal('0.01') or abs(measured_h - h_mm) > Decimal('0.01'):
            raise ValueError(f'Несовпадение единиц SVG: исходный {w_mm} x {h_mm} мм, рендерер {measured_w:.4f} x {measured_h:.4f} мм')
        matrix = pymupdf.Matrix(px_w / page_w_pt, px_h / page_h_pt)
        pixmap = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csGRAY, alpha=False)
        if pixmap.width != px_w or pixmap.height != px_h:
            raise ValueError(f'Сбой размеров растра: ожидалось {px_w}x{px_h}, получено {pixmap.width}x{pixmap.height}')
        gray = Image.frombytes('L', (pixmap.width, pixmap.height), pixmap.samples)

    mono = gray.point(lambda v: 255 if v >= threshold else 0)
    if invert:
        mono = ImageOps.invert(mono)
    if mirror_x:
        mono = ImageOps.mirror(mono)
    output = path.with_name(path.stem + '_laser.png')
    mono.save(output, 'PNG', dpi=(dpi, dpi), optimize=True)

    ppm = Decimal(dpi) / MM_PER_INCH
    h_if_w = w_mm * Decimal(px_h) / Decimal(px_w)
    report = path.with_name(path.stem + '_laser_settings.txt')
    result = Result(
        path.name, output.name, report.name, w_mm, h_mm, px_w, px_h, dpi,
        Decimal(px_w) / ppm - w_mm,
        Decimal(px_h) / ppm - h_mm,
        h_if_w, h_if_w - h_mm, invert, mirror_x,
    )
    report.write_text(guide_text(result), encoding='utf-8-sig')
    return result


def combined_report(results: list[Result], errors: list[tuple[str, str]], dpi: int) -> str:
    lines = [
        'LaserGRBL 4.9.4 — размеры для каждой платы из KiCad',
        '===================================================',
        f'Обработано: {len(results)}. Ошибок: {len(errors)}. DPI: {dpi}',
        '',
        'File -> Open File -> нужный *_laser.png',
        'В окне Target Image: снять Autosize, вписать Size W, проверить Size H.',
        'LaserGRBL блокирует пропорции, поэтому H может немного отличаться от исходного SVG.',
        'У каждого PNG есть отдельный *_laser_settings.txt с полной инструкцией.',
        '',
    ]
    for i, r in enumerate(results, 1):
        lines.extend([
            f'{i}. {r.image}',
            f'   Исходный SVG: {r.source}',
            f'   ВВЕСТИ Size W: {ru(r.width_mm)} мм',
            f'   ПРОВЕРИТЬ Size H: ~{ru(r.lasergrbl_h_if_w_mm)} мм',
            f'   Высота KiCad: {ru(r.height_mm)} мм; расхождение: {ru(r.lasergrbl_h_error_mm)} мм',
            f'   Пиксели: {r.pixels_w} x {r.pixels_h}; TXT: {r.guide}',
            '',
        ])
    if errors:
        lines.extend(['ОШИБКИ:', *[f'  {name}: {error}' for name, error in errors], ''])
    lines.extend([
        'ВАЖНО:',
        'Не применяйте автоматическую обрезку, масштабирование, поворот или зеркало.',
        'Зеркалирование и полярность выбирайте отдельно под технологию изготовления.',
        'Размер SVG может включать поля страницы, если в KiCad не включена подгонка к плате.',
        'Скорость и мощность лазера подбираются тестом — этот файл их не задаёт.',
        'Механическая точность зависит от калибровки CNC3018 и пятна лазера.',
        '',
    ])
    return '\n'.join(lines)


def cli() -> int:
    parser = argparse.ArgumentParser(description='KiCad SVG -> LaserGRBL PNG + TXT report')
    parser.add_argument('--folder', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--dpi', type=int, default=508)
    parser.add_argument('--threshold', type=int, default=128)
    parser.add_argument('--invert', type=int, choices=[0, 1], default=0)
    parser.add_argument('--mirror-x', type=int, choices=[0, 1], default=0)
    args = parser.parse_args()
    if not 1 <= args.dpi <= 5000 or not 0 <= args.threshold <= 255:
        parser.error('dpi 1..5000; threshold 0..255')
    folder = args.folder.resolve()
    if not folder.is_dir():
        parser.error('folder does not exist')

    files = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.svg'),
        key=lambda p: p.name.casefold(),
    )
    print(f'Found {len(files)} SVG(s). DPI {args.dpi}. Folder: {folder}')
    results: list[Result] = []
    errors: list[tuple[str, str]] = []
    for i, path in enumerate(files, 1):
        print(f'[{i}/{len(files)}] {path.name}')
        try:
            r = convert(path, args.dpi, args.threshold, bool(args.invert), bool(args.mirror_x))
            results.append(r)
            print(f'  OK: {r.image} [{r.pixels_w}x{r.pixels_h}]')
            print(f'  LASERGRBL: Autosize OFF, Size W={ru(r.width_mm)} mm, H~{ru(r.lasergrbl_h_if_w_mm)} mm')
            print(f'  REPORT: {r.guide}')
        except (OSError, ValueError, ET.ParseError, InvalidOperation, RuntimeError) as exc:
            errors.append((path.name, str(exc)))
            print(f'  ERROR: {exc}')
        except Exception as exc:
            errors.append((path.name, f'{type(exc).__name__}: {exc}'))
            print(f'  ERROR: {type(exc).__name__}: {exc}')

    (folder / REPORT_NAME).write_text(combined_report(results, errors, args.dpi), encoding='utf-8-sig')
    with (folder / 'lasergrbl_sizes.csv').open('w', encoding='utf-8-sig', newline='') as f:
        wr = csv.writer(f, delimiter=';')
        wr.writerow(['SVG', 'PNG', 'Guide_TXT', 'SVG_W_mm', 'SVG_H_mm', 'PNG_PX_W', 'PNG_PX_H', 'DPI', 'H_if_W_entered_mm', 'H_delta_mm', 'Status'])
        for r in results:
            wr.writerow([r.source, r.image, r.guide, str(r.width_mm), str(r.height_mm), r.pixels_w, r.pixels_h, r.dpi, f'{r.lasergrbl_h_if_w_mm:.6f}', f'{r.lasergrbl_h_error_mm:+.6f}', 'OK'])
        for name, error in errors:
            wr.writerow([name, '', '', '', '', '', '', '', '', '', 'ERROR: ' + error])

    print(f'\nDone: {len(results)} OK / {len(errors)} ERROR. Open {REPORT_NAME}')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(cli())