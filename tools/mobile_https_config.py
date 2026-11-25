"""Change only the two approved mobile ingress settings; never print .env."""
from pathlib import Path
from urllib.parse import urlsplit
import argparse,json
from dotenv import dotenv_values,set_key,unset_key

ROOT=Path(__file__).resolve().parents[1]
PREVIOUS=ROOT/'instance/mobile_https_previous_config.json'
KEYS=('MOBILE_PUBLIC_BASE_URL','MOBILE_TRUST_LOCAL_PROXY')


def activate(url):
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or not p.hostname.endswith(('.trycloudflare.com','.pinggy.link','.pinggy-free.link','.free.pinggy.net')) or p.username or p.password or p.path not in ('','/') or p.query or p.fragment or p.port not in (None,443):
        raise ValueError('Expected the actual temporary HTTPS tunnel origin.')
    settings=dotenv_values(ROOT/'.env',interpolate=False)
    if not PREVIOUS.exists():PREVIOUS.write_text(json.dumps({key:settings.get(key) for key in KEYS},indent=2),encoding='utf-8')
    set_key(ROOT/'.env','MOBILE_PUBLIC_BASE_URL',url.rstrip('/'),quote_mode='never')
    set_key(ROOT/'.env','MOBILE_TRUST_LOCAL_PROXY','1',quote_mode='never')


def restore():
    if not PREVIOUS.exists():raise ValueError('Previous mobile settings checkpoint is missing.')
    previous=json.loads(PREVIOUS.read_text(encoding='utf-8'))
    if set(previous)!=set(KEYS):raise ValueError('Unexpected mobile settings checkpoint.')
    for key,value in previous.items():
        if value is None:unset_key(ROOT/'.env',key)
        else:set_key(ROOT/'.env',key,value,quote_mode='never')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('activate','restore'));parser.add_argument('url',nargs='?')
    args=parser.parse_args()
    if args.action=='activate':activate(args.url or '')
    else:restore()
    print('Approved mobile ingress settings updated; other environment values preserved.')
