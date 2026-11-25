"""One normalized issue photo, stored privately and served through request scope."""
from io import BytesIO
import hashlib
import os
from pathlib import Path
import re
import tempfile
import uuid
import warnings

from flask import current_app,has_app_context
from PIL import Image,ImageOps,UnidentifiedImageError

MAX_PHOTO_BYTES=5*1024*1024
FILENAME=re.compile(r'[a-f0-9]{32}\.webp')


class InvalidMaintenancePhoto(ValueError):pass


def photo_enabled():
    return bool(current_app.config.get('MAINTENANCE_PHOTOS_ENABLED',False)) if has_app_context() else os.environ.get('MAINTENANCE_PHOTOS_ENABLED')=='1'


def photo_path(filename):
    if not isinstance(filename,str) or not FILENAME.fullmatch(filename):raise InvalidMaintenancePhoto('Invalid photo reference.')
    root=Path(current_app.config.get('MAINTENANCE_PHOTO_ROOT',Path(current_app.instance_path)/'maintenance-photos')).resolve()
    path=root/filename
    if path.is_symlink() or path.resolve().parent!=root:raise InvalidMaintenancePhoto('Invalid photo reference.')
    return path


def validate_photo(upload):
    if upload is None or not upload.filename:return None
    name=upload.filename
    if len(name)>200 or any(c in name for c in '/\\:') or any(ord(c)<32 for c in name):
        raise InvalidMaintenancePhoto('Use a plain image filename without folders.')
    suffix=Path(name).suffix.lower()
    if suffix not in ('.jpg','.jpeg','.png'):raise InvalidMaintenancePhoto('Choose one JPG, JPEG or PNG photo.')
    raw=upload.stream.read(MAX_PHOTO_BYTES+1)
    if not raw or len(raw)>MAX_PHOTO_BYTES:raise InvalidMaintenancePhoto('Choose a non-empty photo up to 5 MB.')
    expected='PNG' if suffix=='.png' else 'JPEG'
    if expected=='PNG' and (not raw.startswith(b'\x89PNG\r\n\x1a\n') or not raw.endswith(b'IEND\xaeB`\x82')) or expected=='JPEG' and (not raw.startswith(b'\xff\xd8\xff') or not raw.rstrip().endswith(b'\xff\xd9')):
        raise InvalidMaintenancePhoto('Choose a complete image matching its JPG/PNG extension.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw),formats=[expected]) as image:
                if image.width>10000 or image.height>10000 or image.width*image.height>20_000_000 or getattr(image,'is_animated',False):raise ValueError()
                image.verify()
            with Image.open(BytesIO(raw),formats=[expected]) as source:
                source.load();image=ImageOps.exif_transpose(source).convert('RGBA')
                image.thumbnail((1920,1920),Image.Resampling.LANCZOS)
                # Re-encoding a fresh RGB canvas strips EXIF/GPS and appended metadata.
                clean=Image.new('RGB',image.size,'white');clean.paste(image,mask=image.getchannel('A'))
                output=BytesIO();clean.save(output,format='WEBP',quality=85,method=4)
                data=output.getvalue();width,height=clean.size
    except (UnidentifiedImageError,OSError,SyntaxError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise InvalidMaintenancePhoto('Choose a valid still photo up to 10,000 pixels per side and 20 megapixels.') from None
    if len(data)>MAX_PHOTO_BYTES:raise InvalidMaintenancePhoto('Choose a smaller photo.')
    return dict(data=data,sha256=hashlib.sha256(data).hexdigest(),byte_count=len(data),width=width,height=height)


def store_photo(photo):
    filename=uuid.uuid4().hex+'.webp';destination=photo_path(filename)
    destination.parent.mkdir(parents=True,exist_ok=True);temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.tmp',delete=False) as output:
            temporary=Path(output.name);output.write(photo['data']);output.flush();os.fsync(output.fileno())
        os.replace(temporary,destination)
    finally:
        if temporary:temporary.unlink(missing_ok=True)
    return filename
