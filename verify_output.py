"""Read back spatial HEIC and optionally compare both eyes with lossless exports."""
import argparse
import json
import math
from pathlib import Path
import numpy as np
import pillow_heif
from PIL import Image
from spatial_heic import inspect_spatial


def verify(path):
    report = inspect_spatial(path)
    decoded = pillow_heif.open_heif(path)
    quality = []
    for index, side in enumerate(('left','right')):
        reference = path.with_suffix(f'.{side}.png')
        if reference.exists():
            a = np.asarray(Image.open(reference).convert('RGB'), dtype=np.float32)
            b = np.asarray(decoded[index], dtype=np.float32)
            if a.shape != b.shape:
                raise ValueError('Decoded/reference dimensions differ')
            mse = float(np.mean((a-b)**2))
            psnr = 10*math.log10(255**2/max(mse,1e-12))
            if psnr < 32:
                raise ValueError(f'{side} eye does not match reference: {psnr:.2f} dB')
            quality.append({'eye':side,'psnr_db':psnr})
    report['decoded_vs_lossless']=quality
    report['apple_photos_device_validation']='pending'
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',type=Path)
    args=parser.parse_args()
    report=verify(args.file)
    text=json.dumps(report,indent=2,ensure_ascii=False)
    args.file.with_suffix('.verification.json').write_text(text,encoding='utf-8')
    print(text)
