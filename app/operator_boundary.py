"""Socket boundary for the local desk and explicitly authenticated exposure.

Actor names and Origin are evidence labels, never remote authorization.
Remote device ingest uses its own token, separate from operator actions.
"""
import hmac
import ipaddress
import os
from urllib.parse import urlsplit


def loopback(address):
    try: return ipaddress.ip_address(address).is_loopback
    except ValueError: return False


def operator_allowed(handler, device=False):
    bound = handler.server.server_address
    local = loopback(bound[0]) and loopback(handler.client_address[0])
    origin, host = handler.headers.get('Origin'), handler.headers.get('Host', '')
    try:
        authority = urlsplit('//'+host)
        if authority.username or authority.password or authority.path or authority.query or authority.fragment: return False
        if local and (authority.hostname not in ('localhost', '127.0.0.1', '::1') or authority.port != bound[1]): return False
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or parsed.netloc != host or parsed.path or parsed.query or parsed.fragment: return False
    except ValueError: return False
    if local: return True
    token = os.environ.get('RESCUE_DEVICE_TOKEN' if device else 'RESCUE_OPERATOR_TOKEN', '')
    # Container opt-in (Dockerfile): opens only POST /run (intake; cases still need human approval), and only while no operator token is set.
    if not token and not device and os.environ.get('RESCUE_OPEN_RUN', '').lower() in ('true', '1', 'yes') \
            and urlsplit(getattr(handler, 'path', '')).path == '/run': return True
    supplied = handler.headers.get('Authorization', '')
    return bool(token and hmac.compare_digest(supplied.encode(), ('Bearer '+token).encode()))


def guard_operator(handler, device=False):
    if operator_allowed(handler, device): return True
    # Drain bounded request bytes so Windows can deliver the rejection reliably.
    handler.close_connection = True
    try:
        size = int(handler.headers.get('Content-Length', '0'))
        if 0 < size <= 256000:
            handler.connection.settimeout(2)
            handler.rfile.read(size)
    except (ValueError, OSError): pass
    handler.send_json(403, {'error': 'Operação exige mesa local ou token autorizado.'})
    return False
