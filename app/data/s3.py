"""Minimal path-style AWS SigV4 PUT/GET adapted from gate0_zetaris_s3.py."""
import datetime
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request
from app.config import setting


class S3:
    def request(self, method, key='', body=b'', create_bucket=False):
        access, secret = setting('S3_ACCESS_KEY'), setting('S3_SECRET_KEY')
        if not access or not secret:
            raise RuntimeError('S3 credentials missing')
        endpoint = setting('S3_ENDPOINT_HOST', '127.0.0.1:8333')
        if '://' not in endpoint:
            endpoint = 'http://'+endpoint
        parsed = urllib.parse.urlsplit(endpoint)
        path = '/'+setting('S3_BUCKET', 'oah-data')+('/'+key if key else '')
        path = urllib.parse.quote(path, safe='/-_.~')
        now = datetime.datetime.now(datetime.timezone.utc)
        amz, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
        payload_hash = hashlib.sha256(body).hexdigest()
        headers = {'host': parsed.netloc, 'x-amz-content-sha256': payload_hash, 'x-amz-date': amz}
        signed = ';'.join(sorted(headers))
        canonical = '\n'.join([method, path, '', ''.join(f'{k}:{headers[k]}\n' for k in sorted(headers)), signed, payload_hash])
        scope = day+'/us-east-1/s3/aws4_request'
        string_to_sign = '\n'.join(['AWS4-HMAC-SHA256', amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        signing_key = ('AWS4'+secret).encode()
        for part in (day, 'us-east-1', 's3', 'aws4_request'):
            signing_key = hmac.new(signing_key, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers['Authorization'] = f'AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed}, Signature={signature}'
        request = urllib.request.Request(f'{parsed.scheme}://{parsed.netloc}{path}', method=method,
                                         data=body if method == 'PUT' else None, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if create_bucket and exc.code == 409:
                return b''
            raise RuntimeError('S3 request failed: HTTP '+str(exc.code)) from None

    def put(self, key, body):
        return self.request('PUT', key, body)

    def get(self, key):
        return self.request('GET', key)
