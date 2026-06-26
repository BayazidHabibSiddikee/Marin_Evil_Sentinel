# Async — concurrent
import asyncio, time

async def fetch(name, secs):
    await asyncio.sleep(secs)
    return f"got {name}"

async def main():
    start_time = time.perf_counter()
    result = await asyncio.gather(
                fetch("A", 1),
                fetch("B", 1),
            )
    # total: ~1s  ✓
    print(result)
    end_time = time.perf_counter()
    print(f"\nTotal time: {end_time - start_time:.2f}s")

if __name__ =="__main__":
    asyncio.run(main())