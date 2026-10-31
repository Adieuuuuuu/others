#!/usr/bin/env python3
"""Inspect PPTX objects; patch explicit picture sources/crops and individual corners."""
import argparse
import hashlib
import io
import json
import math
import posixpath
import zipfile
from copy import deepcopy
from pathlib import Path

from lxml import etree as E
from PIL import Image

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
A, R = '{' + NS['a'] + '}', '{' + NS['r'] + '}'
PX = 9525


def digest(data):
    return hashlib.sha256(data).hexdigest()


def xml(data):
    return E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True))


def encoded(root):
    return E.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)


def rel_path(owner):
    parent, name = posixpath.split(owner)
    return posixpath.join(parent, '_rels', name + '.rels')


def resolve_target(rel_file, target):
    parent = posixpath.dirname(posixpath.dirname(rel_file))
    result = posixpath.normpath(target.lstrip('/') if target.startswith('/') else
                               posixpath.join(parent, target))
    if result == '..' or result.startswith('../') or '\\' in result:
        raise ValueError('Relationship target escapes the package.')
    return result


def relationships(parts, owner):
    name = rel_path(owner)
    root = xml(parts[name]) if name in parts else E.Element('{' + REL + '}Relationships', nsmap={None: REL})
    return name, root


def slide_parts(parts):
    root = xml(parts['ppt/presentation.xml'])
    name, rels = relationships(parts, 'ppt/presentation.xml')
    lookup = {r.get('Id'): r for r in rels}
    return [resolve_target(name, lookup[s.get(R + 'id')].get('Target'))
            for s in root.findall('p:sldIdLst/p:sldId', NS)]


def objects(root):
    return root.xpath('.//p:sp | .//p:pic', namespaces=NS)


def identity(obj):
    nv = obj.find('.//p:cNvPr', NS)
    return nv.get('id'), nv.get('name', '')


def frame(obj):
    xfrm = obj.find('p:spPr/a:xfrm', NS)
    if xfrm is None:
        raise ValueError('Object lacks an explicit local transform.')
    off, ext = xfrm.find('a:off', NS), xfrm.find('a:ext', NS)
    values = [int(off.get('x')), int(off.get('y')), int(ext.get('cx')), int(ext.get('cy'))]
    if min(values[2:]) <= 0:
        raise ValueError('Object must have positive dimensions.')
    return values


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def load_package(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) != len({i.filename for i in infos}):
            raise ValueError('Duplicate ZIP members are unsupported.')
        return {i.filename: z.read(i.filename) for i in infos}


def inspect(path, extract_dir):
    parts = load_package(path)
    size = xml(parts['ppt/presentation.xml']).find('p:sldSz', NS)
    result = {'source': str(path), 'sha256': digest(path.read_bytes()),
              'slide_size_px': [int(size.get(k)) / PX for k in ['cx', 'cy']], 'pages': []}
    exports = []
    for page, member in enumerate(slide_parts(parts), 1):
        root = xml(parts[member])
        relname, rels = relationships(parts, member)
        lookup = {r.get('Id'): r for r in rels}
        records = []
        for obj in objects(root):
            sid, name = identity(obj)
            try:
                bounds = [v / PX for v in frame(obj)]
            except ValueError:
                bounds = None
            record = {'shape_id': sid, 'shape_name': name, 'kind': E.QName(obj).localname,
                      'frame_px': bounds, 'grouped': any(x.tag == '{' + NS['p'] + '}grpSp' for x in obj.iterancestors())}
            geom = obj.find('p:spPr/a:prstGeom', NS)
            record['geometry'] = geom.get('prst') if geom is not None else 'custom_or_inherited'
            if geom is not None and geom.get('prst') == 'roundRect' and bounds:
                gd = geom.find('a:avLst/a:gd[@name="adj"]', NS)
                adj = int(gd.get('fmla').split()[-1]) if gd is not None else 16667
                record['uniform_radius_px'] = min(bounds[2:]) * adj / 100000
            blip = obj.find('p:blipFill/a:blip', NS)
            if blip is not None:
                rid = blip.get(R + 'embed') or blip.get(R + 'link')
                rel = lookup.get(rid)
                if rel is None:
                    raise ValueError('Missing picture relationship: ' + str(rid))
                record['external'] = rel.get('TargetMode') == 'External'
                if not record['external']:
                    media = resolve_target(relname, rel.get('Target'))
                    data = parts[media]
                    record.update(media=media, media_sha256=digest(data))
                    try:
                        with Image.open(io.BytesIO(data)) as image:
                            record['source_size_px'] = list(image.size)
                    except OSError:
                        record['source_size_px'] = None
                    if extract_dir:
                        suffix = posixpath.splitext(media)[1]
                        dest = extract_dir / f'page-{page:03}-shape-{sid}{suffix}'
                        exports.append((dest, data))
                        record['extracted_file'] = str(dest)
            records.append(record)
        result['pages'].append({'page': page, 'part': member, 'objects': records,
                               'text_node_count': len(root.findall('.//a:t', NS))})
    if any(p.exists() for p, _ in exports):
        raise FileExistsError('An extraction target already exists.')
    for dest, data in exports:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(data)
    result['slide_count'] = len(result['pages'])
    return result


def corner_geometry(w, h, radii):
    if not isinstance(radii, list) or len(radii) != 4 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or
            not 0 <= x <= min(w, h) / (2 * PX) for x in radii):
        raise ValueError('corners_px requires four finite radii in [0, half the shorter side].')
    def node(tag, **attrs):
        return E.Element(A + tag, {k: str(v) for k, v in attrs.items()})
    if not any(radii):
        geom = node('prstGeom', prst='rect')
        geom.append(node('avLst'))
        return geom
    tl, tr, br, bl = [round(x * PX) for x in radii]
    geom = node('custGeom')
    for tag in ['avLst', 'gdLst', 'ahLst', 'cxnLst']:
        geom.append(node(tag))
    geom.append(node('rect', l='0', t='0', r='w', b='h'))
    paths = node('pathLst'); geom.append(paths)
    path = node('path', w=w, h=h, fill='norm', stroke='true', extrusionOk='false'); paths.append(path)
    def point(tag, x, y):
        command = node(tag); command.append(node('pt', x=round(x), y=round(y))); path.append(command)
    def bezier(points):
        command = node('cubicBezTo')
        for x, y in points:
            command.append(node('pt', x=round(x), y=round(y)))
        path.append(command)
    k = .5522847498307936
    point('moveTo', tl, 0); point('lnTo', w-tr, 0)
    if tr: bezier([(w-tr+k*tr, 0), (w, tr-k*tr), (w, tr)])
    point('lnTo', w, h-br)
    if br: bezier([(w, h-br+k*br), (w-br+k*br, h), (w-br, h)])
    point('lnTo', bl, h)
    if bl: bezier([(bl-k*bl, h), (0, h-bl+k*bl), (0, h-bl)])
    point('lnTo', 0, tl)
    if tl: bezier([(0, tl-k*tl), (tl-k*tl, 0), (tl, 0)])
    path.append(node('close'))
    return geom


def cover_crop(fill, sw, sh, w, h):
    rect = fill.find('a:srcRect', NS)
    if rect is None:
        rect = E.Element(A + 'srcRect'); fill.insert(1, rect)
    source, target = sw / sh, w / h
    lr = round((1-target/source)*50000) if source > target else 0
    tb = round((1-source/target)*50000) if source <= target else 0
    rect.attrib.clear()
    rect.attrib.update({k: str(v) for k, v in [('l', lr), ('t', tb), ('r', lr), ('b', tb)]})
    for tile in fill.findall('a:tile', NS):
        fill.remove(tile)
    stretch = fill.find('a:stretch', NS)
    if stretch is None:
        stretch = E.SubElement(fill, A + 'stretch')
    stretch.clear(); E.SubElement(stretch, A + 'fillRect')


def patch(source, manifest_path, output):
    if source == output or output.exists() or output.suffix.lower() != '.pptx':
        raise ValueError('Output must be a new PPTX distinct from source.')
    spec = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    source_hash = digest(source.read_bytes())
    if spec.get('expected_source_sha256', source_hash) != source_hash:
        raise ValueError('Source SHA-256 does not match the manifest.')
    edits = spec.get('objects')
    if not isinstance(edits, list) or not edits:
        raise ValueError('objects must be a non-empty array.')
    original = load_package(source); parts = dict(original)
    members = slide_parts(parts)
    roots, old_roots, rel_roots, selected, old_rids = {}, {}, {}, {}, {}
    new_assets, replaced_media, records = {}, set(), []
    types = xml(parts['[Content_Types].xml'])
    for edit in edits:
        page = edit.get('page')
        if type(page) is not int or not 1 <= page <= len(members):
            raise ValueError('Invalid 1-based page number.')
        member = members[page-1]
        if member not in roots:
            roots[member] = xml(parts[member]); old_roots[member] = deepcopy(roots[member])
            rel_roots[member] = relationships(parts, member)
            selected[member], old_rids[member] = {}, set()
        root = roots[member]
        matches = [obj for obj in objects(root) if
                   (str(edit['shape_id']) == identity(obj)[0] if 'shape_id' in edit else
                    'shape_name' in edit and edit['shape_name'] == identity(obj)[1])]
        if len(matches) != 1:
            raise ValueError('Object selector must match exactly one object on page ' + str(page))
        obj = matches[0]; sid, name = identity(obj)
        if sid in selected[member]:
            raise ValueError('Object selected more than once.')
        if any(x.tag == '{' + NS['p'] + '}grpSp' for x in obj.iterancestors()):
            raise ValueError('Grouped objects require authoring-tool group transform handling.')
        if not any(k in edit for k in ['image', 'corners_px']):
            raise ValueError('Each object needs image and/or corners_px.')
        selected[member][sid] = edit
        x, y, w, h = frame(obj)
        record = {'page': page, 'shape_id': sid, 'shape_name': name}
        if 'image' in edit:
            if obj.tag != '{' + NS['p'] + '}pic' or edit.get('fit', 'cover') != 'cover':
                raise ValueError('Only picture objects and cover fitting are supported.')
            image_path = (manifest_path.parent / edit['image']).resolve(strict=True)
            data = image_path.read_bytes(); key = digest(data)
            with Image.open(io.BytesIO(data)) as image:
                sw, sh = image.size
                if image.format not in ['PNG', 'JPEG']:
                    raise ValueError('New images must be PNG or JPEG.')
                extension, content_type = ('.png', 'image/png') if image.format == 'PNG' else ('.jpg', 'image/jpeg')
            if key not in new_assets:
                n = 1
                while f'ppt/media/replica-{n}{extension}' in parts: n += 1
                media = f'ppt/media/replica-{n}{extension}'
                parts[media] = data; new_assets[key] = media
                if not any(t.get('Extension') == extension[1:] for t in types):
                    E.SubElement(types, '{' + CT + '}Default', Extension=extension[1:], ContentType=content_type)
            media = new_assets[key]
            relname, rels = rel_roots[member]
            fill = obj.find('p:blipFill', NS); blip = fill.find('a:blip', NS)
            old_rid = blip.get(R + 'embed') or blip.get(R + 'link')
            old_rel = next((r for r in rels if r.get('Id') == old_rid), None)
            if old_rel is None: raise ValueError('Missing old picture relationship.')
            if old_rel.get('TargetMode') != 'External':
                replaced_media.add(resolve_target(relname, old_rel.get('Target')))
            old_rids[member].add(old_rid)
            ids = {r.get('Id') for r in rels}; n = 1
            while f'rIdReplica{n}' in ids: n += 1
            rid = f'rIdReplica{n}'
            E.SubElement(rels, '{' + REL + '}Relationship', Id=rid,
                         Type=NS['r'] + '/image', Target='/' + media)
            blip.attrib.pop(R + 'link', None); blip.set(R + 'embed', rid)
            cover_crop(fill, sw, sh, w, h)
            record.update(image_sha256=key, image_size_px=[sw, sh], media=media)
        if 'corners_px' in edit:
            prop = obj.find('p:spPr', NS)
            geom = corner_geometry(w, h, edit['corners_px'])
            for old in list(prop):
                if old.tag in [A + 'prstGeom', A + 'custGeom']: prop.remove(old)
            position = 1 if prop.find('a:xfrm', NS) is not None else 0
            prop.insert(position, geom)
            record['corners_px'] = edit['corners_px']
        records.append(record)
    for member, root in roots.items():
        # Check all visible XML except the explicitly selected image/geometry fields.
        comparisons = [deepcopy(old_roots[member]), deepcopy(root)]
        for tree in comparisons:
            for obj in objects(tree):
                edit = selected[member].get(identity(obj)[0])
                if not edit: continue
                if 'image' in edit:
                    fill = obj.find('p:blipFill', NS); obj.remove(fill)
                if 'corners_px' in edit:
                    prop = obj.find('p:spPr', NS)
                    for geom in list(prop):
                        if geom.tag in [A+'prstGeom', A+'custGeom']: prop.remove(geom)
        if E.tostring(comparisons[0], method='c14n') != E.tostring(comparisons[1], method='c14n'):
            raise ValueError('Unexpected non-target object change.')
        used = {value for element in root.iter() for attr, value in element.attrib.items() if attr.startswith(R)}
        relname, rels = rel_roots[member]
        for rel in list(rels):
            if rel.get('Id') in old_rids[member] and rel.get('Id') not in used: rels.remove(rel)
        parts[member] = encoded(root)
        if old_rids[member]:
            parts[relname] = encoded(rels)
    targets = {resolve_target(name, rel.get('Target')) for name, data in parts.items() if name.endswith('.rels')
               for rel in xml(data) if rel.get('TargetMode') != 'External'}
    removed = []
    for media in replaced_media:
        if media.startswith('ppt/media/') and media not in targets:
            parts.pop(media, None); removed.append(media)
            for entry in list(types):
                if entry.get('PartName') == '/' + media: types.remove(entry)
    if new_assets or removed: parts['[Content_Types].xml'] = encoded(types)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items(): z.writestr(name, data)
    changed = [name for name in sorted(set(original) | set(parts)) if original.get(name) != parts.get(name)]
    return {'status': 'pass', 'source_sha256': source_hash, 'output': str(output),
            'output_sha256': digest(output.read_bytes()), 'objects': records,
            'changed_parts': changed, 'removed_unreferenced_replaced_media': sorted(removed),
            'only_requested_picture_and_geometry_fields_changed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('inspect'); check.add_argument('source', type=Path)
    check.add_argument('--out', type=Path); check.add_argument('--extract-dir', type=Path)
    change = sub.add_parser('patch'); change.add_argument('source', type=Path)
    change.add_argument('--manifest', type=Path, required=True)
    change.add_argument('--output', type=Path, required=True); change.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        source = args.source.resolve(strict=True)
        report = args.out if args.command == 'inspect' else args.report
        if report and report.exists(): raise FileExistsError('Report already exists.')
        if args.command == 'inspect':
            result = inspect(source, args.extract_dir.resolve() if args.extract_dir else None)
        else:
            if report and report.resolve() == args.output.resolve():
                raise ValueError('Report and output must be different paths.')
            result = patch(source, args.manifest.resolve(strict=True), args.output.resolve())
        if report: write_json(report.resolve(), result)
        print(json.dumps(result if not report else {'status': 'pass', 'report': str(report.resolve())}, ensure_ascii=True))
    except (ValueError, KeyError, FileExistsError, FileNotFoundError, ImportError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
