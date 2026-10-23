import urllib.request, json

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/public/scan',
    data=json.dumps({'url': 'https://icrowd.lk/'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print('Real Target URL:', data.get('target_url'))
        print('Real Score:', data.get('score'))
        print('Real Status:', data.get('score_status', {}).get('status'))
        print('First 4 Categories:')
        for c in data.get('categories', [])[:4]:
            print(f"  {c['name']}: {c['score']}% ({c['status']})")
except Exception as e:
    print('Error:', e)
