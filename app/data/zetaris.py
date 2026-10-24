"""Zetaris REST SQL client. SQL and response bodies are never printed."""
import json
import re
import urllib.error
import urllib.request
import uuid
from app.config import setting


def identifier(name):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
        raise ValueError('Invalid SQL identifier')
    return name


class Zetaris:
    def query(self, sql, limit=20000, timeout=120, allow_exists=False):
        key = setting('ZETARIS_API_KEY')
        if not key:
            raise RuntimeError('Zetaris key missing')
        request = urllib.request.Request(setting('ZETARIS_REST_URL', 'http://localhost:8888/api/v1.0').rstrip('/')+'/sql-editor/sqls/run',
            data=json.dumps({'queryId': str(uuid.uuid4()), 'sql': sql, 'source': 'SqlEditor', 'limit': limit}).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+key,
                     'X-Org-ID': setting('ZETARIS_ORG_ID', '1'), 'X-Request-ID': str(uuid.uuid4())})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # The body may echo secrets in CREATE SQL; inspect privately then discard.
            body = exc.read().decode('utf-8', 'replace')
            if allow_exists and 'already exist' in body.lower():
                return {'headers': [], 'data': [], 'total': 0, 'already_exists': True}
            raise RuntimeError('Zetaris SQL failed: HTTP '+str(exc.code)) from None

    def rows(self, table, timeout=120):
        table = identifier(table)
        data = self.query('SELECT * FROM OAH_S3.'+table, limit=25000, timeout=timeout)
        headers = [h if isinstance(h, str) else h.get('name', h.get('columnName')) for h in data['headers']]
        if any(not isinstance(h, str) for h in headers):
            raise ValueError('Unknown Zetaris headers shape')
        if int(data.get('total', len(data['data']))) > len(data['data']):
            raise ValueError('Zetaris result truncated; raise explicit row limit')
        return [dict(zip(headers, row)) for row in data['data']]
