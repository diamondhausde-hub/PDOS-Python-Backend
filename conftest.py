import sys
import pytest

# conftest.py — instruct pytest to ignore non-pytest script files
collect_ignore = [
    "test_map.py",
    "test_cov.py",
    "test_api.py",
    "scripts/test_storage.py",
    "scripts/test_redis_pubsub.py",
    "test_endpoints.py",
    "test_sup.py",
    "test_targets.py",
    "final_test.py",
]
