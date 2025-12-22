from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import IntegrityError


# new change for testing purposes
Base = declarative_base()

DATABASE_URL = "postgresql+asyncpg://library_user:library_pass@db:5432/library"
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(
    bind = engine,
    expire_on_commit=True,
    class_ = AsyncSession
)

async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

class Branch(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)

    copies = relationship("BookCopy", back_populates="branch")

class Faculty(Base):
    __tablename__ = "faculties"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)

    loans = relationship("Loan", back_populates="faculty")


class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    isbn = Column(String, unique=True, index=True)
    year = Column(Integer, nullable=True)

    copies = relationship("BookCopy", back_populates="book")


class BookCopy(Base):
    __tablename__ = "book_copies"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    inventory_number = Column(String, unique=True, index=True)

    book = relationship("Book", back_populates="copies")
    branch = relationship("Branch", back_populates="copies")
    loans = relationship("Loan", back_populates="copy")


class Loan(Base):
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True, index=True)
    copy_id = Column(Integer, ForeignKey("book_copies.id"), nullable=False)
    faculty_id = Column(Integer, ForeignKey("faculties.id"), nullable=False)

    borrowed_at = Column(DateTime(timezone=True), server_default=func.now())
    returned_at = Column(DateTime(timezone=True), nullable=True)

    copy = relationship("BookCopy", back_populates="loans")
    faculty = relationship("Faculty", back_populates="loans")


DATABASE_URL = "postgresql+asyncpg://library_user:library_pass@db:5432/library"
engine = create_async_engine(DATABASE_URL, echo=True)
app = FastAPI(title="LibraryInfo API")
@app.get("/")
async def root():
    return {"message": "ok"}

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get('/books')
async def list_books(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Book))
    books = result.scalars().all()
    return books

@app.post('/books')
async def create_book(session: AsyncSession = Depends(get_session)):
    book = Book(title='Test', author='User', isbn='123', year=2025)
    session.add(book)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Книга с таким ISBN уже существует",
        )

    await session.refresh(book)
    return {"message": "success", "id": book.id}




