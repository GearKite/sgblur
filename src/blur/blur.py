import hashlib
import json
import os
import pathlib
import subprocess
import time
import uuid
from datetime import datetime

import exifread
import requests
import turbojpeg
from PIL import Image, ImageFilter, ImageOps, ImageDraw

from ..detect import detect

jpeg = turbojpeg.TurboJPEG()

crop_save_dir = '/tmp/sgblur/crops'

def blurPicture(picture_bytes, keep, microservice: bool):
    """Blurs a single picture by detecting faces and licence plates.

    Parameters
    ----------
    picture : tempfile
		Picture file
    keep : str
        1 to keep blurred part to allow deblur
        2 keep detected road signs only, do not blur

    Returns
    -------
    Bytes
        the blurred image
    """

    pid = os.getpid()

    # copy received JPEG picture to temporary file
    tmp = '/dev/shm/blur%s.jpg' % pid
    tmpcrop = '/dev/shm/crop%s.jpg' % pid

    with open(tmp, 'w+b') as jpg:
        jpg.write(picture_bytes)
        jpg.seek(0)
        tags = exifread.process_file(jpg, details=False)

    print("keep", keep, "original", os.path.getsize(tmp))

    # solve image orientation
    if 'Image Orientation' in tags:
        if 'normal' not in str(tags['Image Orientation']):
            subprocess.run('exiftran -a %s -o %s' % (tmp, tmp+'_tmp'), shell=True)
            print("after exiftran", os.path.getsize(tmp+'_tmp'))
            os.replace(tmp+'_tmp', tmp)

    info, crop_rects = detect_parts_to_blur(picture_bytes, microservice, keep)

    return blur_image_parts(tmp, tmpcrop, keep, crop_rects, info)

def detect_parts_to_blur(picture_bytes, microservice, keep = None):
    if microservice:
        return call_detection_microservice(picture_bytes, keep)
    else:
        print("Detecting areas to blur locally...")
        result = detect.detector(picture_bytes)
        info = result["info"]
        crop_rects = result["crop_rects"]
        return info, crop_rects

def call_detection_microservice(picture_bytes, keep):
    """Call the detection service at localhost:8001"""
    print("Calling detection service...")
    files = {'picture': picture_bytes}
    if keep == '2':
        r = requests.post('http://localhost:8001/detect/?cls=sign', files=files, timeout=10)
    else:
        r = requests.post('http://localhost:8001/detect/', files=files, timeout=10)
    results = json.loads(r.text)
    info = results['info']
    crop_rects = results['crop_rects']
    return info, crop_rects


def blur_image_parts(tmp, tmpcrop, keep, crop_rects: list, info: list):
    """Blurs image given a list of rectangles"""

    # get picture details
    with open(tmp, 'rb') as jpg:
        width, height, jpeg_subsample, jpeg_colorspace = jpeg.decode_header(
            jpg.read())
        jpg.seek(0)

    salt = None

    # prepare bounding boxes list

    # get MCU maximum size (2^n) = 8 or 16 pixels subsamplings
    _, _, sample = [(3, 3 ,'1x1'), (4, 3, '2x1'), (4, 4, '2x2'), (4, 4, '2x2'), (3, 4, '1x2')][jpeg_subsample]

    # print("hblock, vblock, sample :",hblock, vblock, sample)
    # print(info, crop_rects)

    today = datetime.today().strftime('%Y-%m-%d')
    if len(crop_rects)>0:
        # extract cropped jpeg data from boxes to be blurred
        with open(tmp, 'rb') as jpg:
            crops = jpeg.crop_multiple(jpg.read(), crop_rects, background_luminance=0, copynone=True)

        # if face or plate, blur boxes and paste them onto original
        for _, (crop_bytes, crop_info, crop_rect) in enumerate(zip(crops, info, crop_rects)):
            if keep=='2':
                break
            print(crop_info['class'])
            if crop_info['class'] == 'sign':
                continue
            crop = open(tmpcrop,'wb')
            crop.write(crop_bytes)
            crop.close()
            # pillow based blurring
            img = Image.open(tmpcrop)
            radius = max(int(max(img.width, img.height)/12) >> 3 << 3, 8)
            # pixelate first
            reduced = ImageOps.scale(img, 1/radius, resample=0)
            pixelated = ImageOps.scale(reduced, radius, resample=0)
            # and blur
            boxblur = pixelated.filter(ImageFilter.BoxBlur(radius))
            boxblur.save(tmpcrop, subsampling=jpeg_subsample)
            subprocess.run('djpeg %s | cjpeg -sample %s -optimize -dct float -baseline -outfile %s' % (tmpcrop, sample, tmpcrop+'_tmp'), shell=True)
            os.replace(tmpcrop+'_tmp', tmpcrop)

            # jpegtran "drop"
            print( 'crop size', os.path.getsize(tmpcrop))
            p = subprocess.run('jpegtran -progressive -optimize -copy all -trim -drop +%s+%s %s %s > %s' % (crop_rect[0], crop_rect[1], tmpcrop, tmp, tmp+'_tmp'), shell=True)
            print( 'after drop', os.path.getsize(tmp+'_tmp'))
            if p.returncode != 0 :
                print('crop %sx%s -> recrop %sx%s' % (img.width, img.height, crop_rect[2], crop_rect[3]))
                subprocess.run('jpegtran -crop %sx%s+0+0 %s > %s' % (img.width, img.height, tmpcrop, tmpcrop+'_tmp'), shell=True)
                p = subprocess.run('jpegtran -progressive -optimize -copy all -trim -drop +%s+%s %s %s > %s' % (crop_rect[0], crop_rect[1], tmpcrop+'_tmp', tmp, tmp+'_tmp'), shell=True)
                if img.height != crop_rect[3]:
                    input()

            if p.returncode != 0 :
                print('>>>>>> crop info: ',crop_info)
                input()
                # problem with original JPEG... we try to recompress it
                subprocess.run('djpeg %s | cjpeg -optimize -smooth 10 -dct float -baseline -outfile %s' % (tmp, tmp+'_tmp'), shell=True)
                # copy EXIF tags
                subprocess.run('exiftool -overwrite_original -tagsfromfile %s %s' % (tmp, tmp+'_tmp'), shell=True)
                print('after recompressing original', os.path.getsize(tmp+'_tmp'))
                os.replace(tmp+'_tmp', tmp)
                print('jpegtran -progressive -optimize -copy all -trim -drop +%s+%s %s %s > %s' % (crop_rect[0], crop_rect[1], tmpcrop, tmp, tmp+'_tmp'))
                subprocess.run('jpegtran -progressive -optimize -copy all -trim -drop +%s+%s %s %s > %s' % (crop_rect[0], crop_rect[1], tmpcrop, tmp, tmp+'_tmp'), shell=True)
            os.replace(tmp+'_tmp', tmp)

        # save detected objects data in JPEG comment at end of file
        with open(tmp, 'r+b') as jpg:
            jpg.seek(0, os.SEEK_END)
            jpg.seek(-2, os.SEEK_CUR)
            jpg.write(b'\xFF\xFE')
            jpg.write(len(str(info)+'  ').to_bytes(2, 'big'))
            jpg.write(str(info).encode())
            jpg.write(b'\xFF\xD9')

        # keep potential false positive and road signs original parts hashed
        if crop_save_dir != '':
            salt = str(uuid.uuid4())
            for _, (crop_bytes, crop_info) in enumerate(zip(crops, info)):
                if ((keep == '1' and crop_info['confidence'] < 0.5 and crop_info['class'] in ['face', 'plate'])
                        or (crop_info['confidence'] > 0.2 and crop_info['class'] == 'sign')):
                    h = hashlib.sha256()
                    h.update(((salt if not crop_info['class'] == 'sign' else str(info))+str(crop_info)).encode())
                    cropname = h.hexdigest()+'.jpg'
                    if crop_info['class'] != 'sign':
                        dirname = crop_save_dir+'/'+crop_info['class']+'/'+cropname[0:2]+'/'+cropname[0:4]+'/'
                    else:
                        dirname = crop_save_dir+'/'+crop_info['class']+'/'+today+'/'+cropname[0:2]+'/'
                    pathlib.Path(dirname).mkdir(parents=True, exist_ok=True)
                    with open(dirname+cropname, 'wb') as crop:
                        crop.write(crop_bytes)
                    if crop_info['class'] == 'sign':
                        print('copy EXIF')
                        info2 = {   'width':width,
                                    'height':height,
                                    'xywh': crop_info['xywh'],
                                    'confidence': crop_info['confidence'],
                                    'offset': round((crop_info['xywh'][0]+crop_info['xywh'][2]/2.0)/width - 0.5,3)}
                        # subprocess.run('exiv2 -ea %s | exiv2 -ia %s' % (tmp, dirname+cropname), shell=True)
                        comment = json.dumps(info2, separators=(',', ':'))
                        print(dirname+cropname, comment)
                        subprocess.run('exiftool -q -overwrite_original -tagsfromfile %s -Comment=\'%s\' %s' % (tmp, comment, dirname+cropname), shell=True)
                    else:
                        # round ctime/mtime to midnight
                        daytime = int(time.time()) - int(time.time()) % 86400
                        os.utime(dirname+cropname, (daytime, daytime))
            info = { 'info': info, 'salt': salt }

        if False:
            # regenerate EXIF thumbnail
            before_thumb = os.path.getsize(tmp)
            subprocess.run('exiftran -g -o %s %s' % (tmp+'_tmp', tmp), shell=True)
            os.replace(tmp+'_tmp', tmp)
            print("after thumbnail", os.path.getsize(tmp), (100*(os.path.getsize(tmp)-before_thumb)/before_thumb))

    # return result (original image if no blur needed)
    with open(tmp, 'rb') as jpg:
        original = jpg.read()

    if False:
        try:
            os.remove(tmp)
            os.remove(tmpcrop)
        except:
            pass

    return original, info

def deblurPicture(picture, idx, salt):
    """Un-blur a part of a previously blurred picture by restoring the original saved part.

    Parameters
    ----------
    picture : tempfile
		Picture file
    idx : int
        Index in list of blurred parts (starts at 0)
    salt: str
        salt to compute hashed filename

    Returns
    -------
    Bytes
        the "deblurred" image if OK else None
    """

    try:
        pid = os.getpid()
        # copy received JPEG picture to temporary file
        tmp = '/dev/shm/deblur%s.jpg' % pid

        with open(tmp, 'w+b') as jpg:
            jpg.write(picture.file.read())

        # get JPEG comment to retrieve detected objects
        com = subprocess.run('rdjpgcom %s' % tmp, shell=True, capture_output=True)
        i = json.loads(com.stdout.decode().replace('\'','"'))

        # do not allow deblur with high confidence detected objects
        if i[idx]['conf']>0.5:
            return None

        # compute hashed filename containing original picture part
        h = hashlib.sha256()
        h.update((salt+str(i[idx])).encode())
        cropname = h.hexdigest()+'.jpg'
        cropdir = crop_save_dir+'/'+i[idx]['class']+'/'+cropname[0:2]+'/'+cropname[0:4]+'/'

        # "drop" original picture part into provided picture
        crop_rect = i[idx]['xywh']
        subprocess.run('jpegtran -optimize -copy all -drop +%s+%s %s %s > %s' % (crop_rect[0], crop_rect[1], cropdir+cropname, tmp, tmp+'_tmp'), shell=True, capture_output=True)
        os.replace(tmp+'_tmp', tmp)

        with open(tmp, 'rb') as jpg:
            deblurred = jpg.read()

        os.remove(tmp)

        print('deblur: ',i[idx], cropname)
        return deblurred
    except:
        return None


def create_mask(picture_bytes, picture: Image.Image):
    """Draws a mask where the picture would be blurred"""
    areas, _ = detect_parts_to_blur(picture_bytes, False)

    output = Image.new(mode="1", size=picture.size)
    output_draw = ImageDraw.Draw(output)

    for rect in areas:
        if rect['class'] == 'sign':
            continue
        xywh = rect["xywh"]

        x = xywh[0]
        y = xywh[1]
        w = xywh[2]
        h = xywh[3]

        shape = [(x, y), (x + w, y + h)]
        output_draw.rectangle(shape, fill="white")

    return output
