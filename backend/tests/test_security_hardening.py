"""Abuse cases in addition to the ordinary authentication/RBAC/workflow suite."""
import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from test_security_workflows import fresh_database, login
from app.core.config import Settings, get_settings
from app.core.spreadsheets import safe_csv_cell
from app.main import app


def test_jwt_requires_expiry_and_access_type():
    with TestClient(app) as client:
        headers = login(client)
        payload = jwt.decode(headers['Authorization'].split()[1], get_settings().secret_key, algorithms=['HS256'])
        for key in ('exp', 'sub', 'org', 'type', 'ver'):
            invalid = {k: v for k, v in payload.items() if k != key}
            token = jwt.encode(invalid, get_settings().secret_key, algorithm='HS256')
            assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'}).status_code == 401
        payload['type'] = 'refresh'
        token = jwt.encode(payload, get_settings().secret_key, algorithm='HS256')
        assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'}).status_code == 401


def test_origin_guard_and_no_store():
    with TestClient(app) as client:
        headers = login(client)
        response = client.get('/api/v1/auth/me', headers=headers)
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert client.post('/api/v1/auth/refresh', headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/api/v1/auth/refresh', headers={'Origin': 'http://localhost:5173'}).status_code == 200
        assert 'admin_seeded' not in client.get('/api/health').json()


def test_public_throttle_cannot_be_bypassed_with_forwarding_headers():
    with TestClient(app) as client:
        for i in range(5):
            response = client.post('/api/v1/auth/forgot-password', json={'organization': 'north', 'email': 'unknown@example.com'},
                                   headers={'X-Forwarded-For': f'192.0.2.{i}'})
            assert response.status_code == 202
        assert client.post('/api/v1/auth/forgot-password', json={'organization': 'north', 'email': 'unknown@example.com'},
                           headers={'X-Forwarded-For': '198.51.100.1'}).status_code == 429


def test_reset_verification_is_throttled():
    with TestClient(app) as client:
        body = {'organization': 'north', 'email': 'owner@example.com', 'reset_code': 'x' * 32,
                'new_password': 'Never-used-password-123!', 'confirm_password': 'Never-used-password-123!'}
        for _ in range(10):
            assert client.post('/api/v1/auth/reset-password', json=body).status_code == 400
        assert client.post('/api/v1/auth/reset-password', json=body).status_code == 429


def test_validation_does_not_echo_secrets():
    with TestClient(app) as client:
        password = 'Secret-value-' * 20
        response = client.post('/api/v1/auth/login', json={'organization': 'north', 'email': 'owner@example.com', 'password': password})
        assert response.status_code == 422
        assert password not in response.text
        assert 'input' not in response.json()['detail'][0]


@pytest.mark.parametrize('value', ['=1+1', '+cmd', '-cmd', '@SUM(A1)', '  =cmd', '\t=cmd', '\rtest', '\ntext'])
def test_csv_formula_neutralization(value):
    assert safe_csv_cell(value) == "'" + value


def test_csv_keeps_typed_numbers():
    assert safe_csv_cell(-12) == -12
    assert safe_csv_cell('Normal text') == 'Normal text'


@pytest.mark.parametrize('origin', ['*', 'https://*.example.com', 'https://example.com/path', 'null', 'https://user@example.com'])
def test_cors_rejects_non_origins(origin):
    with pytest.raises(ValidationError):
        Settings(cors_origins=origin)


def test_production_fails_closed():
    with pytest.raises(ValidationError):
        Settings(environment='production', database_url='sqlite://', secret_key='', secure_cookies=True, cors_origins='https://app.example.com')
    with pytest.raises(ValidationError):
        Settings(environment='production', secret_key='a' * 48, secure_cookies=False, cors_origins='https://app.example.com')
    assert Settings(environment='production', secret_key='a' * 48, secure_cookies=True, cors_origins='https://app.example.com')


def test_database_integrity_errors_are_generic_conflicts():
    import asyncio
    from sqlalchemy.exc import IntegrityError
    from app.main import integrity_error
    error = IntegrityError('INSERT secret SQL', {'password': 'do-not-echo'}, Exception('sensitive driver detail'))
    response = asyncio.run(integrity_error(None, error))
    assert response.status_code == 409
    assert b'do-not-echo' not in response.body
    assert b'sensitive' not in response.body


def test_login_budget_rejects_excess_attempts():
    from fastapi import Request, HTTPException
    from app.core.database import SessionLocal
    from app.core.request_security import throttle
    request = Request({'type': 'http', 'client': ('192.0.2.10', 1234), 'headers': []})
    with SessionLocal() as db:
        for _ in range(30):
            throttle(db, request, 'login', 30)
        with pytest.raises(HTTPException) as failure:
            throttle(db, request, 'login', 30)
        assert failure.value.status_code == 429
        assert failure.value.headers['Retry-After'] == '900'
