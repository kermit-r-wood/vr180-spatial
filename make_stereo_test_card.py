"""Known-disparity synthetic fixture to test Apple stereo presentation."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from spatial_heic import save_spatial, inspect_spatial


def make_card():
    out = Path('output/diagnostics')
    out.mkdir(exist_ok=True, parents=True)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 34)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 23)
    eyes=[]
    # At fx=782px and baseline=.06m: positive disparities 8/24/48 pixels
    # correspond to depths about 5.86/1.95/.98 metres before presentation.
    layers=[('FAR',8,(90,145,390,625),(55,110,180)),
            ('MID',24,(450,145,750,625),(40,155,100)),
            ('NEAR',48,(810,145,1110,625),(210,120,45))]
    for eye,sign in [('LEFT',1),('RIGHT',-1)]:
        im=Image.new('RGB',(1200,800),(22,27,35))
        draw=ImageDraw.Draw(im)
        draw.text((340,30),'STEREO DEPTH TEST',font=font,fill='white')
        for name,disp,rect,color in layers:
            x0,y0,x1,y1=rect
            x0+=sign*disp//2; x1+=sign*disp//2
            draw.rectangle((x0,y0,x1,y1),fill=color,outline='white',width=3)
            for y in range(y0+70,y1-35,65):
                draw.line((x0+20,y,x1-20,y),fill=(230,230,230),width=2)
            draw.text((x0+85,y0+20),name,font=font,fill='white')
            draw.text((x0+30,y1-35),f'disparity {disp} px',font=small,fill='white')
        draw.text((240,710),'Close one eye at a time. Marker below is eye-specific.',font=small,fill='white')
        # Same position, different text: a monocular display will show the same
        # label through both eyes. This deliberately unfused marker is diagnostic.
        draw.text((490,750),eye+' EYE',font=small,fill='white')
        eyes.append(im)
    path=out/'STEREO_DEPTH_TEST.heic'
    save_spatial(*eyes,path,75,60,.045,95)
    check=inspect_spatial(path)
    check['synthetic_disparities_px']={'FAR':8,'MID':24,'NEAR':48}
    check['expected_eye_labels']=['LEFT EYE','RIGHT EYE']
    path.with_suffix('.json').write_text(json.dumps(check,indent=2),encoding='utf-8')
    print(path.resolve())


if __name__=='__main__': make_card()
