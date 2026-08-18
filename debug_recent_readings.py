import database
from itertools import islice

def main(limit=100):
    rows = database.get_all_readings()
    rows = list(reversed(rows))  # newest first
    print(f"Showing up to {limit} most recent readings (newest first):\n")
    for r in rows[:limit]:
        ts = r.get('timestamp')
        vib = r.get('vibration')
        seed = r.get('is_seed')
        status = r.get('status')
        temp = r.get('temperature')
        hum = r.get('humidity')
        print(f"{ts}  T={temp}  H={hum}  V={vib}  status={status}  is_seed={seed}")

if __name__ == '__main__':
    main(200)
