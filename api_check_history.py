import json
from urllib.request import urlopen


def main():
    url = 'http://localhost:5000/api/history'
    with urlopen(url, timeout=5) as resp:
        rows = json.load(resp)
    seeded = [row for row in rows if row.get('is_seed') == 1]
    print('rows returned:', len(rows))
    print('seeded rows in response:', len(seeded))
    if seeded:
        print('\nSample seeded rows:')
        print(json.dumps(seeded[:10], indent=2))

if __name__ == "__main__":
    main()
