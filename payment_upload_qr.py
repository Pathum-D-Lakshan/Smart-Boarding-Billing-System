"""Private QR images using the project's existing ReportLab and Pillow packages."""
import base64
from io import BytesIO
from PIL import Image,ImageDraw
from reportlab.graphics.barcode.qr import QrCodeWidget


def upload_qr_data_uri(url):
    """Render integer-sized modules and a four-module white quiet zone locally."""
    if not isinstance(url,str) or not url.startswith('https://') or len(url)>1024:
        raise ValueError('A bounded HTTPS upload URL is required.')
    encoder=QrCodeWidget(url,barLevel='M').qr
    encoder.make()
    modules=encoder.modules;scale=8;border=4
    side=(len(modules)+border*2)*scale
    image=Image.new('1',(side,side),1);draw=ImageDraw.Draw(image)
    for y,row in enumerate(modules):
        for x,dark in enumerate(row):
            if dark:
                left=(x+border)*scale;top=(y+border)*scale
                draw.rectangle((left,top,left+scale-1,top+scale-1),fill=0)
    output=BytesIO();image.save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode('ascii')
