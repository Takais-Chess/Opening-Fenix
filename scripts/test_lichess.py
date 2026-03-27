import urllib.request
import urllib.parse
import json
import os

def get_user_dir():
    # Helper to get the project root for dev environment
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(script_dir)

fen = "r1b1kbnr/pp2pppp/2n5/2pq4/5P2/8/PPPPB1PP/RNBQK1NR w KQkq -"
# Testing masters database
params = {
    'variant': 'standard',
    'fen': fen
}
query_string = urllib.parse.urlencode(params)
url = f"https://explorer.lichess.org/masters?{query_string}"
print(f"URL: {url}")

config_path = os.path.join(get_user_dir(), "config.json")
lichess_token = None
if os.path.exists(config_path):
    try:
        with open(config_path, "r") as f:
            conf = json.load(f)
            lichess_token = conf.get("lichess_token")
    except: pass

headers = {'User-Agent': 'OpeningFenix/1.0'}
if lichess_token and lichess_token != "YOUR_TOKEN_HERE":
    headers['Authorization'] = f'Bearer {lichess_token}'
    print("Using Lichess API Token from config.json")
else:
    print("Warning: No Lichess API Token found in config.json")

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req) as response:
        print("Success! Data received:")
        print(response.read().decode('utf-8')[:200] + "...")
except Exception as e:
    print(f"Error fetching from Lichess: {e}")
