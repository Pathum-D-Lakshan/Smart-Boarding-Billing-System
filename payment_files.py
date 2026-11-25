"""Private original bank-slip evidence; never trust names, MIME or static URLs."""
from io import BytesIO
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid
import warnings

from flask import current_app
from PIL import Image,ImageOps,UnidentifiedImageError

FILENAME=re.compile(r'[a-f0-9]{32}\.(?:jpg|png|pdf)')


class InvalidPaymentFile(ValueError): pass


def upload_limit():
    return max(1024,min(int(current_app.config.get('PAYMENT_MAX_UPLOAD_BYTES',5*1024*1024)),10*1024*1024))


def evidence_path(filename):
    if not isinstance(filename,str) or not FILENAME.fullmatch(filename): raise InvalidPaymentFile('Invalid evidence reference.')
    root=Path(current_app.config.get('PAYMENT_UPLOAD_ROOT',Path(current_app.root_path)/'receipts'/'slips')).resolve()
    path=root/filename
    if path.is_symlink() or path.resolve().parent!=root: raise InvalidPaymentFile('Invalid evidence reference.')
    return path


def validate_slip(upload):
    if upload is None or not upload.filename: raise InvalidPaymentFile('Choose a JPG, PNG or static PDF bank slip.')
    name=upload.filename
    if len(name)>200 or any(c in name for c in ('/','\\',':')) or any(ord(c)<32 for c in name):
        raise InvalidPaymentFile('Use a plain filename without folders or special control characters.')
    extension=Path(name).suffix.lower()
    if extension not in ('.jpg','.jpeg','.png','.pdf'): raise InvalidPaymentFile('Only JPG, JPEG, PNG and static PDF files are accepted.')
    data=upload.stream.read(upload_limit()+1)
    if not data: raise InvalidPaymentFile('The bank slip is empty.')
    if len(data)>upload_limit(): raise InvalidPaymentFile('Choose a slip within the displayed upload-size limit.')
    if extension=='.pdf':
        if not re.match(br'%PDF-(?:1\.[0-7]|2\.0)',data) or not data.rstrip().endswith(b'%%EOF'):
            raise InvalidPaymentFile('Choose a complete, valid PDF bank slip.')
        environment={name:os.environ[name] for name in ('SYSTEMROOT','WINDIR','TEMP','TMP') if name in os.environ}
        try:
            result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).with_name('payment_pdf_validator.py'))],
                input=data,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=6,env=environment,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
            if result.returncode!=0 or result.stdout.strip()!=b'OK': raise ValueError()
        except (subprocess.TimeoutExpired,OSError,ValueError):
            raise InvalidPaymentFile('Use a valid static PDF up to 10 pages, without encryption, forms, attachments or active links. You can upload a JPG/PNG instead.') from None
        media='application/pdf'; suffix='.pdf'
    else:
        expected='PNG' if extension=='.png' else 'JPEG'
        if (expected=='PNG' and not data.startswith(b'\x89PNG\r\n\x1a\n')) or (expected=='JPEG' and not data.startswith(b'\xff\xd8\xff')):
            raise InvalidPaymentFile('The file contents do not match its extension.')
        if expected=='PNG' and not data.endswith(b'IEND\xaeB`\x82') or expected=='JPEG' and not data.rstrip().endswith(b'\xff\xd9'):
            raise InvalidPaymentFile('Choose a complete image without appended content.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(BytesIO(data),formats=[expected]) as image:
                    if image.width>10000 or image.height>10000 or image.width*image.height>20_000_000 or getattr(image,'is_animated',False): raise ValueError()
                    image.verify()
                with Image.open(BytesIO(data),formats=[expected]) as image: image.load()
        except (UnidentifiedImageError,OSError,SyntaxError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise InvalidPaymentFile('Choose a valid still image up to 10,000 pixels per side and 20 megapixels.') from None
        media='image/png' if expected=='PNG' else 'image/jpeg'; suffix='.png' if expected=='PNG' else '.jpg'
    return {'data':data,'media_type':media,'suffix':suffix,'byte_count':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def sanitize_mobile_slip(slip):
    """Strip image metadata and apply orientation without reducing readability."""
    if slip['media_type']=='application/pdf':return slip
    try:
        with Image.open(BytesIO(slip['data'])) as original:
            image=ImageOps.exif_transpose(original)
            image=image.convert('RGBA' if image.mode in ('RGBA','P') else 'RGB')
            # Saving an existing Pillow image may implicitly copy EXIF/PNG info.
            # Rebuild pixels only so GPS and other metadata cannot survive.
            image=Image.frombytes(image.mode,image.size,image.tobytes())
            output=BytesIO()
            if slip['media_type']=='image/jpeg':image.convert('RGB').save(output,format='JPEG',quality=95)
            else:image.save(output,format='PNG')
            data=output.getvalue()
        if len(data)>upload_limit():raise InvalidPaymentFile('The processed photo exceeds the upload limit. Choose a smaller image.')
        return {**slip,'data':data,'byte_count':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    except (OSError,ValueError):raise InvalidPaymentFile('Could not process this photo. Choose another JPG or PNG.') from None


def store_slip(slip):
    filename=uuid.uuid4().hex+slip['suffix']; destination=evidence_path(filename)
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.tmp',delete=False) as output:
            temporary=Path(output.name); output.write(slip['data']); output.flush(); os.fsync(output.fileno())
        os.replace(temporary,destination)
    finally:
        if temporary: temporary.unlink(missing_ok=True)
    return filename
