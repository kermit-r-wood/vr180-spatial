"""Bounded local export adapter for the existing validated HEIC converter."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def validate_frame(frame):
    limits = {'pitch':(-80,80), 'hfov':(30,88), 'width':(1600,3200),
              'height':(900,3200), 'baseline':(.1,9999)}
    result = {}
    for key, (low, high) in limits.items():
        value = float(frame[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Invalid {key}')
        result[key] = value
    if float(frame['yaw']) != 0:
        raise ValueError('空间 HEIC 当前仅支持左右方向 0°')
    for key in ('width', 'height'):
        if not result[key].is_integer():
            raise ValueError('Output dimensions must be integers')
        result[key] = int(result[key])
    return result


def export_spatial(frame, source_bytes):
    args = validate_frame(frame)
    with tempfile.TemporaryDirectory(prefix='vr180-export-') as directory:
        root = Path(directory)
        source = root/'photo.jpg'
        source.write_bytes(source_bytes)
        command = [sys.executable, str(ROOT/'vr180_to_spatial.py'), str(source),
                   '--output-dir', str(root/'result'), '--projection', 'equirect180']
        for key, option in [('pitch','pitch'), ('hfov','hfov'), ('width','width'),
                            ('height','height'), ('baseline','baseline-mm')]:
            command.extend(['--'+option, str(args[key])])
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=240,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            detail = (result.stderr or result.stdout).strip().splitlines()
            raise ValueError('转换未通过几何检查或编码失败：'+(detail[-1] if detail else 'unknown error'))
        output = root/'result'/'photo.spatial.heic'
        return output.read_bytes()
