# Testing Skill

> pytest (Backend) + Vitest (Frontend)

---

## Backend Setup

```bash
pip install pytest pytest-asyncio pytest-cov httpx
```

---

## Test Fixtures

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import Base, get_db
from app.auth.jwt import create_access_token, hash_password
from app.models.user import User

TEST_DB_URL = "postgresql://test:test@localhost/test_db"
engine = create_engine(TEST_DB_URL)
TestSession = sessionmaker(bind=engine)

@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture
def test_user(db):
    user = User(email="test@example.com", hashed_password=hash_password("password123"), full_name="Test")
    db.add(user)
    db.commit()
    return user

@pytest.fixture
def auth_headers(test_user):
    token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {token}"}
```

---

## API Tests

```python
# tests/test_auth.py
def test_register(client):
    response = client.post("/api/v1/auth/register", json={"email": "new@test.com", "password": "password123"})
    assert response.status_code == 201
    assert response.json()["email"] == "new@test.com"

def test_login(client, test_user):
    response = client.post("/api/v1/auth/login", data={"username": test_user.email, "password": "password123"})
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_me_unauthorized(client):
    assert client.get("/api/v1/auth/me").status_code == 401

def test_me_authorized(client, auth_headers):
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
```

---

## Service Tests

```python
# tests/test_user_service.py
import pytest
from app.services import user_service
from app.exceptions import NotFoundError

def test_get_user(db, test_user):
    user = user_service.get_user(db, test_user.id)
    assert user.email == test_user.email

def test_get_user_not_found(db):
    with pytest.raises(NotFoundError):
        user_service.get_user(db, 99999)
```

---

## Frontend Setup

```bash
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event msw
```

---

## Component Tests

```typescript
// src/__tests__/LoginForm.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginForm } from '../components/forms/LoginForm';

test('renders login form', () => {
  render(<LoginForm />);
  expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
});

test('submits form', async () => {
  const user = userEvent.setup();
  render(<LoginForm />);
  await user.type(screen.getByLabelText(/email/i), 'test@example.com');
  await user.type(screen.getByLabelText(/password/i), 'password123');
  await user.click(screen.getByRole('button', { name: /sign in/i }));
});
```

---

## Hook Tests

```typescript
// src/__tests__/usePosts.test.tsx
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { usePosts } from '../hooks/usePosts';

const wrapper = ({ children }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

test('fetches posts', async () => {
  const { result } = renderHook(() => usePosts(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
});
```

---

## Run Tests

```bash
# Backend
pytest                    # Run all
pytest -v                 # Verbose
pytest --cov=app         # With coverage
pytest --cov-fail-under=80  # Require 80%

# Frontend
npm test                  # Run tests
npm run test:coverage    # With coverage
```

---

## Best Practices

- Use fixtures for test data
- Test success AND error cases
- Mock external dependencies
- Target 80%+ coverage
- Clean up between tests
