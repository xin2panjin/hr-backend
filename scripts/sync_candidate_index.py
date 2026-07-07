import asyncio

from tasks.candidate_index_tasks import sync_candidate_index_batch


async def main() -> None:
    count = await sync_candidate_index_batch()
    print(f"Synced candidate index events: {count}")


if __name__ == "__main__":
    asyncio.run(main())