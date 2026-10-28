"""Apple spatial HEIC packaging without Apple frameworks.

HEVC encoding is performed by pillow-heif/libheif. The HEIF stereo group and
Apple UUID camera properties follow ImageIO output. Field encodings are also
documented by strukturag/libheif box.cc (cmin/cmex). No reference image is needed
at runtime. Meta is relocated to EOF, preserving every original media offset.
"""
import io
import math
import struct
from pathlib import Path

import pillow_heif

INTRINSICS = bytes.fromhex('22cc04c7d6d94e079d904eb6ecbaf3a3')
EXTRINSICS = bytes.fromhex('4363e9145b7d4aab97aebea69803b434')
DISPARITY = bytes.fromhex('de22508536cb436587432f8705e7c78a')


def box(kind, payload):
    return struct.pack('>I4s', len(payload) + 8, kind) + payload


def boxes(data):
    """Return (type, payload, original bytes, offset); reject truncated boxes."""
    p = 0
    while p < len(data):
        if len(data) - p < 8:
            raise ValueError('Truncated box header')
        size, kind = struct.unpack_from('>I4s', data, p)
        header = 8
        if size == 1:
            size = struct.unpack_from('>Q', data, p + 8)[0]
            header = 16
        elif size == 0:
            size = len(data) - p
        if size < header or p + size > len(data):
            raise ValueError('Invalid box length')
        yield kind, data[p+header:p+size], data[p:p+size], p
        p += size


def child(data, kind):
    found = [p for k, p, _, _ in boxes(data) if k == kind]
    if len(found) != 1:
        raise ValueError(f'Expected one {kind!r}, found {len(found)}')
    return found[0]


def associations(payload):
    version = payload[0]
    flags = int.from_bytes(payload[1:4], 'big')
    count = int.from_bytes(payload[4:8], 'big')
    p, result = 8, {}
    for _ in range(count):
        size = 2 if version == 0 else 4
        item = int.from_bytes(payload[p:p+size], 'big')
        n = payload[p+size]
        p += size + 1
        values = []
        for _ in range(n):
            size = 2 if flags & 1 else 1
            value = int.from_bytes(payload[p:p+size], 'big')
            p += size
            mask = 0x8000 if size == 2 else 0x80
            values.append((value & (mask-1), bool(value & mask)))
        result[item] = values
    if p != len(payload):
        raise ValueError('Malformed ipma')
    return result


def write_associations(entries):
    # Version 1: 32-bit item IDs; flags 1: 15-bit property indices.
    out = struct.pack('>II', 0x01000001, len(entries))
    for item, values in entries.items():
        out += struct.pack('>IB', item, len(values))
        for index, essential in values:
            out += struct.pack('>H', index | (0x8000 if essential else 0))
    return box(b'ipma', out)


def image_ids(meta):
    inf = child(meta[4:], b'iinf')
    items = []
    for _, p, _, _ in boxes(inf[6 if inf[0] == 0 else 8:]):
        if p[0] != 2:
            raise ValueError('Unsupported infe version')
        item = int.from_bytes(p[4:6], 'big')
        kind = p[8:12]
        hidden = int.from_bytes(p[1:4], 'big') & 1
        if not hidden and kind in (b'hvc1', b'grid'):
            items.append(item)
    return items


def package_stereo(encoded, hfov, baseline_mm, disparity):
    if not 0 < hfov < 180 or not 0 < baseline_mm < 10000 or not -1 <= disparity <= 1:
        raise ValueError('Invalid spatial parameters')
    meta = child(encoded, b'meta')
    ids = image_ids(meta)
    if len(ids) != 2:
        raise ValueError(f'Expected exactly two top-level images, got {ids}')
    iprp = child(meta[4:], b'iprp')
    props = [raw for _, _, raw, _ in boxes(child(iprp, b'ipco'))]
    assoc = associations(child(iprp, b'ipma'))
    group_id = max(assoc) + 1

    def add(uuid, data):
        props.append(box(b'uuid', uuid + data))
        return len(props)

    # cmin: relative focal length fx/width, cx/width, cy/height in signed Q30.
    focal = 0.5 / math.tan(math.radians(hfov) / 2)
    shift = min(30, max(0, int(math.floor(math.log2((2**31-1)/max(focal, .5))))))
    intrinsic = add(INTRINSICS, struct.pack('>Iiii', shift << 8,
                    round(focal * 2**shift), round(.5 * 2**shift), round(.5 * 2**shift)))
    left = add(EXTRINSICS, struct.pack('>I', 0x10))
    # cmex positions are signed micrometres, not mm or metres.
    right = add(EXTRINSICS, struct.pack('>Ii', 0x11, round(baseline_mm * 1000)))
    disp = add(DISPARITY, struct.pack('>i', round(disparity * 10000)))
    for item, extrinsic in zip(ids, (left, right)):
        assoc[item] += [(intrinsic, False), (extrinsic, False), (disp, False)]
    assoc[group_id] = [(disp, False)]
    new_iprp = box(b'iprp', box(b'ipco', b''.join(props)) + write_associations(assoc))
    group = box(b'grpl', box(b'ster', struct.pack('>IIIII', 0, group_id, 2, *ids)))
    new_meta = box(b'meta', meta[:4] + b''.join(
        new_iprp if k == b'iprp' else raw for k, _, raw, _ in boxes(meta[4:])) + group)
    # Preserve file-relative iloc offsets by replacing original meta with free.
    return b''.join(box(b'free', bytes(len(p))) if k == b'meta' else raw
                    for k, p, raw, _ in boxes(encoded)) + new_meta


def save_spatial(left, right, path, hfov, baseline_mm, disparity=.02, quality=92):
    if left.size != right.size:
        raise ValueError('Eye dimensions differ')
    h = pillow_heif.from_pillow(left)
    h.add_from_pillow(right)
    buffer = io.BytesIO()
    h.save(buffer, quality=quality, chroma='420')
    Path(path).write_bytes(package_stereo(buffer.getvalue(), hfov, baseline_mm, disparity))


def inspect_spatial(path):
    data = Path(path).read_bytes()
    meta = child(data, b'meta')
    iprp = child(meta[4:], b'iprp')
    props = list(boxes(child(iprp, b'ipco')))
    assoc = associations(child(iprp, b'ipma'))
    ster = child(child(meta[4:], b'grpl'), b'ster')
    _, group, count = struct.unpack_from('>III', ster)
    if count != 2:
        raise ValueError('Stereo group must have two eyes')
    ids = struct.unpack_from('>II', ster, 12)
    if list(ids) != image_ids(meta):
        raise ValueError('Stereo group image order mismatch')
    cameras = []
    for item in ids:
        values = {p[:16]: p[16:] for index, _ in assoc[item]
                  for k, p, _, _ in [props[index-1]] if k == b'uuid'}
        flags, fx, cx, cy = struct.unpack('>Iiii', values[INTRINSICS])
        factor = 2**((flags >> 8) & 31)
        focal = fx / factor
        e = values[EXTRINSICS]
        ef = int.from_bytes(e[:4], 'big')
        x = struct.unpack('>i', e[4:8])[0] / 1000 if ef & 1 else 0.0
        cameras.append({'item_id': item, 'hfov': math.degrees(2*math.atan(.5/focal)),
                        'position_mm': x, 'principal_point_relative': [cx/factor, cy/factor],
                        'disparity': struct.unpack('>i', values[DISPARITY])[0]/10000})
    group_props = [props[i-1][1] for i, _ in assoc[group]]
    if not any(p.startswith(DISPARITY) for p in group_props):
        raise ValueError('Stereo group lacks disparity')
    decoded = pillow_heif.open_heif(path)
    if len(decoded) != 2 or decoded[0].size != decoded[1].size:
        raise ValueError('Invalid decoded eye count/dimensions')
    # Force both bitstreams to be fully decoded, not just read headers.
    for eye in decoded:
        if len(eye.data) != eye.stride * eye.size[1]:
            raise ValueError('Invalid decoded pixel data')
    # Independently parsed by native libheif, not our box parser above.
    native_groups = decoded.info.get('entity_groups', [])
    if not any(g['type']=='ster' and g['entities']==list(ids) for g in native_groups):
        raise ValueError('libheif did not recognize the stereo group')
    native_cameras = []
    for eye, expected in zip(decoded, cameras):
        native = eye.info.get('heif', {})
        intr = native.get('camera_intrinsic_matrix')
        rotation = native.get('camera_extrinsic_matrix_rot')
        if not intr or not rotation:
            raise ValueError('libheif did not recognize camera properties')
        expected_fx = eye.size[0]/(2*math.tan(math.radians(expected['hfov'])/2))
        if abs(intr['focal_length_x']-expected_fx)>.001:
            raise ValueError('Native camera focal length mismatch')
        native_cameras.append({'intrinsics': intr, 'rotation': list(rotation)})
    return {'stereo_group': group, 'eye_size': list(decoded[0].size),
            'baseline_mm': cameras[1]['position_mm'] - cameras[0]['position_mm'],
            'cameras': cameras, 'bytes': len(data), 'decoded_eyes': len(decoded),
            'native_libheif': {'version': pillow_heif.libheif_info()['libheif'],
                              'groups': native_groups, 'cameras': native_cameras,
                              'chroma': decoded.info['chroma']}}
