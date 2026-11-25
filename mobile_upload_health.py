"""Check the configured upload origin before creating a bearer capability."""
import hashlib
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import URLError

UNAVAILABLE = 'Mobile upload is temporarily unavailable. Restart the demo tunnel and create a fresh QR, or use Upload from Computer.'


def origin_fingerprint(origin):
    # Public configuration identity, not a token or credential. A recycled
    # hostname must not accidentally pass as this application's upload page.
    return hashlib.sha256(origin.encode('utf-8')).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def require_available(origin):
    from mobile_payment_service import UploadLinkError
    request = Request(origin + '/mobile/payment-slip', headers={
        'User-Agent': 'SmartBoarding-Mobile-Health',
        'X-Pinggy-No-Screen': '1',  # Provider-supported non-browser health probe.
        'Cache-Control': 'no-cache',
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=4) as response:
            body = response.read(256 * 1024 + 1)
            valid = (
                response.status == 200 and len(body) <= 256 * 1024
                and response.headers.get('X-Smart-Boarding-Upload') == origin_fingerprint(origin)
                and 'no-store' in response.headers.get('Cache-Control', '')
                and b'id="slip-content"' in body
            )
            if not valid:
                raise UploadLinkError(UNAVAILABLE)
    except (URLError, OSError, ValueError):
        # No external response body, credentials or bearer link enters logs/UI.
        raise UploadLinkError(UNAVAILABLE) from None
