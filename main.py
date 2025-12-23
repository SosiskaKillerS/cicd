from __future__ import annotations

from decimal import Decimal
from typing import AsyncGenerator, Optional, List

from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    UniqueConstraint,
    Numeric,
    select,
    func,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship


# ---------------------------
# DB
# ---------------------------

DATABASE_URL = "postgresql+asyncpg://library_user:library_pass@db:5432/library"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

# new change for testing purposes
Base = declarative_base()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------
# Models
# ---------------------------

class Branch(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)

    stocks = relationship("BookStock", back_populates="branch", cascade="all, delete-orphan")


class Faculty(Base):
    __tablename__ = "faculties"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)

    used_books = relationship("BookFaculty", back_populates="faculty", cascade="all, delete-orphan")


class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    authors = Column(String, nullable=False)          # автор(ы)
    publisher = Column(String, nullable=False)        # издательство
    year = Column(Integer, nullable=True)
    pages = Column(Integer, nullable=True)            # количество страниц
    illustrations = Column(Integer, nullable=False, default=0)  # количество иллюстраций
    price = Column(Numeric(10, 2), nullable=True)     # стоимость

    stocks = relationship("BookStock", back_populates="book", cascade="all, delete-orphan")
    used_by = relationship("BookFaculty", back_populates="book", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("title", "authors", "publisher", "year", name="uq_book_identity"),
    )


class BookStock(Base):
    __tablename__ = "book_stock"

    book_id = Column(Integer, ForeignKey("books.id", ondelete="RESTRICT"), primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), primary_key=True)
    quantity = Column(Integer, nullable=False, default=0)

    book = relationship("Book", back_populates="stocks")
    branch = relationship("Branch", back_populates="stocks")

    __table_args__ = (
        UniqueConstraint("book_id", "branch_id", name="uq_book_branch"),
    )


class BookFaculty(Base):
    __tablename__ = "book_faculty"

    book_id = Column(Integer, ForeignKey("books.id", ondelete="RESTRICT"), primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculties.id", ondelete="RESTRICT"), primary_key=True)

    book = relationship("Book", back_populates="used_by")
    faculty = relationship("Faculty", back_populates="used_books")

    __table_args__ = (
        UniqueConstraint("book_id", "faculty_id", name="uq_book_faculty"),
    )


# ---------------------------
# Schemas (Pydantic)
# ---------------------------

class BookBase(BaseModel):
    title: str
    authors: str
    publisher: str
    year: Optional[int] = None
    pages: Optional[int] = Field(default=None, ge=1)
    illustrations: int = Field(default=0, ge=0)
    price: Optional[Decimal] = Field(default=None, ge=Decimal("0.00"))


class BookCreate(BookBase):
    pass


class BookUpdate(BaseModel):
    title: Optional[str] = None
    authors: Optional[str] = None
    publisher: Optional[str] = None
    year: Optional[int] = None
    pages: Optional[int] = Field(default=None, ge=1)
    illustrations: Optional[int] = Field(default=None, ge=0)
    price: Optional[Decimal] = Field(default=None, ge=Decimal("0.00"))


class BookOut(BookBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class BranchCreate(BaseModel):
    name: str
    address: str


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    address: str


class FacultyCreate(BaseModel):
    name: str


class FacultyUpdate(BaseModel):
    name: Optional[str] = None


class FacultyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class StockUpsert(BaseModel):
    book_id: int
    branch_id: int
    quantity: int = Field(ge=0)


class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    book_id: int
    branch_id: int
    quantity: int


class BookFacultyLink(BaseModel):
    book_id: int
    faculty_id: int


# ---------------------------
# App
# ---------------------------

app = FastAPI(title="LibraryInfo API")


@app.post("/startup")
async def on_startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return {"message":"success"}


@app.get("/")
async def root():
    return {"message": "ok"}


# ---------------------------
# Helpers
# ---------------------------

def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# ---------------------------
# CRUD: Books
# ---------------------------

@app.get("/books", response_model=list[BookOut])
async def list_books(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Book).order_by(Book.id))
    return res.scalars().all()


@app.get("/books/{book_id}", response_model=BookOut)
async def get_book(book_id: int, session: AsyncSession = Depends(get_session)):
    book = await session.get(Book, book_id)
    if not book:
        raise not_found("Книга не найдена")
    return book


@app.post("/books", response_model=BookOut, status_code=201)
async def create_book(payload: BookCreate, session: AsyncSession = Depends(get_session)):
    book = Book(**payload.model_dump())
    session.add(book)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise conflict("Дублирующая запись книги, проверь название, авторов, издательство и год")
    await session.refresh(book)
    return book


@app.put("/books/{book_id}", response_model=BookOut)
async def update_book(book_id: int, payload: BookUpdate, session: AsyncSession = Depends(get_session)):
    book = await session.get(Book, book_id)
    if not book:
        raise not_found("Книга не найдена")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(book, k, v)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise conflict("Не удалось обновить книгу: нарушена уникальность или ограничения")
    await session.refresh(book)
    return book


@app.delete("/books/{book_id}")
async def delete_book(book_id: int, session: AsyncSession = Depends(get_session)):
    qty = await session.scalar(
        select(func.coalesce(func.sum(BookStock.quantity), 0)).where(BookStock.book_id == book_id)
    )
    if qty and qty > 0:
        raise conflict("Нельзя удалить книгу: она числится в филиалах. Сначала обнули количество в филиалах")

    book = await session.get(Book, book_id)
    if not book:
        raise not_found("Книга не найдена")

    await session.delete(book)
    await session.commit()
    return {"message": "deleted"}


# ---------------------------
# CRUD: Branches
# ---------------------------

@app.get("/branches", response_model=list[BranchOut])
async def list_branches(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Branch).order_by(Branch.id))
    return res.scalars().all()


@app.post("/branches", response_model=BranchOut, status_code=201)
async def create_branch(payload: BranchCreate, session: AsyncSession = Depends(get_session)):
    obj = Branch(**payload.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@app.put("/branches/{branch_id}", response_model=BranchOut)
async def update_branch(branch_id: int, payload: BranchUpdate, session: AsyncSession = Depends(get_session)):
    obj = await session.get(Branch, branch_id)
    if not obj:
        raise not_found("Филиал не найден")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)

    await session.commit()
    await session.refresh(obj)
    return obj


@app.delete("/branches/{branch_id}")
async def delete_branch(branch_id: int, session: AsyncSession = Depends(get_session)):
    qty = await session.scalar(
        select(func.count()).select_from(BookStock).where(BookStock.branch_id == branch_id, BookStock.quantity > 0)
    )
    if qty and qty > 0:
        raise conflict("Нельзя удалить филиал: в нем числятся книги. Сначала обнули количество")

    obj = await session.get(Branch, branch_id)
    if not obj:
        raise not_found("Филиал не найден")

    await session.delete(obj)
    await session.commit()
    return {"message": "deleted"}


# ---------------------------
# CRUD: Faculties
# ---------------------------

@app.get("/faculties", response_model=list[FacultyOut])
async def list_faculties(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Faculty).order_by(Faculty.id))
    return res.scalars().all()


@app.post("/faculties", response_model=FacultyOut, status_code=201)
async def create_faculty(payload: FacultyCreate, session: AsyncSession = Depends(get_session)):
    obj = Faculty(**payload.model_dump())
    session.add(obj)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise conflict("Факультет с таким названием уже существует")
    await session.refresh(obj)
    return obj


@app.put("/faculties/{faculty_id}", response_model=FacultyOut)
async def update_faculty(faculty_id: int, payload: FacultyUpdate, session: AsyncSession = Depends(get_session)):
    obj = await session.get(Faculty, faculty_id)
    if not obj:
        raise not_found("Факультет не найден")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise conflict("Факультет с таким названием уже существует")
    await session.refresh(obj)
    return obj


@app.delete("/faculties/{faculty_id}")
async def delete_faculty(faculty_id: int, session: AsyncSession = Depends(get_session)):
    links = await session.scalar(
        select(func.count()).select_from(BookFaculty).where(BookFaculty.faculty_id == faculty_id)
    )
    if links and links > 0:
        raise conflict("Нельзя удалить факультет: есть связи с книгами. Сначала отвяжи книги от факультета")

    obj = await session.get(Faculty, faculty_id)
    if not obj:
        raise not_found("Факультет не найден")

    await session.delete(obj)
    await session.commit()
    return {"message": "deleted"}


# ---------------------------
# Admin: links and stock
# ---------------------------

@app.put("/admin/stock", response_model=StockOut)
async def upsert_stock(payload: StockUpsert, session: AsyncSession = Depends(get_session)):
    book = await session.get(Book, payload.book_id)
    if not book:
        raise not_found("Книга не найдена")

    branch = await session.get(Branch, payload.branch_id)
    if not branch:
        raise not_found("Филиал не найден")

    obj = await session.get(BookStock, {"book_id": payload.book_id, "branch_id": payload.branch_id})
    if obj is None:
        obj = BookStock(book_id=payload.book_id, branch_id=payload.branch_id, quantity=payload.quantity)
        session.add(obj)
    else:
        obj.quantity = payload.quantity

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise conflict("Не удалось сохранить количество: проверь ограничения")

    await session.refresh(obj)
    return obj


@app.post("/admin/book-faculty", status_code=201)
async def add_book_faculty(payload: BookFacultyLink, session: AsyncSession = Depends(get_session)):
    book = await session.get(Book, payload.book_id)
    if not book:
        raise not_found("Книга не найдена")

    faculty = await session.get(Faculty, payload.faculty_id)
    if not faculty:
        raise not_found("Факультет не найден")

    session.add(BookFaculty(book_id=payload.book_id, faculty_id=payload.faculty_id))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise conflict("Такая связь книга–факультет уже существует")

    return {"message": "ok"}


@app.delete("/admin/book-faculty")
async def remove_book_faculty(book_id: int, faculty_id: int, session: AsyncSession = Depends(get_session)):
    obj = await session.get(BookFaculty, {"book_id": book_id, "faculty_id": faculty_id})
    if not obj:
        raise not_found("Связь книга–факультет не найдена")

    await session.delete(obj)
    await session.commit()
    return {"message": "deleted"}


# ---------------------------
# Analytics (2 функции по ТЗ)
# ---------------------------

@app.get("/analytics/branches/{branch_id}/books/{book_id}/quantity")
async def analytics_quantity(branch_id: int, book_id: int, session: AsyncSession = Depends(get_session)):
    qty = await session.scalar(
        select(BookStock.quantity).where(BookStock.branch_id == branch_id, BookStock.book_id == book_id)
    )
    return {"branch_id": branch_id, "book_id": book_id, "quantity": int(qty or 0)}


@app.get("/analytics/branches/{branch_id}/books/{book_id}/faculties")
async def analytics_faculties(branch_id: int, book_id: int, session: AsyncSession = Depends(get_session)):
    qty = await session.scalar(
        select(BookStock.quantity).where(BookStock.branch_id == branch_id, BookStock.book_id == book_id)
    )
    if not qty or qty <= 0:
        return {"book_id": book_id, "branch_id": branch_id, "count": 0, "faculties": []}

    res = await session.execute(
        select(Faculty.name)
        .join(BookFaculty, BookFaculty.faculty_id == Faculty.id)
        .where(BookFaculty.book_id == book_id)
        .order_by(Faculty.name)
    )
    names = res.scalars().all()
    return {"book_id": book_id, "branch_id": branch_id, "count": len(names), "faculties": names}
