import requests

def test_api():
    url = "http://127.0.0.1:8000/tasks/9a399aa2-164a-413d-86e6-b9fcf635c1cf"
    headers = {"Content-Type": "application/json"}
    # we don't have token but let's see if it gives 401
    res = requests.patch(url, json={"status": "in_progress"}, headers=headers)
    print("Status code:", res.status_code)
    print("Response:", res.text)

if __name__ == "__main__":
    test_api()
