import pytest
import httpx

@pytest.mark.anyio
async def test_root_ok():
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        r = await client.get("/")
    assert r.status_code == 200
    assert r.json() == {"message": "ok"}