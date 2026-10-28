"""Approximate relative range from calibrated LR half-equirectangular VR180.

Rotate the spherical parameterization so each row is an epipolar plane about
the horizontal camera baseline. Match angular disparity, not longitude shifts.
No learned depth or fabricated fill is used for unmatched regions.
"""
import cv2
import numpy as np


def estimate_depth(sbs):
    h, w = sbs.shape[:2]
    if w != 2*h or not 128 <= h <= 1024:
        raise ValueError('Expected a 2:1 SBS image with 128–1024 pixels per eye')
    n = h
    angle = ((np.arange(n, dtype=np.float32)+.5)/n-.5)*np.pi
    theta, phi = np.meshgrid(angle, angle)
    x = np.sin(theta)
    y = np.cos(theta)*np.sin(phi)
    z = np.cos(theta)*np.cos(phi)
    mx = (np.arctan2(x, z)/np.pi+.5)*n-.5
    my = (np.arcsin(np.clip(y, -1, 1))/np.pi+.5)*n-.5
    eyes = [cv2.remap(sbs[:, i*n:(i+1)*n], mx, my, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_REPLICATE) for i in range(2)]
    gray = [cv2.cvtColor(e, cv2.COLOR_BGR2GRAY) for e in eyes]
    count = max(16, int(n*.125)//16*16)
    def matcher(minimum):
        return cv2.StereoSGBM_create(minDisparity=minimum, numDisparities=count,
            blockSize=5, P1=8*25, P2=32*25, uniquenessRatio=12,
            speckleWindowSize=80, speckleRange=2, disp12MaxDiff=1,
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
    disparity = matcher(0).compute(*gray).astype(np.float32)/16
    reverse = matcher(-count).compute(gray[1], gray[0]).astype(np.float32)/16
    cols, rows = np.meshgrid(np.arange(n, dtype=np.float32), np.arange(n, dtype=np.float32))
    xr = cols-disparity
    dr = cv2.remap(reverse, xr, rows, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=-999)
    # Reject low-texture areas, occlusions and inconsistent left/right matches.
    g = gray[0].astype(np.float32)
    variance = cv2.boxFilter(g*g, -1, (7, 7))-cv2.boxFilter(g, -1, (7, 7))**2
    valid = (disparity>.75)&(disparity<count-1)&(xr>=0)&(np.abs(disparity+dr)<1.5)&(variance>9)
    valid &= (np.abs(theta)<np.deg2rad(82))&(np.abs(phi)<np.deg2rad(82))
    delta = disparity*np.pi/n
    inverse_range = np.sin(delta)/np.maximum(np.cos(theta-delta), .02)
    # Reproject scalar depth and confidence to the original LEFT-eye panorama.
    lon, lat = theta, phi
    sx, sy, sz = np.cos(lat)*np.sin(lon), np.sin(lat), np.cos(lat)*np.cos(lon)
    tx = (np.arctan2(sx, np.hypot(sy, sz))/np.pi+.5)*n-.5
    ty = (np.arctan2(sy, sz)/np.pi+.5)*n-.5
    inv = cv2.remap(inverse_range, tx, ty, cv2.INTER_NEAREST)
    mask = cv2.remap(valid.astype(np.uint8), tx, ty, cv2.INTER_NEAREST).astype(bool)
    values = inv[mask]
    if len(values)<n*n*.005:
        raise ValueError('可靠匹配不足，无法显示深度。请确认左右眼顺序和等距柱状投影。')
    low, high = np.percentile(values, [5, 95])
    norm = np.clip((inv-low)/max(float(high-low), 1e-6), 0, 1)
    # OpenCV JET: blue = low inverse range (far), red = high (near).
    color = cv2.applyColorMap((norm*255).astype(np.uint8), cv2.COLORMAP_JET)
    rgba = np.dstack([color, mask.astype(np.uint8)*255])
    return rgba, {'valid_percent': round(float(mask.mean()*100), 1),
                  'scale': 'relative_inverse_range', 'eye': 'left',
                  'normalization': 'whole_photo_p05_p95', 'resolution': n}
