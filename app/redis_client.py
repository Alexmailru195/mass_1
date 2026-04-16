import redis
import time
import json

# Создаем клиент
client = redis.Redis(host='redis', port=6379, decode_responses=True)

def update_status(user_id: int):
    try:
        client.set(f"user:{user_id}:last_seen", int(time.time()), ex=300)
    except Exception as e:
        print(f"Redis Error (status): {e}")

def get_status(user_id: int) -> str:
    try:
        last = client.get(f"user:{user_id}:last_seen")
        if not last: return "offline"
        diff = int(time.time()) - int(last)
        if diff < 60: return "online"
        if diff < 3600: return f"был {diff//60} мин. назад"
        return f"был {diff//3600} ч. назад"
    except:
        return "offline"

def publish(channel: str, data: dict):
    try:
        client.publish(channel, json.dumps(data))
    except Exception as e:
        print(f"Redis Error (pub): {e}")