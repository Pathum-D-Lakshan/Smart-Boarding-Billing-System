"""Read-only public probes: never create a real Student token or payment."""
from pathlib import Path
import sys,json,hashlib,urllib.request,urllib.error
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from app import app
from db import get_db_connection
from mobile_payment_service import public_base
from mobile_upload_health import require_available

with app.app_context():origin=public_base()
with app.app_context():require_available(origin)
session_state=json.loads((root/'instance/mobile_https_session.json').read_text(encoding='utf-8-sig'))
assert session_state['public_url']==origin
assert app.config['MOBILE_TRUST_LOCAL_PROXY'] and not app.debug
headers={'User-Agent':'SmartBoarding-HTTPS-Verification','X-Pinggy-No-Screen':'1'}
checks={}
def probe(path,*,method='GET',browser=False):
    request_headers={'User-Agent':'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1'} if browser else headers
    request=urllib.request.Request(origin+path,headers=request_headers,method=method)
    try:
        with urllib.request.urlopen(request,timeout=15) as response:return response.status,response.headers,response.read()
    except urllib.error.HTTPError as error:return error.code,error.headers,error.read()

status,response_headers,body=probe('/mobile/payment-slip')
assert status==200 and b'slip-live-camera' in body
assert response_headers.get('Cache-Control')=='no-store'
assert 'camera=(self)' in response_headers.get('Permissions-Policy','')
checks['upload_page']={'status':status,'actual_app_html':True,'no_store':True,'camera_policy':True}
for asset in ('css/mobile-payment-slip.css','js/mobile-payment-slip.js'):
    status,_,data=probe('/static/'+asset)
    match=hashlib.sha256(data).digest()==hashlib.sha256((root/'static'/asset).read_bytes()).digest()
    assert status==200 and match
    checks[asset]={'status':status,'matches_workspace':match}
for path in ('/login','/dashboard/owner','/owner/payments','/student/payments','/.env','/payments/1/slip','/static/../app.py'):
    status,_,_=probe(path);assert status==404,(path,status);checks[path]={'status':status}
status,_,_=probe('/mobile/payment-slip/open',method='POST')
assert status==403 # Wrong/missing Origin blocked before any rate-limit write.
checks['invalid_origin_post']={'status':status}
browser_status,_,browser_body=probe('/mobile/payment-slip',browser=True)
browser_screen=browser_status==200 and b'slip-live-camera' not in browser_body
with get_db_connection() as c,c.cursor(dictionary=True) as q:
    c.start_transaction(readonly=True)
    q.execute('SELECT COUNT(*) AS count FROM payment_upload_links');tokens=q.fetchone()['count']
    q.execute('SELECT COUNT(*) AS count FROM payment_notifications');jobs=q.fetchone()['count']
    q.execute('SELECT COUNT(*) AS count FROM owner_settings WHERE account_number IS NOT NULL');banks=q.fetchone()['count']
with urllib.request.urlopen('http://127.0.0.1:5000/login',timeout=5) as main_response:
    main_server=main_response.headers.get('Server')
report={'origin':origin,'provider':'pinggy','origin_matches_session_metadata':True,'fresh_token_health_gate':'PASS',
    'main_server':main_server,'checks':checks,'browser_first_visit_screen':browser_screen,
    'main_upload_links':tokens,'main_notifications':jobs,'owner_bank_configured':banks>0,
    'main_debug':app.debug,'verification_created_records':False,'physical_phone_tested':False,'real_email_or_whatsapp_sent':False}
(root/'instance/mobile_https_live_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
