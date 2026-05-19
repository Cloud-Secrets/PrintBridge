import json
from fastapi.testclient import TestClient
from print_server_app import api

client = TestClient(api)
resp = client.get('/openapi.json')
resp.raise_for_status()
openapi = resp.json()

with open('swagger.json', 'w', encoding='utf-8') as f:
    json.dump(openapi, f, ensure_ascii=False, indent=2)

print('swagger.json generated')
print('title:', openapi.get('info', {}).get('title'))
print('version:', openapi.get('info', {}).get('version'))
print('paths:', len(openapi.get('paths', {})))
