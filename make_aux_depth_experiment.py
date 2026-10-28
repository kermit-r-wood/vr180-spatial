"""Experimental HEIC auxiliary disparity injection; Apple readback NOT assumed.

Preserves original stereo bitstreams byte-for-byte. Writes the standard HEVC
depth auxiliary type and Apple pixel-data XMP, without copying camera metadata
or private portrait rendering parameters from the reference image.
"""
import io
import json
import math
import struct
import hashlib
from pathlib import Path
import cv2
import numpy as np
import pillow_heif
from PIL import Image
from spatial_heic import boxes, box, child, associations, write_associations, inspect_spatial

OUT = Path('output/aux_depth_experiment')



def locations(payload):
    # Our encoder uses iloc v0, no construction method or extent index.
    assert payload[0] == 0
    os, ls, bs = payload[4] >> 4, payload[4] & 15, payload[5] >> 4
    p = 8
    result = {}
    def read(n):
        nonlocal p
        value = int.from_bytes(payload[p:p+n], 'big'); p += n
        return value
    for _ in range(int.from_bytes(payload[6:8], 'big')):
        item, dataref, base = read(2), read(2), read(bs)
        assert dataref == 0
        result[item] = [(base+read(os), read(ls)) for _ in range(read(2))]
    assert p == len(payload)
    return result


def iloc(entries):
    p = bytes(4)+b'\x88\x00'+struct.pack('>H', len(entries))
    for item, extents in entries.items():
        p += struct.pack('>HHH', item, 0, len(extents))
        p += b''.join(struct.pack('>QQ', *extent) for extent in extents)
    return box(b'iloc', p)


def inject(original, pixels, low, high, width, height, focal):
    stream = io.BytesIO()
    pillow_heif.from_pillow(Image.fromarray(pixels)).save(stream, quality=100)
    encoded = stream.getvalue()
    meta = child(original, b'meta'); donor = child(encoded, b'meta')
    iprp = child(meta[4:], b'iprp'); diprp = child(donor[4:], b'iprp')
    props = [raw for _, _, raw, _ in boxes(child(iprp, b'ipco'))]
    assoc = associations(child(iprp, b'ipma'))
    depth_id = max(assoc)+1; xmp_id = depth_id+1
    old_count = len(props)
    props += [raw for _, _, raw, _ in boxes(child(diprp, b'ipco'))]
    props.append(box(b'auxC', bytes(4)+b'urn:mpeg:hevc:2015:auxid:2\0'))
    da = associations(child(diprp, b'ipma')); assert list(da)==[1]
    assoc[depth_id] = [(i+old_count, e) for i,e in da[1]]+[(len(props), True)]
    matrix = [focal,0,0,0,focal,0,width/2,height/2,1]
    seq = ''.join(f'<rdf:li>{v}</rdf:li>' for v in matrix)
    xmp = f'''<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" xmlns:apdi="http://ns.apple.com/pixeldatainfo/1.0/" xmlns:depthData="http://ns.apple.com/depthData/1.0/">
<apdi:IntMinValue>0</apdi:IntMinValue><apdi:IntMaxValue>255</apdi:IntMaxValue><apdi:StoredFormat>1278226488</apdi:StoredFormat><apdi:NativeFormat>1751411059</apdi:NativeFormat><apdi:FloatMinValue>{low}</apdi:FloatMinValue><apdi:FloatMaxValue>{high}</apdi:FloatMaxValue><apdi:AuxiliaryImageType>disparity</apdi:AuxiliaryImageType>
<depthData:DepthDataVersion>65541</depthData:DepthDataVersion><depthData:Accuracy>relative</depthData:Accuracy><depthData:Quality>low</depthData:Quality><depthData:Filtered>True</depthData:Filtered><depthData:IntrinsicMatrixReferenceWidth>{width}</depthData:IntrinsicMatrixReferenceWidth><depthData:IntrinsicMatrixReferenceHeight>{height}</depthData:IntrinsicMatrixReferenceHeight><depthData:IntrinsicMatrix><rdf:Seq>{seq}</rdf:Seq></depthData:IntrinsicMatrix>
</rdf:Description></rdf:RDF></x:xmpmeta>'''.encode()
    loc = locations(child(meta[4:], b'iloc'))
    donor_loc = locations(child(donor[4:], b'iloc')); assert list(donor_loc)==[1]
    loc[depth_id] = [(len(original)+8+offset, length) for offset,length in donor_loc[1]]
    loc[xmp_id] = [(len(original)+8+len(encoded), len(xmp))]
    inf = child(meta[4:], b'iinf'); assert inf[:4]==bytes(4)
    entries = [raw for _,_,raw,_ in boxes(inf[6:])]
    entries += [box(b'infe', b'\x02\x00\x00\x01'+struct.pack('>HH',depth_id,0)+b'hvc1\0'),
                box(b'infe', b'\x02\x00\x00\x01'+struct.pack('>HH',xmp_id,0)+b'mime\0application/rdf+xml\0')]
    refs = child(meta[4:],b'iref') if any(k==b'iref' for k,_,_,_ in boxes(meta[4:])) else bytes(4)
    assert refs[:4]==bytes(4)
    # The auxiliary map is aligned with the left (primary) view only.
    refs += box(b'auxl',struct.pack('>HHH',depth_id,1,1))+box(b'cdsc',struct.pack('>HHH',xmp_id,1,depth_id))
    replacements = {b'iloc':iloc(loc),b'iinf':box(b'iinf',bytes(4)+struct.pack('>H',len(entries))+b''.join(entries)),
                    b'iprp':box(b'iprp',box(b'ipco',b''.join(props))+write_associations(assoc))}
    newmeta = box(b'meta',meta[:4]+b''.join(replacements.get(k,raw) for k,_,raw,_ in boxes(meta[4:]) if k!=b'iref')+box(b'iref',refs))
    base = b''.join(box(b'free',bytes(len(p))) if k==b'meta' else raw for k,p,raw,_ in boxes(original))
    return base+box(b'mdat',encoded+xmp)+newmeta


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    SOURCE = args.source
    OUT.mkdir(exist_ok=True, parents=True)
    original = SOURCE.read_bytes(); info = inspect_spatial(SOURCE)
    stereo = pillow_heif.open_heif(SOURCE)
    w,h = stereo[0].size; n=800; sh=round(h*n/w)
    images=[cv2.resize(np.asarray(e),(n,sh),interpolation=cv2.INTER_AREA) for e in stereo]
    gray=[cv2.cvtColor(e,cv2.COLOR_RGB2GRAY) for e in images]
    def matcher(minimum):
        return cv2.StereoSGBM_create(minDisparity=minimum,numDisparities=128,blockSize=5,P1=200,P2=800,uniquenessRatio=12,speckleWindowSize=80,speckleRange=2)
    d=matcher(0).compute(*gray).astype(np.float32)/16
    rev=matcher(-128).compute(gray[1],gray[0]).astype(np.float32)/16
    x,y=np.meshgrid(np.arange(n,dtype=np.float32),np.arange(sh,dtype=np.float32))
    dr=cv2.remap(rev,x-d,y,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=-999)
    valid=(d>1)&(d<127)&(np.abs(d+dr)<1.5)
    if valid.mean()<.01: raise ValueError('Insufficient disparity evidence')
    focal=w/(2*math.tan(math.radians(info['cameras'][0]['hfov'])/2))
    inv=d/(focal*n/w*(info['baseline_mm']/1000))
    low,high=np.percentile(inv[valid],[2,98])
    # Explicitly retain confidence; fill gaps only for this controlled experiment.
    _,labels=cv2.distanceTransformWithLabels((~valid).astype(np.uint8),cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
    values=np.zeros(labels.max()+1,np.float32);values[labels[valid]]=inv[valid]
    filled=cv2.medianBlur(values[labels],5)
    pixels=np.uint8(np.clip((filled-low)/(high-low),0,1)*255)
    pixels=cv2.resize(pixels,(480,round(h*480/w)),interpolation=cv2.INTER_AREA)
    variants={'A_no_depth':None,'B_estimated_depth':pixels,'C_inverted_depth':255-pixels}
    report={'source':str(SOURCE),'apple_imageio_readback':'NOT RUN','vision_pro_viewing':'NOT RUN','estimate_valid_fraction':float(valid.mean()),'disparity_range_inverse_m':[float(low),float(high)],'gap_fill':'nearest valid estimate, median filter; not ground truth','auxiliary_format':'experimental HEVC auxid:2 + Apple apdi/depthData XMP; no HEVC depth SEI','files':{}}
    reference=[np.asarray(e).copy() for e in stereo]
    for name,depth in variants.items():
        path=OUT/(name+'.heic');path.write_bytes(original if depth is None else inject(original,depth,low,high,w,h,focal))
        result=inspect_spatial(path); decoded=pillow_heif.open_heif(path)
        assert all(np.array_equal(np.asarray(decoded[i]),reference[i]) for i in range(2))
        for key in ('eye_size','baseline_mm','cameras','stereo_group'):assert result[key]==info[key]
        depths=decoded[0].info['depth_images']; assert len(depths)==(0 if depth is None else 1)
        if depth is not None:
            read=np.asarray(depths[0]); assert read.shape==depth.shape
            error=float(np.abs(read.astype(float)-depth).mean());assert error<3
            Image.fromarray(read).save(OUT/(name+'.depth.png'))
        report['files'][name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'stereo_pixels_identical':True,'spatial_metadata_identical':True,'native_depth_count':len(depths),'aux_mae_8bit':error if depth is not None else None}
    Image.fromarray(np.uint8(valid)*255).save(OUT/'depth_confidence.png')
    (OUT/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
