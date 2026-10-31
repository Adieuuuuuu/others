#!/usr/bin/env python3
"""Inspect image/PDF references, render PDF pages, and crop original pixels."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from PIL import Image


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(path):
    if path.suffix.lower() != '.pdf':
        with Image.open(path) as image:
            return {'kind': 'image', 'path': str(path), 'sha256': sha(path),
                    'size_px': list(image.size), 'format': image.format,
                    'exif_orientation': image.getexif().get(274, 1)}
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError('Encrypted PDF: provide an accessible copy.')
    pages = []
    for number, page in enumerate(reader.pages, 1):
        chars, images = len((page.extract_text() or '').strip()), len(page.images)
        hint = 'raster_candidate' if chars < 20 and images else (
            'text_or_vector_candidate' if chars >= 20 else 'visual_inspection_required')
        pages.append({'page': number, 'size_pt': [float(page.mediabox.width),
                      float(page.mediabox.height)], 'text_char_count': chars,
                      'image_count': images, 'hint': hint})
    return {'kind': 'pdf', 'path': str(path), 'sha256': sha(path),
            'page_count': len(pages), 'pages': pages,
            'note': 'Heuristic hints only; inspect renders. No OCR performed.'}


def page_numbers(spec, count):
    if not spec:
        return list(range(1, count + 1))
    result = []
    for part in spec.split(','):
        if not re.fullmatch(r'\d+(?:-\d+)?', part):
            raise ValueError('Pages must use 1-based numbers/ranges: 1,3-4.')
        bounds = [int(x) for x in part.split('-')]
        start, end = bounds[0], bounds[-1]
        if not 1 <= start <= end <= count:
            raise ValueError('Page range is outside the PDF.')
        result.extend(range(start, end + 1))
    if len(result) != len(set(result)):
        raise ValueError('Duplicate page selections.')
    return result


def render(path, out_dir, dpi, pages):
    import pypdfium2 as pdfium
    if path.suffix.lower() != '.pdf':
        raise ValueError('render requires a PDF.')
    if not 32 <= dpi <= 600:
        raise ValueError('DPI must be between 32 and 600.')
    document = pdfium.PdfDocument(path)
    try:
        selected = page_numbers(pages, len(document))
        outputs = [out_dir / f'page-{n:03}.png' for n in selected]
        if any(p.exists() for p in outputs):
            raise FileExistsError('A selected render output already exists.')
        out_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for n, output in zip(selected, outputs):
            page, bitmap = document[n - 1], None
            try:
                bitmap = page.render(scale=dpi / 72)
                image = bitmap.to_pil()
                with output.open('xb') as stream:
                    image.save(stream, format='PNG')
                records.append({'page': n, 'file': str(output),
                                'size_px': list(image.size), 'sha256': sha(output)})
            finally:
                if bitmap is not None:
                    bitmap.close()
                page.close()
        return {'source': str(path), 'source_sha256': sha(path), 'dpi': dpi,
                'pages': records}
    finally:
        document.close()


def crop(path, regions_path, out_dir):
    regions = json.loads(regions_path.read_text(encoding='utf-8-sig'))
    if not isinstance(regions, list) or not regions:
        raise ValueError('regions must be a non-empty JSON array.')
    with Image.open(path) as image:
        records, outputs, ids = [], [], set()
        for region in regions:
            name = region.get('id', '')
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
                raise ValueError('Region IDs must be safe filename stems.')
            if name in ids:
                raise ValueError('Duplicate region ID: ' + name)
            ids.add(name)
            box = region.get('bbox')
            if not isinstance(box, list) or len(box) != 4 or any(type(x) is not int for x in box):
                raise ValueError('bbox must contain four integer pixel coordinates.')
            left, top, right, bottom = box
            if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
                raise ValueError('Crop is outside source image: ' + name)
            output = out_dir / (name + '.png')
            if output.exists() or output.resolve() == path:
                raise FileExistsError('Crop output exists or equals source: ' + str(output))
            outputs.append((region, output))
        out_dir.mkdir(parents=True, exist_ok=True)
        for region, output in outputs:
            cropped = image.crop(region['bbox'])
            with output.open('xb') as stream:
                cropped.save(stream, format='PNG')
            records.append({'id': region['id'], 'bbox': region['bbox'], 'file': str(output),
                            'size_px': list(cropped.size), 'sha256': sha(output)})
    return {'source': str(path), 'source_sha256': sha(path), 'crops': records,
            'note': 'Original pixels cropped without resampling or source mutation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('inspect')
    check.add_argument('source', type=Path)
    render_cmd = sub.add_parser('render')
    render_cmd.add_argument('source', type=Path)
    render_cmd.add_argument('--out-dir', type=Path, required=True)
    render_cmd.add_argument('--dpi', type=int, default=144)
    render_cmd.add_argument('--pages')
    crop_cmd = sub.add_parser('crop')
    crop_cmd.add_argument('source', type=Path)
    crop_cmd.add_argument('--regions', type=Path, required=True)
    crop_cmd.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        source = args.source.resolve(strict=True)
        if args.command == 'inspect':
            result = inspect(source)
        elif args.command == 'render':
            result = render(source, args.out_dir.resolve(), args.dpi, args.pages)
        else:
            result = crop(source, args.regions.resolve(strict=True), args.out_dir.resolve())
        print(json.dumps(result, ensure_ascii=True))
    except (ValueError, FileExistsError, FileNotFoundError, ImportError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
