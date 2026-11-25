"""Optional local-only gateway for an explicitly approved HTTPS upload tunnel.

Never exposes portal/login/MySQL/evidence endpoints. Does not launch a tunnel.
Run: python -B tools/mobile_upload_gateway.py --port 5002
"""
from http.client import HTTPConnection,HTTPException
from http.cookies import SimpleCookie,CookieError
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
import argparse
import re

GET_PATHS={'/mobile/payment-slip','/static/css/mobile-payment-slip.css','/static/js/mobile-payment-slip.js'}
POST_PATHS={'/mobile/payment-slip/open','/mobile/payment-slip/save'}
MAX_BODY=6*1024*1024
COOKIE='boarding_slip_capability'


class RequestBodyError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status


class UploadGateway(BaseHTTPRequestHandler):
    upstream_port=5000
    def log_message(self,*args):pass # Never log bearer cookies or upload contents.

    def do_GET(self):self.forward()
    def do_HEAD(self):self.forward()
    def do_POST(self):self.forward()

    def fail(self,status,message):
        data=message.encode();self.send_response(status)
        self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(data)));self.end_headers()
        if self.command!='HEAD':self.wfile.write(data)

    def read_body(self):
        lengths=self.headers.get_all('Content-Length',[])
        encodings=self.headers.get_all('Transfer-Encoding',[])
        if len(lengths)>1 or len(encodings)>1 or (lengths and encodings):raise RequestBodyError('Ambiguous request framing.')
        if encodings:
            if self.command!='POST' or encodings[0].strip().lower()!='chunked':raise RequestBodyError('Unsupported request framing.')
            # HTTPS/HTTP2 relays may stream browser uploads as chunked HTTP/1.1.
            # Decode within the same total limit, then forward a single length.
            parts=[];total=0
            for _ in range(4096):
                line=self.rfile.readline(32)
                if not re.fullmatch(rb'[0-9a-fA-F]{1,8}\r\n',line):raise RequestBodyError('Invalid upload framing.')
                size=int(line[:-2],16)
                if not size:
                    if self.rfile.readline(3)!=b'\r\n':raise RequestBodyError('Upload trailers are not supported.')
                    return b''.join(parts)
                total+=size
                if total>MAX_BODY:raise RequestBodyError('Upload too large.',413)
                chunk=self.rfile.read(size)
                if len(chunk)!=size or self.rfile.read(2)!=b'\r\n':raise RequestBodyError('Incomplete upload.')
                parts.append(chunk)
            raise RequestBodyError('Too many upload chunks.',413)
        raw=lengths[0] if lengths else '0'
        if not re.fullmatch(r'[0-9]{1,10}',raw):raise RequestBodyError('Invalid upload length.')
        size=int(raw)
        if size>MAX_BODY:raise RequestBodyError('Upload too large.',413)
        if self.command!='POST' and size:raise RequestBodyError('Unexpected request body.')
        body=self.rfile.read(size) if size else b''
        if len(body)!=size:raise RequestBodyError('Incomplete upload.')
        return body

    def forward(self):
        parsed=urlsplit(self.path)
        allowed=POST_PATHS if self.command=='POST' else GET_PATHS
        if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path not in allowed:return self.fail(404,'Not available on this upload gateway.')
        self.connection.settimeout(20)
        try:body=self.read_body()
        except RequestBodyError as invalid:return self.fail(invalid.status,str(invalid))
        except (OSError,TimeoutError):return self.fail(408,'Upload timed out.')
        headers={key:self.headers[key] for key in ('Content-Type','Origin','X-Mobile-Upload') if self.headers.get(key)}
        headers['X-Forwarded-Proto']='https'
        try:
            cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
            if COOKIE in cookies:headers['Cookie']=cookies[COOKIE].OutputString()
        except CookieError:return self.fail(400,'Invalid cookie.')
        upstream=HTTPConnection('127.0.0.1',self.upstream_port,timeout=20)
        try:
            upstream.request(self.command,self.path,body=body,headers=headers)
            response=upstream.getresponse();data=response.read(2*1024*1024+1)
            if len(data)>2*1024*1024:return self.fail(502,'Unexpected upstream response.')
            self.send_response(response.status)
            for key,value in response.getheaders():
                if key.lower() in ('content-type','cache-control','content-security-policy','referrer-policy','permissions-policy','x-content-type-options','x-smart-boarding-upload'):
                    self.send_header(key,value)
                elif key.lower()=='set-cookie' and value.startswith(COOKIE+'='):self.send_header(key,value)
            self.send_header('Content-Length',str(len(data)));self.end_headers()
            if self.command!='HEAD':self.wfile.write(data)
        except (OSError,HTTPException):self.fail(503,'The upload service is unavailable.')
        finally:upstream.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=5002)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('Use a valid unprivileged local port.')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),UploadGateway)
    print('Local-only mobile upload gateway ready. No public tunnel was started.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
