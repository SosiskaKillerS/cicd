import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from main import (
    Book,
    Branch,
    Faculty,
    BookStock,
    BookCreate,
    StockUpsert,
    create_book,
    analytics_quantity,
    analytics_faculties,
    delete_book,
    upsert_stock,
)

"""
Файл содержит unit-тесты (без HTTP и без реальной БД): функции приложения вызываются напрямую, а вместо настоящей AsyncSession используется FakeSession, который имитирует методы scalar, execute, get, add, commit, rollback, refresh. 
Это позволяет изолированно проверить бизнес-логику и обработку ошибок.
Покрытие сценариев:
create_book: успешное создание (commit, refresh, выдача id) и обработка дубликата (IntegrityError → rollback → HTTPException 409).
analytics_quantity: при отсутствии записи в stock возвращается quantity=0.
analytics_faculties: при qty=0 возвращается пустой список; при qty>0 возвращается список факультетов и корректный count.
delete_book: запрет удаления при наличии экземпляров (qty>0 → 409); успешное удаление при qty=0 (delete + commit).
upsert_stock: 404 если книга не найдена; создание новой записи BookStock при отсутствии связи (add + commit) и корректные поля book_id/branch_id/quantity.
"""

# ----------------------------
# Fake async results/session
# ----------------------------

class _FakeScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeExecuteResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalarResult(self._items)


class FakeSession:
    """
    Минимальная подделка AsyncSession для unit тестов.
    Управляем возвратами через:
      - scalar_returns: список значений для await session.scalar(...)
      - execute_items: список значений, которые вернёт scalars().all()
      - get_map: dict {(ModelClass, key): obj}
      - fail_commit: если True -> commit кидает IntegrityError
    """

    def __init__(self, *, scalar_returns=None, execute_items=None, get_map=None, fail_commit=False):
        self.scalar_returns = list(scalar_returns or [])
        self.execute_items = list(execute_items or [])
        self.get_map = dict(get_map or {})
        self.fail_commit = fail_commit

        self.added = []
        self.deleted = []
        self.committed = False
        self.rolled_back = False
        self.refreshed = []

    @staticmethod
    def _key(ident):
        if isinstance(ident, dict):
            return tuple(sorted(ident.items()))
        return ident

    async def scalar(self, stmt):
        if not self.scalar_returns:
            return None
        return self.scalar_returns.pop(0)

    async def execute(self, stmt):
        return _FakeExecuteResult(self.execute_items)

    async def get(self, model, ident):
        return self.get_map.get((model, self._key(ident)))

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        if self.fail_commit:
            raise IntegrityError("stmt", {}, Exception("dup"))
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, obj):
        self.refreshed.append(obj)
        # имитируем, что БД выдала id
        if getattr(obj, "id", None) is None:
            obj.id = 1


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ----------------------------
# Unit tests
# ----------------------------

@pytest.mark.unit
@pytest.mark.anyio
async def test_create_book_success_unit():
    """Unit: create_book успешный commit и выдача id"""
    session = FakeSession()
    payload = BookCreate(
        title="T",
        authors="A",
        publisher="P",
        year=2025,
        pages=10,
        illustrations=0,
        price="1.00",
    )

    book = await create_book(payload=payload, session=session)

    assert isinstance(book, Book)
    assert book.id == 1
    assert session.committed is True
    assert len(session.added) == 1


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_book_duplicate_409_unit():
    """Unit: create_book при IntegrityError должен сделать rollback и вернуть 409"""
    session = FakeSession(fail_commit=True)
    payload = BookCreate(
        title="T",
        authors="A",
        publisher="P",
        year=2025,
        pages=10,
        illustrations=0,
        price="1.00",
    )

    with pytest.raises(HTTPException) as exc:
        await create_book(payload=payload, session=session)

    assert exc.value.status_code == 409
    assert session.rolled_back is True


@pytest.mark.unit
@pytest.mark.anyio
async def test_analytics_quantity_default_zero_unit():
    """Unit: analytics_quantity без записи в stock должен вернуть 0"""
    session = FakeSession(scalar_returns=[None])
    data = await analytics_quantity(branch_id=10, book_id=20, session=session)
    assert data == {"branch_id": 10, "book_id": 20, "quantity": 0}


@pytest.mark.unit
@pytest.mark.anyio
async def test_analytics_faculties_no_stock_unit():
    """Unit: analytics_faculties без экземпляров в филиале возвращает пустой список"""
    session = FakeSession(scalar_returns=[0])
    data = await analytics_faculties(branch_id=1, book_id=2, session=session)
    assert data["count"] == 0
    assert data["faculties"] == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_analytics_faculties_with_stock_unit():
    """Unit: analytics_faculties при qty > 0 возвращает список факультетов"""
    session = FakeSession(
        scalar_returns=[1],
        execute_items=["Math", "Physics"],
    )
    data = await analytics_faculties(branch_id=1, book_id=2, session=session)
    assert data["count"] == 2
    assert data["faculties"] == ["Math", "Physics"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_book_conflict_if_stock_gt0_unit():
    """Unit: delete_book запрещён если есть quantity > 0"""
    session = FakeSession(scalar_returns=[2])
    with pytest.raises(HTTPException) as exc:
        await delete_book(book_id=1, session=session)

    assert exc.value.status_code == 409
    assert session.committed is False


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_book_success_unit():
    """Unit: delete_book успешный путь когда stock=0"""
    book = Book(title="T", authors="A", publisher="P", year=2025, pages=10, illustrations=0, price=None)
    book.id = 1

    session = FakeSession(
        scalar_returns=[0],
        get_map={(Book, 1): book},
    )

    resp = await delete_book(book_id=1, session=session)

    assert resp["message"] == "deleted"
    assert session.committed is True
    assert book in session.deleted


@pytest.mark.unit
@pytest.mark.anyio
async def test_upsert_stock_book_not_found_unit():
    """Unit: upsert_stock возвращает 404 если книги нет"""
    session = FakeSession(get_map={(Book, 1): None})
    payload = StockUpsert(book_id=1, branch_id=2, quantity=5)

    with pytest.raises(HTTPException) as exc:
        await upsert_stock(payload=payload, session=session)

    assert exc.value.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_upsert_stock_create_new_unit():
    """Unit: upsert_stock создаёт новую запись если stock ещё нет"""
    book = Book(title="T", authors="A", publisher="P", year=2025, pages=10, illustrations=0, price=None)
    book.id = 1
    branch = Branch(name="B", address="Addr")
    branch.id = 2

    session = FakeSession(
        get_map={
            (Book, 1): book,
            (Branch, 2): branch,
            (BookStock, tuple(sorted({"book_id": 1, "branch_id": 2}.items()))): None,
        }
    )

    payload = StockUpsert(book_id=1, branch_id=2, quantity=7)
    out = await upsert_stock(payload=payload, session=session)

    assert isinstance(out, BookStock)
    assert out.book_id == 1
    assert out.branch_id == 2
    assert out.quantity == 7
    assert session.committed is True
    assert len(session.added) == 1
