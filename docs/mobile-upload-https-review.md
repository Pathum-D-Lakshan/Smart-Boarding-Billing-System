# Approved limited mobile HTTPS demonstration

The user authorized completion of the public upload tunnel setup. Main stays on
loopback port 5000 with debug disabled. Only the narrow upload gateway listens
on loopback port 5002 and is forwarded publicly.

## Actual rollout

- Official portable cloudflared 2026.11.0 was downloaded; SHA-256 matched the
  release digest. Outbound port 7844 was blocked, so that process was stopped.
  No firewall rules were changed.
- The working fallback uses Pinggy HTTPS via existing Windows OpenSSH over port
  443. It uses a dedicated workspace SSH identity and pinned known-hosts file,
  without personal SSH identities, passwords, agent forwarding or a service.
- Only MOBILE_PUBLIC_BASE_URL and MOBILE_TRUST_LOCAL_PROXY were updated. Their
  previous values are checkpointed privately. Main was safely restarted.
- The follow-up user-approved Waitress 3.0.2 installation now serves the same main
  app on loopback port 5000, without debugger/traceback exposure. Health probes
  verify the configured origin fingerprint before generating a token. QR links
  last fifteen minutes; the free tunnel still lasts sixty minutes.
- The public page and CSS/JS returned HTTP 200; Login, portals, evidence and
  .env returned 404. Invalid-origin POST returned 403. Measured results are in
  instance/mobile_https_live_report.json.

Only these exact routes are forwarded:

```
GET/HEAD /mobile/payment-slip
GET/HEAD /static/css/mobile-payment-slip.css
GET/HEAD /static/js/mobile-payment-slip.js
POST /mobile/payment-slip/open
POST /mobile/payment-slip/save
```

The gateway strips portal cookies and forwards only the dedicated capability
cookie. It rejects unsupported routes, ambiguous framing, oversized uploads,
chunk extensions and trailers. Bounded chunked bodies from the relay are decoded
and forwarded with one computed Content-Length. It logs no tokens or evidence.

HTTPS traffic traverses the tunnel provider. This temporary demonstration is
not production hosting. The free Pinggy session expires after 60 minutes;
the first browser visit displays an **Enter site** warning. Its continuation
reloads the same URL, preserving the token fragment. Physical-phone camera,
QR scanning and actual Gmail inbox receipt still require user verification.

No production token, payment, account or test email was created by rollout QA.
Owner bank details still need to be saved before an actual payment submission.

## Start and stop

See [mobile-upload-demo.md](mobile-upload-demo.md) for commands. The stop helper
verifies process identities, stops only the recorded tunnel/gateway, restores
the two prior mobile settings and restarts the main app. It preserves database
and evidence records. Never expose port 5000, MySQL or debug mode directly.

Provider references:

- https://pinggy.io/docs/usages/
- https://pinggy.io/docs/http_tunnels/screening/
- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/
