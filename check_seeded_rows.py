import database
import datetime
import json

def check(days):
    since=(datetime.datetime.utcnow()-datetime.timedelta(days=days)).isoformat()
    rows=database.get_readings_since(since)
    seeded=[r for r in rows if r.get('is_seed')==1]
    print(f"seeded in last {days} days: {len(seeded)}")
    if seeded:
        print(json.dumps([{'timestamp':r['timestamp'],'temperature':r['temperature'],'humidity':r['humidity'],'vibration':r['vibration']} for r in seeded[:10]], indent=2))

if __name__ == '__main__':
    check(30)
    print('---')
    check(7)
