# Sync — one at a time
import time

def fetch(name, secs):
    time.sleep(secs)
    return f"got {name}"

start_time = time.perf_counter()
print(fetch("A", 1))  # waits 1s
print(fetch("B", 1))  # waits 1s more
# total: ~2s
end_time = time.perf_counter()
print(f"\nTotal time: {end_time - start_time:.2f}s")