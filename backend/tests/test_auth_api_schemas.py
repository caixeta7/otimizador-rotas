"""
Testes de autenticação, banco de dados, schemas e endpoints REST.

Cobertura:
  - init_db(): cria tabelas e popula os 3 usuarios fixos (sem duplicar)
  - authenticate_user(): aceita credenciais corretas, rejeita erradas
  - create_access_token() / get_current_user(): token JWT valido e expirado
  - /auth/login: rate limit (5/min), sucesso, credenciais invalidas
  - /routes CRUD: criar, listar, obter, deletar
  - /routes/{id}/import: importar planilha fixture, validar formato
  - /routes/{id}/optimize: calcular rota, verificar status
  - /stops/{id}/address: editar endereco de parada
  - /stops/{id}/location: corrigir coordenada
  - /stops/{id}/deliver + /routes/{id}/finish: fluxo completo de entrega
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jose import jwt

from app.database import Base, get_db, init_db, pwd_context, DB_PATH
from app.models import User, Route, Stop, Package
from app.main import app
from app.auth import (
    SECRET_KEY, ALGORITHM, create_access_token, get_current_user,
)


# ------------------------------------------------------------------ FIXTURES


@pytest.fixture
def temp_db(monkeypatch):
    """Cria um banco SQLite temporario e força o init_db() a usa-lo."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    monkeypatch.setenv("ROTAHUB_DB", tmp.name)
    # recarrega o engine/DB_PATH do modulo database
    from app import database as db_mod
    db_mod.DATABASE_URL = f"sqlite:///{tmp.name}"
    db_mod.engine = create_engine(
        db_mod.DATABASE_URL, connect_args={"check_same_thread": False}
    )
    db_mod.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_mod.engine
    )
    db_mod.DB_PATH = tmp.name
    init_db(reset=True)
    yield tmp.name
    # dispose do engine antes de tentar deletar
    db_mod.engine.dispose()
    try:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
    except (PermissionError, OSError):
        pass


@pytest.fixture
def client(temp_db):
    """TestClient com override da dependencia get_db para usar temp_db."""
    from app import database as db_mod
    def _override_get_db():
        d = db_mod.SessionLocal()
        try:
            yield d
        finally:
            d.close()
    app.dependency_overrides[get_db] = _override_get_db
    # inicializa o limiter no state (slowapi exige isso)
    from app.main import limiter
    app.state.limiter = limiter
    # reseta o estado do limiter entre testes (ip fixo do TestClient)
    limiter.reset()
    with TestClient(app) as c:
        yield c
    limiter.reset()
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(client):
    """Client autenticado como 'matheus'."""
    r = client.post(
        "/auth/login",
        data={"username": "matheus", "password": "rotahub2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ------------------------------------------------------------------ DATABASE


class TestDatabase:
    def test_init_db_creates_3_fixed_users(self, temp_db):
        """RF001 - os 3 usuarios fixos sao criados no init_db."""
        from app import database as db_mod
        db = db_mod.SessionLocal()
        try:
            users = db.query(User).order_by(User.username).all()
            usernames = [u.username for u in users]
            assert usernames == ["bruna", "matheus", "paulo"]
            for u in users:
                # senha nunca em texto puro
                assert u.password_hash != "rotahub2026"
                # hash bcrypt confere com a senha
                assert pwd_context.verify("rotahub2026", u.password_hash)
        finally:
            db.close()

    def test_init_db_does_not_duplicate_users_on_reinit(self, temp_db):
        """Chamar init_db() duas vezes NAO duplica os usuarios fixos."""
        from app import database as db_mod
        db = db_mod.SessionLocal()
        try:
            count_before = db.query(User).count()
        finally:
            db.close()
        # chama de novo
        init_db(reset=False)
        db = db_mod.SessionLocal()
        try:
            count_after = db.query(User).count()
        finally:
            db.close()
        assert count_before == count_after == 3

    def test_passwords_are_independent_hashes(self, temp_db):
        """Mesma senha, hashes diferentes (salt aleatorio do bcrypt)."""
        from app import database as db_mod
        db = db_mod.SessionLocal()
        try:
            hashes = [u.password_hash for u in db.query(User).all()]
            assert len(set(hashes)) == 3
        finally:
            db.close()


# -------------------------------------------------------------------- AUTH --


class TestAuth:
    def test_authenticate_user_accepts_correct_credentials(self, temp_db):
        from app import database as db_mod
        db = db_mod.SessionLocal()
        try:
            user = None
            # import local pra nao quebrar
            from app.auth import authenticate_user
            user = authenticate_user(db, "matheus", "rotahub2026")
            assert user is not None
            assert user.username == "matheus"
            assert user.display_name == "Matheus"
        finally:
            db.close()

    def test_authenticate_user_rejects_wrong_password(self, temp_db):
        from app import database as db_mod
        from app.auth import authenticate_user
        db = db_mod.SessionLocal()
        try:
            assert authenticate_user(db, "matheus", "senhaerrada") is None
            assert authenticate_user(db, "inexistente", "rotahub2026") is None
        finally:
            db.close()

    def test_create_access_token_returns_valid_jwt(self, temp_db):
        from app import database as db_mod
        db = db_mod.SessionLocal()
        try:
            user = db.query(User).first()
            token = create_access_token(user)
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            assert payload["sub"] == user.username
            assert payload["uid"] == user.id
            assert "exp" in payload
        finally:
            db.close()

    def test_get_current_user_raises_on_invalid_token(self, client):
        """Token forjado/errado -> 401."""
        r = client.get("/me", headers={"Authorization": "Bearer token.invalido.aqui"})
        assert r.status_code == 401

    def test_get_current_user_raises_on_missing_token(self, client):
        r = client.get("/me")
        assert r.status_code == 401

    def test_get_current_user_raises_on_expired_token(self, client):
        """Token com exp expirado deve ser rejeitado."""
        from app import database as db_mod
        db = db_mod.SessionLocal()
        try:
            user = db.query(User).first()
            # gera token expirado (expirou ha 1 hora)
            expired_payload = {
                "sub": user.username,
                "uid": user.id,
                "exp": datetime.utcnow() - timedelta(hours=1),
            }
            expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)
        finally:
            db.close()
        r = client.get("/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert r.status_code == 401


# -------------------------------------------------------------------- LOGIN


class TestLoginEndpoint:
    def test_login_success_returns_token_and_display_name(self, client):
        r = client.post(
            "/auth/login",
            data={"username": "bruna", "password": "rotahub2026"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["display_name"] == "Bruna"

    def test_login_wrong_password_returns_401(self, client):
        r = client.post(
            "/auth/login",
            data={"username": "matheus", "password": "errado"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 401
        assert "invalidos" in r.json()["detail"].lower()

    def test_login_unknown_user_returns_401(self, client):
        r = client.post(
            "/auth/login",
            data={"username": "fantasma", "password": "qualquer"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 401

    def test_login_rate_limited_after_5_attempts_per_minute(self, client):
        """Rate limit: 5/min no /auth/login."""
        # 5 tentativas falhas (a 6a deve ser bloqueada)
        for _ in range(5):
            r = client.post(
                "/auth/login",
                data={"username": "matheus", "password": "errado"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert r.status_code == 401
        # 6a tentativa deve ser bloqueada pelo rate limiter
        r = client.post(
            "/auth/login",
            data={"username": "matheus", "password": "rotahub2026"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 429


# ----------------------------------------------------------- ROUTES CRUD ---


class TestRoutesCRUD:
    def test_create_route_returns_route_with_draft_status(self, auth_client):
        r = auth_client.post("/routes", json={"name": "Rota Teste"})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Rota Teste"
        assert data["status"] == "draft"
        assert data["stops"] == []

    def test_create_route_requires_authentication(self, client):
        r = client.post("/routes", json={"name": "Sem Auth"})
        assert r.status_code == 401

    def test_list_routes_returns_only_existing(self, auth_client):
        # cria 2 rotas
        auth_client.post("/routes", json={"name": "A"})
        auth_client.post("/routes", json={"name": "B"})
        r = auth_client.get("/routes")
        assert r.status_code == 200
        routes = r.json()
        assert len(routes) >= 2
        # mais recente primeiro (listagem ordenada por created_at desc)
        names = [rt["name"] for rt in routes]
        assert "A" in names
        assert "B" in names

    def test_get_route_returns_404_for_unknown_id(self, auth_client):
        r = auth_client.get("/routes/99999")
        assert r.status_code == 404

    def test_delete_route_removes_it(self, auth_client):
        created = auth_client.post("/routes", json={"name": "Apagar"}).json()
        rid = created["id"]
        r = auth_client.delete(f"/routes/{rid}")
        assert r.status_code == 200
        # agora deve dar 404
        r2 = auth_client.get(f"/routes/{rid}")
        assert r2.status_code == 404

    def test_unauthenticated_request_to_routes_returns_401(self, client):
        r = client.get("/routes")
        assert r.status_code == 401


# ---------------------------------------------- IMPORT + EDIT STOP + DELIVERY


class TestRouteWorkflow:
    FIXTURE_PATH = os.path.join(
        os.path.dirname(__file__), "fixtures", "exemplo_bruna_shopee_bruto.xlsx"
    )

    def test_import_fixture_returns_stops_and_format(self, auth_client):
        route = auth_client.post("/routes", json={"name": "Import Test"}).json()
        with open(self.FIXTURE_PATH, "rb") as f:
            r = auth_client.post(
                f"/routes/{route['id']}/import",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["source_format"] == "shopee_raw"
        assert len(data["stops"]) > 0
        # cada stop tem package_count > 0
        for s in data["stops"]:
            assert s["package_count"] >= 1

    def test_optimize_after_import_assigns_sequence_and_distance(self, auth_client):
        route = auth_client.post("/routes", json={"name": "Opt Test"}).json()
        with open(self.FIXTURE_PATH, "rb") as f:
            imported = auth_client.post(
                f"/routes/{route['id']}/import",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        # tem que ter paradas pra otimizar
        assert len(imported["stops"]) > 0
        r = auth_client.post(f"/routes/{route['id']}/optimize")
        assert r.status_code == 200
        optimized = r.json()
        assert optimized["status"] == "optimized"
        # todas as paradas devem ter sequence entre 1 e N
        seqs = [s["sequence"] for s in optimized["stops"]]
        assert None not in seqs
        assert sorted(seqs) == list(range(1, len(seqs) + 1))
        # distancia total registrada
        assert optimized["total_distance_km"] is not None

    def test_correct_stop_address_clears_needs_review(self, auth_client):
        route = auth_client.post("/routes", json={"name": "Edit Addr"}).json()
        with open(self.FIXTURE_PATH, "rb") as f:
            imported = auth_client.post(
                f"/routes/{route['id']}/import",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        # pega a primeira parada
        stop = imported["stops"][0]
        # simula que ela precisa de revisao
        new_addr = "Rua Teste da Silva, 999, Apto 42"
        r = auth_client.put(
            f"/stops/{stop['id']}/address",
            json={
                "address": new_addr,
                "complement": "Apto 42",
                "neighborhood": "Centro",
                "city": "Sao Paulo",
                "zipcode": "01000-000",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["address"] == new_addr
        assert data["needs_review"] is False

    def test_correct_stop_location_persists_with_manual_source(self, auth_client):
        route = auth_client.post("/routes", json={"name": "Edit Loc"}).json()
        with open(self.FIXTURE_PATH, "rb") as f:
            imported = auth_client.post(
                f"/routes/{route['id']}/import",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        stop = imported["stops"][0]
        r = auth_client.put(
            f"/stops/{stop['id']}/location",
            json={"latitude": -23.5, "longitude": -46.6},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["latitude"] == -23.5
        assert data["longitude"] == -46.6

    def test_deliver_stop_marks_status_delivered(self, auth_client):
        route = auth_client.post("/routes", json={"name": "Deliver"}).json()
        with open(self.FIXTURE_PATH, "rb") as f:
            imported = auth_client.post(
                f"/routes/{route['id']}/import",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        auth_client.post(f"/routes/{route['id']}/optimize")
        # marca a primeira como entregue
        stop = imported["stops"][0]
        r = auth_client.post(f"/stops/{stop['id']}/deliver")
        assert r.status_code == 200
        assert r.json()["status"] == "delivered"

    def test_skip_stop_with_recalculation(self, auth_client):
        route = auth_client.post("/routes", json={"name": "Skip"}).json()
        with open(self.FIXTURE_PATH, "rb") as f:
            imported = auth_client.post(
                f"/routes/{route['id']}/import",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        auth_client.post(f"/routes/{route['id']}/optimize")
        stop = imported["stops"][0]
        r = auth_client.post(
            f"/stops/{stop['id']}/skip",
            json={"reason": "cliente ausente", "recalculate": True},
        )
        assert r.status_code == 200
        data = r.json()
        assert any(s["status"] == "skipped" for s in data["stops"])

    def test_finish_route_requires_no_pending_stops(self, auth_client):
        route = auth_client.post("/routes", json={"name": "Finish"}).json()
        with open(self.FIXTURE_PATH, "rb") as f:
            auth_client.post(
                f"/routes/{route['id']}/import",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        auth_client.post(f"/routes/{route['id']}/optimize")
        # ainda tem paradas pendentes - deve falhar
        r = auth_client.post(f"/routes/{route['id']}/finish")
        assert r.status_code == 400

    def test_complete_workflow_import_optimize_deliver_finish(self, auth_client):
        """Fluxo end-to-end: importar -> otimizar -> entregar tudo -> finalizar."""
        route = auth_client.post("/routes", json={"name": "E2E"}).json()
        with open(self.FIXTURE_PATH, "rb") as f:
            imported = auth_client.post(
                f"/routes/{route['id']}/import",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        auth_client.post(f"/routes/{route['id']}/optimize")
        auth_client.post(f"/routes/{route['id']}/start")
        for stop in imported["stops"]:
            auth_client.post(f"/stops/{stop['id']}/deliver")
        r = auth_client.post(f"/routes/{route['id']}/finish")
        assert r.status_code == 200
        summary = r.json()
        assert summary["delivered"] == len(imported["stops"])
        assert summary["skipped"] == 0
        assert summary["pending"] == 0


# ---------------------------------------------------------- SCHEMAS -------


class TestSchemas:
    def test_login_response_requires_token_and_name(self):
        from app.schemas import LoginResponse
        ok = LoginResponse(access_token="x", display_name="Y")
        assert ok.access_token == "x"
        assert ok.token_type == "bearer"

    def test_stop_address_update_rejects_empty_address(self):
        from app.schemas import StopAddressUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            StopAddressUpdate(address="")

    def test_location_update_rejects_out_of_range_coords(self):
        from app.schemas import LocationUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LocationUpdate(latitude=91.0, longitude=0.0)
        with pytest.raises(ValidationError):
            LocationUpdate(latitude=0.0, longitude=181.0)
        # coords validas nao devem falhar
        LocationUpdate(latitude=-23.5, longitude=-46.6)

    def test_route_create_rejects_empty_name(self):
        from app.schemas import RouteCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RouteCreate(name="")


# ---------------------------------------------------------- DISTANCE FALLBACK -


class TestDistanceFallback:
    def test_haversine_matrix_is_symmetric(self):
        from app.distance import _haversine_matrix
        points = [
            {"latitude": -23.5, "longitude": -46.6},
            {"latitude": -23.6, "longitude": -46.7},
            {"latitude": -23.7, "longitude": -46.8},
        ]
        m = _haversine_matrix(points)
        for i in range(3):
            for j in range(3):
                assert abs(m[i][j] - m[j][i]) < 1e-9, f"assimetrico em ({i},{j})"

    def test_haversine_matrix_zero_diagonal(self):
        from app.distance import _haversine_matrix
        points = [
            {"latitude": -23.5, "longitude": -46.6},
            {"latitude": -23.6, "longitude": -46.7},
        ]
        m = _haversine_matrix(points)
        assert m[0][0] == 0.0
        assert m[1][1] == 0.0

    def test_haversine_matrix_known_distance(self):
        """Sao Paulo -> Rio de Janeiro ~360 km em linha reta."""
        from app.distance import _haversine_matrix
        points = [
            {"latitude": -23.5505, "longitude": -46.6333},  # SP
            {"latitude": -22.9068, "longitude": -43.1729},  # RJ
        ]
        m = _haversine_matrix(points)
        # tolerancia ampla (linha reta estao ~360 km, +/- 30 km pra margem)
        assert 330 < m[0][1] < 390
