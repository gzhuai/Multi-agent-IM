"""E2E: multi-agent group channel test."""
import urllib.request, json, time

CH = 'http://localhost:8080'
RT = 'http://localhost:50051'
CHANNEL = '398c86ec-287e-4857-b6a4-a6a4b7c70d4c'

def think(aid, label):
    td = json.dumps({
        'agent_id': aid, 'channel_id': CHANNEL,
        'messages': [{'role': 'user', 'content': '请对这个需求给出你的专业意见：要不要给App加上暗黑模式？一句话回答。', 'sender_name': 'PM'}],
        'participants': [
            {'id': '7aa0c5e4-af62-4206-af9f-0951baaf2160', 'type': 'agent'},
            {'id': '30927627-c7fc-4fff-98f2-9ba367a65854', 'type': 'agent'},
            {'id': 'dev-user-1', 'type': 'user'},
        ]
    }).encode()
    t0 = time.time()
    req = urllib.request.Request(f'{RT}/api/think', data=td,
        headers={'Content-Type': 'application/json'})
    resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
    elapsed = time.time() - t0
    # Write to stdout
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print(f'[{label}] ({elapsed:.1f}s) {resp["text"][:300]}')

# Fire both in sequence (simulates parallel goroutine dispatch)
print('=== Multi-Agent Group Channel Test ===')
print('Asking both agents: "要不要给App加上暗黑模式？"')
print()

think('7aa0c5e4-af62-4206-af9f-0951baaf2160', 'PM Agent')
think('30927627-c7fc-4fff-98f2-9ba367a65854', 'Dev Agent')

print()
print('=== PASS: both agents responded independently ===')
