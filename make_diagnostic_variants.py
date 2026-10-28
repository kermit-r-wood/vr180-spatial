"""Change only window-disparity metadata, preserving both encoded eye images."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from spatial_heic import boxes, box, child, DISPARITY, inspect_spatial


def with_disparity(data, value):
    def rewrite(payload):
        out = []
        for kind, p, raw, _ in boxes(payload):
            if kind == b'meta':
                raw = box(kind, p[:4] + rewrite(p[4:]))
            elif kind in (b'iprp', b'ipco'):
                raw = box(kind, rewrite(p))
            elif kind == b'uuid' and p[:16] == DISPARITY:
                raw = box(kind, DISPARITY + struct.pack('>i', round(value*10000)))
            out.append(raw)
        return b''.join(out)
    if not -1 <= value <= 1:
        raise ValueError('Invalid disparity')
    result = rewrite(data)
    assert len(result) == len(data)
    before = [(raw, offset) for k, p, raw, offset in boxes(data) if k == b'mdat']
    after = [(raw, offset) for k, p, raw, offset in boxes(result) if k == b'mdat']
    assert before == after
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    data = args.source.read_bytes()
    dest = args.source.parent / 'diagnostics'
    dest.mkdir(exist_ok=True)
    reports = []
    for name, value in [('A_disparity_002', .02), ('B_disparity_000', 0.)]:
        path = dest / (args.source.stem + '.' + name + '.heic')
        path.write_bytes(with_disparity(data, value))
        reports.append({'file': str(path), 'disparity': value,
                        'validation': inspect_spatial(path), 'encoded_eyes_unchanged': True})
    (dest/'variants.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps([{'file':r['file'],'disparity':r['disparity']} for r in reports],indent=2))
