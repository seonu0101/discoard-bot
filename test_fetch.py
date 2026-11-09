"""상위 10명 가져오기 테스트: python test_fetch.py"""
import json
import urllib.request

URL = "https://leaderboard.bettermultiplayer.com/leaderboard/0?limit=10&offset=0"

req = urllib.request.Request(URL, headers={"User-Agent": "leaderboard-discord-bot"})
with urllib.request.urlopen(req, timeout=10) as r:
    data = json.load(r)

print(f"카테고리: {data['track_name']} / 전체 {data['total']}명\n")
for p in data["data"]:
    print(f"{p['rank_position']:>2}위  {p['player']['persona_name']:<20} {p['player']['avatar_url']}")
