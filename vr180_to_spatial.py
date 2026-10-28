"""Convert half-equirectangular SBS VR180 photographs to Apple spatial HEIC."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageCms

from spatial_heic import save_spatial, inspect_spatial


def project(eye, width, height, hfov, pitch=0):
    """Inverse pinhole to 180x180 degree equirectangular; pixel-centre sampling."""
    focal = width / (2 * math.tan(math.radians(hfov)/2))
    x = (np.arange(width, dtype=np.float32) + .5 - width/2) / focal
    y = (np.arange(height, dtype=np.float32) + .5 - height/2) / focal
    xx, yy = np.meshgrid(x, y)
    # Positive pitch looks downward. A shared rotation about the horizontal
    # stereo baseline preserves horizontal epipolar alignment (unlike yaw).
    angle = math.radians(pitch)
    yr = math.cos(angle)*yy + math.sin(angle)
    zr = math.cos(angle) - math.sin(angle)*yy
    if np.any(zr <= 0):
        raise ValueError('Pitch and vertical FOV extend outside the front VR180 hemisphere')
    lon = np.arctan2(xx, zr)
    lat = np.arctan2(yr, np.sqrt(zr*zr + xx*xx))
    mapx = (lon/np.pi + .5) * eye.shape[1] - .5
    mapy = (lat/np.pi + .5) * eye.shape[0] - .5
    return cv2.remap(eye, mapx, mapy, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)


def correspondence_metrics(left, right):
    """Robust descriptor matches, independent of horizontal disparity magnitude."""
    scale = min(1, 1400/left.shape[1])
    imgs = [cv2.resize(cv2.cvtColor(x, cv2.COLOR_RGB2GRAY), None, fx=scale, fy=scale) for x in (left,right)]
    sift = cv2.SIFT_create(nfeatures=6000)
    a, da = sift.detectAndCompute(imgs[0], None)
    b, db = sift.detectAndCompute(imgs[1], None)
    if da is None or db is None:
        return {'matches': 0}, None
    matches = cv2.BFMatcher().knnMatch(da, db, k=2)
    good = [m for pair in matches if len(pair)==2 for m,n in [pair] if m.distance < .7*n.distance]
    if len(good)<20:
        return {'matches': len(good)}, None
    p = np.float32([a[m.queryIdx].pt for m in good])/scale
    q = np.float32([b[m.trainIdx].pt for m in good])/scale
    _, mask = cv2.findFundamentalMat(p, q, cv2.FM_RANSAC, 1.5/scale, .999)
    if mask is None:
        return {'matches': 0}, None
    p, q = p[mask.ravel()!=0], q[mask.ravel()!=0]
    delta = p-q
    return {'matches': len(p), 'horizontal_median_px': float(np.median(delta[:,0])),
            'vertical_median_px': float(np.median(delta[:,1])),
            'vertical_abs_p95_px': float(np.percentile(abs(delta[:,1]),95)),
            'horizontal_p01_px': float(np.percentile(delta[:,0],1)),
            'horizontal_p99_px': float(np.percentile(delta[:,0],99))}, (p,q)


def rectify_views(left, right, hfov):
    """Estimate a small relative camera correction, then resample to a shared
    centred pinhole camera. Does not synthesize pixels or alter stereo baseline.
    Fail closed on large/ambiguous camera corrections or excessive crop.
    """
    height,width=left.shape[:2]
    metrics,points=correspondence_metrics(left,right)
    if points is None or metrics['matches']<80:
        raise ValueError('Insufficient correspondences for camera rectification')
    p,q=points
    focal=width/(2*math.tan(math.radians(hfov)/2))
    K=np.float64([[focal,0,width/2],[0,focal,height/2],[0,0,1]])
    E,mask=cv2.findEssentialMat(p,q,K,method=cv2.RANSAC,prob=.999,threshold=width/1600)
    if E is None or E.shape!=(3,3):
        raise ValueError('Ambiguous relative camera solution')
    n,R,t,mask=cv2.recoverPose(E,p,q,K,mask=mask)
    rotation_degrees=float(np.linalg.norm(cv2.Rodrigues(R)[0])*180/math.pi)
    if n<80 or n<len(p)*.6 or rotation_degrees>3 or t[0,0]>-.95:
        raise ValueError('Unreliable stereo calibration; refusing large or reversed camera correction')
    R1,R2,_,_,_,_,_=cv2.stereoRectify(K,None,K,None,(width,height),R,t,flags=cv2.CALIB_ZERO_DISPARITY)
    # Keep a centred optical axis, unlike stereoRectify's potentially off-centre
    # P matrices. Increase focal length until the whole output maps inside BOTH
    # source images. Homography of a rectangle is bounded by its four corners.
    corners=np.float64([[.5,.5,1],[width-.5,.5,1],[.5,height-.5,1],[width-.5,height-.5,1]]).T
    new_focal=focal
    for attempt in range(60):
        new_K=np.float64([[new_focal,0,width/2],[0,new_focal,height/2],[0,0,1]])
        valid=True
        for rotation in (R1,R2):
            rays=K @ rotation.T @ np.linalg.inv(new_K) @ corners
            xy=rays[:2]/rays[2:]
            valid &= bool(np.all(rays[2]>0) and np.all(xy[0]>=4) and np.all(xy[0]<=width-5)
                          and np.all(xy[1]>=4) and np.all(xy[1]<=height-5))
        if valid: break
        new_focal*=1.025
    else:
        raise ValueError('Unable to find valid common stereo field of view')
    effective_fov=math.degrees(2*math.atan(width/(2*new_focal)))
    if effective_fov<hfov*.7:
        raise ValueError('Rectification would remove too much field of view')
    results=[]
    for source,rotation in ((left,R1),(right,R2)):
        mx,my=cv2.initUndistortRectifyMap(K,None,rotation,new_K,(width,height),cv2.CV_32FC1)
        results.append(cv2.remap(source,mx,my,cv2.INTER_LANCZOS4))
    return *results,effective_fov,{'inliers':int(n),'relative_rotation_degrees':rotation_degrees,
           'estimated_translation_direction':t.ravel().tolist(),'left_rotation':R1.tolist(),
           'right_rotation':R2.tolist(),'output_hfov':effective_fov}


def convert(source, out_dir, args):
    source = Path(source)
    output = out_dir / (source.stem + '.spatial.heic')
    if output.exists() and not args.overwrite:
        raise ValueError(f'Output exists: {output}; use --overwrite')
    with Image.open(source) as im:
        exif = im.getexif()
        software = str(exif.get(305,''))
        lens = str(exif.get_ifd(34665).get(42036,''))
        if args.projection == 'auto' and 'EOS VR Utility' not in software:
            raise ValueError('Unrecognized projection. Specify --projection equirect180 only for 180x180 per-eye equirectangular input.')
        if im.width != im.height*2:
            raise ValueError('Expected full SBS with square 180x180 degree eyes (2:1 combined image)')
        baseline = args.baseline_mm
        if baseline is None:
            if 'RF5.2mm' in lens and 'DUAL FISHEYE' in lens:
                baseline = 60.0
            else:
                raise ValueError('Unknown camera baseline: specify --baseline-mm')
        if im.info.get('icc_profile'):
            import io
            rgb = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(im.info['icc_profile'])), ImageCms.createProfile('sRGB'), outputMode='RGB')
        else:
            rgb = im.convert('RGB')
        data = np.asarray(rgb)
    eyes = np.split(data,2,axis=1)
    if args.eye_order == 'rl':
        eyes.reverse()
    left,right = [project(e,args.width,args.height,args.hfov,args.pitch) for e in eyes]
    output_hfov=args.hfov
    rectification=None
    if args.pitch != 0:
        left,right,output_hfov,rectification=rectify_views(left,right,args.hfov)
    before,_ = correspondence_metrics(left,right)
    after = before
    # Rectify only a constant vertical offset; arbitrary warps would invalidate
    # the pinhole metadata. Apply symmetric shifts and crop equal margins.
    vertical_shift = 0.0
    crop = 0
    if args.align_vertical and before.get('matches',0)>=40:
        vertical_shift = before['vertical_median_px']
        if abs(vertical_shift)>args.height*.02:
            raise ValueError('Large vertical misalignment; calibration is required')
        if abs(vertical_shift)>.25:
            def translate(a,dy):
                return cv2.warpAffine(a,np.float32([[1,0,0],[0,1,dy]]),(a.shape[1],a.shape[0]),flags=cv2.INTER_LANCZOS4)
            left=translate(left,-vertical_shift/2)
            right=translate(right,vertical_shift/2)
            crop=math.ceil(abs(vertical_shift)/2)+4
            left,right=left[crop:-crop],right[crop:-crop]
            after,_=correspondence_metrics(left,right)
    if after.get('matches',0)<40:
        raise ValueError('Insufficient stereo matches for automatic validation')
    if after['vertical_abs_p95_px']>max(3,args.width*.002):
        raise ValueError('Residual vertical disparity too large; source needs stereo calibration')
    disparity = args.disparity
    if disparity is None:
        # Move near foreground behind the window: positive separation exceeds
        # positive source disparity. Do not change the encoded stereo pixels.
        disparity = max(.02,after['horizontal_p99_px']/args.width+.005)
        disparity = round(disparity,4)
    if not -1<=disparity<=1:
        raise ValueError('Disparity must be in [-1,1]')
    out_dir.mkdir(parents=True, exist_ok=True)
    l,r=Image.fromarray(left),Image.fromarray(right)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    l.info['icc_profile']=srgb
    r.info['icc_profile']=srgb
    temp=output.with_suffix('.tmp.heic')
    try:
        save_spatial(l,r,temp,output_hfov,baseline,disparity,args.quality)
        check=inspect_spatial(temp)
        if abs(check['baseline_mm']-baseline)>.001 or abs(check['cameras'][0]['hfov']-output_hfov)>.001:
            raise ValueError('Spatial metadata readback mismatch')
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    preview=Image.fromarray(np.concatenate([left,right],axis=1))
    preview.thumbnail((1600,800))
    preview.save(output.with_suffix('.preview.jpg'),quality=95)
    if args.save_eyes:
        l.save(output.with_suffix('.left.png'))
        r.save(output.with_suffix('.right.png'))
    report={'source':str(source.resolve()), 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'output':str(output.resolve()),'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'software':software,'lens':lens,'input_projection':'half-equirectangular 180x180 per eye',
            'eye_order':args.eye_order,'vertical_shift_px':vertical_shift,'vertical_crop_each_edge':crop,
            'pitch_degrees_down':args.pitch,
            'requested_hfov':args.hfov,'rectification':rectification,
            'stereo_before':before,'stereo_after':after,'output_validation':check,
            'apple_device_test':'Not performed; Windows structural/decoding/geometry validation only'}
    output.with_suffix('.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path,help='Image or directory (nonrecursive JPG/PNG batch)')
    p.add_argument('--output-dir',type=Path,default=Path('output'))
    p.add_argument('--projection',choices=['auto','equirect180'],default='auto')
    p.add_argument('--eye-order',choices=['lr','rl'],default='lr')
    p.add_argument('--baseline-mm',type=float)
    p.add_argument('--hfov',type=float,default=75)
    p.add_argument('--pitch',type=float,default=0,help='View pitch in degrees; positive looks down, negative looks up')
    p.add_argument('--width',type=int,default=2400)
    p.add_argument('--height',type=int,default=1800)
    p.add_argument('--quality',type=int,default=92)
    p.add_argument('--disparity',type=float,help='Default: automatically place 99th-percentile matched foreground behind window')
    p.add_argument('--align-vertical',action=argparse.BooleanOptionalAction,default=True)
    p.add_argument('--save-eyes',action='store_true')
    p.add_argument('--overwrite',action='store_true')
    args=p.parse_args()
    if not (20<=args.hfov<90 and 256<=args.width<=8192 and 256<=args.height<=8192 and 1<=args.quality<=100):
        p.error('Require FOV 20..<90, width/height 256..8192, quality 1..100')
    if args.baseline_mm is not None and not 0<args.baseline_mm<10000:
        p.error('baseline must be positive and below 10000 mm')
    vfov=math.degrees(2*math.atan(args.height/args.width*math.tan(math.radians(args.hfov)/2)))
    if not math.isfinite(args.pitch) or abs(args.pitch)+vfov/2>=90:
        p.error('Pitch plus half vertical FOV must stay below 90 degrees')
    files=sorted(x for x in args.input.iterdir() if x.suffix.lower() in ('.jpg','.jpeg','.png')) if args.input.is_dir() else [args.input]
    if not files:
        p.error('No input images')
    failures=[]
    for f in files:
        try:
            convert(f,args.output_dir,args)
        except Exception as e:
            failures.append(str(f))
            print(f'FAILED {f}: {e}',flush=True)
    if failures:
        raise SystemExit(1)


if __name__=='__main__':
    main()
