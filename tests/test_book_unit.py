import os
import uuid

import pytest
import httpx


BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as c:
        yield c


async def _create_branch(client: httpx.AsyncClient) -> dict:
    payload = {"name": _uniq("branch"), "address": _uniq("addr")}
    r = await client.post("/branches", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _create_faculty(client: httpx.AsyncClient, name: str | None = None) -> dict:
    payload = {"name": name or _uniq("faculty")}
    r = await client.post("/faculties", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _create_book(client: httpx.AsyncClient, title: str | None = None) -> dict:
    payload = {
        "title": title or _uniq("book"),
        "authors": "Test Author",
        "publisher": "Test Publisher",
        "year": 2025,
        "pages": 100,
        "illustrations": 5,
        "price": "10.50",
    }
    r = await client.post("/books", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _set_stock(client: httpx.AsyncClient, book_id: int, branch_id: int, qty: int) -> dict:
    r = await client.put("/admin/stock", json={"book_id": book_id, "branch_id": branch_id, "quantity": qty})
    assert r.status_code == 200, r.text
    return r.json()


async def _link_book_faculty(client: httpx.AsyncClient, book_id: int, faculty_id: int) -> None:
    r = await client.post("/admin/book-faculty", json={"book_id": book_id, "faculty_id": faculty_id})
    assert r.status_code == 201, r.text


async def _unlink_book_faculty(client: httpx.AsyncClient, book_id: int, faculty_id: int) -> None:
    r = await client.delete("/admin/book-faculty", params={"book_id": book_id, "faculty_id": faculty_id})
    assert r.status_code in (200, 404), r.text


# --------------------
# Smoke
# --------------------

@pytest.mark.smoke
@pytest.mark.anyio
async def test_root_ok(client):
    """Smoke: сервис отвечает на корневой эндпоинт"""
    r = await client.get("/")
    assert r.status_code == 200
    assert r.json() == {"message": "ok"}


# --------------------
# Catalog: Books
# --------------------

@pytest.mark.catalog
@pytest.mark.anyio
async def test_books_crud(client):
    """Catalog: CRUD книги"""
    book = await _create_book(client)
    book_id = book["id"]

    r = await client.get(f"/books/{book_id}")
    assert r.status_code == 200
    assert r.json()["id"] == book_id

    new_title = _uniq("book-upd")
    r = await client.put(f"/books/{book_id}", json={"title": new_title})
    assert r.status_code == 200
    assert r.json()["title"] == new_title

    r = await client.get("/books")
    assert r.status_code == 200
    assert any(x["id"] == book_id for x in r.json())

    r = await client.delete(f"/books/{book_id}")
    assert r.status_code == 200


@pytest.mark.catalog
@pytest.mark.errors
@pytest.mark.anyio
async def test_books_duplicate_409(client):
    """Errors: дубликат книги должен давать 409"""
    payload = {
        "title": _uniq("dup-book"),
        "authors": "A",
        "publisher": "P",
        "year": 2025,
        "pages": 10,
        "illustrations": 0,
        "price": "1.00",
    }

    r1 = await client.post("/books", json=payload)
    assert r1.status_code == 201, r1.text
    book_id = r1.json()["id"]

    r2 = await client.post("/books", json=payload)
    assert r2.status_code == 409

    await client.delete(f"/books/{book_id}")


# --------------------
# Catalog: Branches + Faculties
# --------------------

@pytest.mark.catalog
@pytest.mark.anyio
async def test_branches_crud(client):
    """Catalog: CRUD филиала"""
    b = await _create_branch(client)
    branch_id = b["id"]

    r = await client.get("/branches")
    assert r.status_code == 200
    assert any(x["id"] == branch_id for x in r.json())

    r = await client.put(f"/branches/{branch_id}", json={"address": _uniq("addr-upd")})
    assert r.status_code == 200

    r = await client.delete(f"/branches/{branch_id}")
    assert r.status_code == 200


@pytest.mark.catalog
@pytest.mark.anyio
async def test_faculties_crud(client):
    """Catalog: CRUD факультета"""
    f = await _create_faculty(client)
    faculty_id = f["id"]

    r = await client.get("/faculties")
    assert r.status_code == 200
    assert any(x["id"] == faculty_id for x in r.json())

    r = await client.put(f"/faculties/{faculty_id}", json={"name": _uniq("faculty-upd")})
    assert r.status_code == 200

    r = await client.delete(f"/faculties/{faculty_id}")
    assert r.status_code == 200


@pytest.mark.catalog
@pytest.mark.errors
@pytest.mark.anyio
async def test_faculty_duplicate_409(client):
    """Errors: дубликат факультета по name должен давать 409"""
    name = _uniq("faculty-dup")

    r1 = await client.post("/faculties", json={"name": name})
    assert r1.status_code == 201, r1.text
    faculty_id = r1.json()["id"]

    r2 = await client.post("/faculties", json={"name": name})
    assert r2.status_code == 409

    await client.delete(f"/faculties/{faculty_id}")


# --------------------
# Admin
# --------------------

@pytest.mark.admin
@pytest.mark.anyio
async def test_admin_stock(client):
    """Admin: установка количества экземпляров книги в филиале"""
    branch = await _create_branch(client)
    book = await _create_book(client)

    out = await _set_stock(client, book["id"], branch["id"], 7)
    assert out["quantity"] == 7

    out = await _set_stock(client, book["id"], branch["id"], 0)
    assert out["quantity"] == 0

    await client.delete(f"/books/{book['id']}")
    await client.delete(f"/branches/{branch['id']}")


@pytest.mark.admin
@pytest.mark.anyio
async def test_admin_book_faculty_link_unlink(client):
    """Admin: связь книга-факультет (создание и удаление)"""
    book = await _create_book(client)
    faculty = await _create_faculty(client)

    await _link_book_faculty(client, book["id"], faculty["id"])
    await _unlink_book_faculty(client, book["id"], faculty["id"])

    await client.delete(f"/books/{book['id']}")
    await client.delete(f"/faculties/{faculty['id']}")


# --------------------
# Analytics
# --------------------

@pytest.mark.analytics
@pytest.mark.anyio
async def test_analytics_quantity(client):
    """Analytics: количество экземпляров книги в филиале"""
    branch = await _create_branch(client)
    book = await _create_book(client)

    await _set_stock(client, book["id"], branch["id"], 3)

    r = await client.get(f"/analytics/branches/{branch['id']}/books/{book['id']}/quantity")
    assert r.status_code == 200
    assert r.json()["quantity"] == 3

    await _set_stock(client, book["id"], branch["id"], 0)
    await client.delete(f"/books/{book['id']}")
    await client.delete(f"/branches/{branch['id']}")


@pytest.mark.analytics
@pytest.mark.anyio
async def test_analytics_faculties(client):
    """Analytics: список факультетов, использующих книгу, если в филиале есть экземпляры"""
    branch = await _create_branch(client)
    book = await _create_book(client)
    fac1 = await _create_faculty(client)
    fac2 = await _create_faculty(client)

    await _link_book_faculty(client, book["id"], fac1["id"])
    await _link_book_faculty(client, book["id"], fac2["id"])

    # нет экземпляров в филиале -> пусто
    r = await client.get(f"/analytics/branches/{branch['id']}/books/{book['id']}/faculties")
    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert r.json()["faculties"] == []

    # добавили экземпляры -> видим факультеты
    await _set_stock(client, book["id"], branch["id"], 1)

    r = await client.get(f"/analytics/branches/{branch['id']}/books/{book['id']}/faculties")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert set(data["faculties"]) == {fac1["name"], fac2["name"]}

    # cleanup
    await _set_stock(client, book["id"], branch["id"], 0)
    await _unlink_book_faculty(client, book["id"], fac1["id"])
    await _unlink_book_faculty(client, book["id"], fac2["id"])
    await client.delete(f"/books/{book['id']}")
    await client.delete(f"/branches/{branch['id']}")
    await client.delete(f"/faculties/{fac1['id']}")
    await client.delete(f"/faculties/{fac2['id']}")


# --------------------
# Errors (restrictions)
# --------------------

@pytest.mark.errors
@pytest.mark.anyio
async def test_cannot_delete_book_if_in_stock(client):
    """Errors: нельзя удалить книгу, если она числится в филиале (quantity > 0)"""
    branch = await _create_branch(client)
    book = await _create_book(client)

    await _set_stock(client, book["id"], branch["id"], 2)

    r = await client.delete(f"/books/{book['id']}")
    assert r.status_code == 409

    await _set_stock(client, book["id"], branch["id"], 0)
    r = await client.delete(f"/books/{book['id']}")
    assert r.status_code == 200

    await client.delete(f"/branches/{branch['id']}")


@pytest.mark.errors
@pytest.mark.anyio
async def test_cannot_delete_faculty_if_linked(client):
    """Errors: нельзя удалить факультет, если есть связь книга-факультет"""
    faculty = await _create_faculty(client)
    book = await _create_book(client)

    await _link_book_faculty(client, book["id"], faculty["id"])

    r = await client.delete(f"/faculties/{faculty['id']}")
    assert r.status_code == 409

    await _unlink_book_faculty(client, book["id"], faculty["id"])
    r = await client.delete(f"/faculties/{faculty['id']}")
    assert r.status_code == 200

    await client.delete(f"/books/{book['id']}")


@pytest.mark.errors
@pytest.mark.anyio
async def test_cannot_delete_branch_if_has_stock(client):
    """Errors: нельзя удалить филиал, если в нем числятся книги (quantity > 0)"""
    branch = await _create_branch(client)
    book = await _create_book(client)

    await _set_stock(client, book["id"], branch["id"], 1)

    r = await client.delete(f"/branches/{branch['id']}")
    assert r.status_code == 409

    await _set_stock(client, book["id"], branch["id"], 0)
    r = await client.delete(f"/branches/{branch['id']}")
    assert r.status_code == 200

    await client.delete(f"/books/{book['id']}")
