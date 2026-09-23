"""Redis Pub/Sub test — validates publish and subscribe within one Python process."""

import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

CHANNEL = "notifications"
TIMEOUT = 10


async def test():
    import redis.asyncio as aioredis

    r = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(CHANNEL)

    # Wait briefly for subscription to register
    await asyncio.sleep(0.5)

    # Publish
    payload = json.dumps({"user_id": "test-user", "type": "test", "title": "CrossProcess", "message": "Hello"})
    await r.publish(CHANNEL, payload)

    # Receive
    while True:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=TIMEOUT)
        if msg and msg["type"] == "message":
            data = json.loads(msg["data"])
            assert data["user_id"] == "test-user"
            assert data["type"] == "test"
            print(f"Redis Pub/Sub TEST PASSED - received: {data['title']}: {data['message']}")
            break

    await pubsub.close()
    await r.close()


if __name__ == "__main__":
    asyncio.run(test())
