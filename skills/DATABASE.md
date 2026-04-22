# Database Skill

> PostgreSQL + SQLAlchemy + Alembic

---

## Database Connection

```python
# database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## Base Mixins

```python
# models/base.py
from sqlalchemy import Column, DateTime, Boolean
from sqlalchemy.sql import func

class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class SoftDeleteMixin:
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
```

---

## User Model

```python
# models/user.py
from sqlalchemy import Column, Integer, String, Boolean, Enum
from sqlalchemy.orm import relationship
import enum
from app.database import Base
from app.models.base import TimestampMixin

class UserRole(enum.Enum):
    admin = "admin"
    user = "user"

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)
    full_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    role = Column(Enum(UserRole), default=UserRole.user)
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    avatar_url = Column(String(500), nullable=True)

    # Relationships
    posts = relationship("Post", back_populates="author", cascade="all, delete-orphan")
```

---

## One-to-Many Example

```python
# models/post.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.base import TimestampMixin

class Post(Base, TimestampMixin):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    slug = Column(String(250), unique=True, index=True)
    content = Column(Text, nullable=False)
    is_published = Column(Boolean, default=False)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    author = relationship("User", back_populates="posts")

    __table_args__ = (Index('ix_posts_author_published', 'author_id', 'is_published'),)
```

---

## Many-to-Many Example

```python
# models/tag.py
from sqlalchemy import Column, Integer, String, Table, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

post_tags = Table(
    'post_tags', Base.metadata,
    Column('post_id', Integer, ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)
)

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    posts = relationship("Post", secondary=post_tags, back_populates="tags")
```

---

## Alembic Commands

```bash
# Initialize
alembic init alembic

# Create migration
alembic revision --autogenerate -m "Create users table"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

---

## Query Patterns

```python
# Avoid N+1 with eager loading
from sqlalchemy.orm import joinedload, selectinload

def get_post_with_author(db, post_id: int):
    return db.query(Post).options(joinedload(Post.author)).filter(Post.id == post_id).first()

# Pagination
def get_posts_paginated(db, page: int = 1, per_page: int = 10):
    offset = (page - 1) * per_page
    return db.query(Post).offset(offset).limit(per_page).all()
```

---

## Best Practices

- Use meaningful table/column names
- Add indexes on frequently queried columns
- Use `ondelete="CASCADE"` for foreign keys
- Create migrations for all schema changes
- Use mixins for common fields (timestamps)
- Avoid N+1 with eager loading
