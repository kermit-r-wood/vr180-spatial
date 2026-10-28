import cv2
import numpy as np
import pytest
from depth_preview import estimate_depth


def test_spherical_stereo_near_plane_is_warmer_than_far_plane():
    # Render textured planes at z=1 and z=3 from cameras separated by .12.
    # Rays are equirectangular, so this also tests the epipolar remapping.
    n = 512
    a = ((np.arange(n, dtype=np.float32)+.5)/n-.5)*np.pi
    lon, lat = np.meshgrid(a, a)
    z = np.where(lat > 0, 1., 3.)
    x = z*np.tan(lon)
    y = z*np.tan(lat)/np.cos(lon)
    texture = np.random.default_rng(7).integers(0, 256, (2048, 2048), dtype=np.uint8)
    texture = cv2.GaussianBlur(texture, (3, 3), .6)
    eyes = []
    for camera in (0., .12):
        eye = cv2.remap(texture, ((x+camera)*150+1024).astype(np.float32),
                       (y*150+1024).astype(np.float32), cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_WRAP)
        eyes.append(cv2.cvtColor(eye, cv2.COLOR_GRAY2BGR))
    depth, stats = estimate_depth(np.hstack(eyes))
    def warmth(part):
        pixels = part[part[:, :, 3]>0].astype(float)
        assert len(pixels)>100
        return np.median(pixels[:, 2]-pixels[:, 0])
    assert warmth(depth[280:330, 230:280]) > warmth(depth[182:232, 230:280])+100
    assert stats['eye']=='left'


def test_untextured_photo_has_no_invented_depth():
    with pytest.raises(ValueError, match='可靠匹配不足'):
        estimate_depth(np.full((256,512,3), 128, np.uint8))
