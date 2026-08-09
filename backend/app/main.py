import os
import shutil
import tempfile
import datetime
import hashlib
from typing import List

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .database import get_db, init_db
from .models import User, Route, Stop, Package
from . import schemas, auth as auth_mod
from .parser import parse_workbook, ParseError
from .geo import geocode_nominatim
from .distance import build_distance_matrix
from .optimizer import solve_tsp, route_total_distance, route_total_duration

MAX_UPLOAD_MB = 8
ALLOWED_EXTENSIONS = {".xlsx"}

limiter = Limiter(key_func=get_remote_address, default_limits=["200 per day"])

app = FastAPI(title="RotaHub API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS restrito - o frontend roda em localhost / arquivo estatico servido
# pelo proprio backend. Ajustar allow_origins ao publicar (RF de seguranca).
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ROTAHUB_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()


# ---------------------------------------------------------------- AUTH ----

@app.post("/auth/login", response_model=schemas.LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = auth_mod.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Usuario ou senha invalidos")
    token = auth_mod.create_access_token(user)
    return schemas.LoginResponse(access_token=token, display_name=user.display_name)


@app.get("/me")
def me(current: User = Depends(auth_mod.get_current_user)):
    return {"id": current.id, "username": current.username, "display_name": current.display_name}


# --------------------------------------------------------------- ROUTES ---

def _stop_to_out(stop: Stop) -> schemas.StopOut:
    return schemas.StopOut(
        id=stop.id,
        address=stop.address,
        complement=stop.complement,
        custom_label=stop.custom_label,
        neighborhood=stop.neighborhood,
        city=stop.city,
        zipcode=stop.zipcode,
        latitude=stop.latitude,
        longitude=stop.longitude,
        sequence=stop.sequence,
        status=stop.status,
        needs_review=stop.needs_review,
        package_count=len(stop.packages),
    )


def _route_to_out(route: Route) -> schemas.RouteOut:
    stops_sorted = sorted(route.stops, key=lambda s: (s.sequence is None, s.sequence or 0))
    return schemas.RouteOut(
        id=route.id,
        name=route.name,
        status=route.status,
        source_format=route.source_format,
        distance_source=route.distance_source,
        total_distance_km=route.total_distance_km,
        total_duration_min=route.total_duration_min,
        stops=[_stop_to_out(s) for s in stops_sorted],
    )


def _get_owned_route(db: Session, route_id: int) -> Route:
    # Uso colaborativo entre os 3 usuarios fixos: qualquer um pode ver/operar
    # qualquer rota (equipe pequena, um so passa o celular pro outro).
    route = db.query(Route).filter(Route.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Rota nao encontrada")
    return route


@app.post("/routes", response_model=schemas.RouteOut)
def create_route(body: schemas.RouteCreate, db: Session = Depends(get_db),
                  current: User = Depends(auth_mod.get_current_user)):
    route = Route(owner_id=current.id, name=body.name, status="draft")
    db.add(route)
    db.commit()
    db.refresh(route)
    return _route_to_out(route)


@app.get("/routes", response_model=List[schemas.RouteOut])
def list_routes(db: Session = Depends(get_db), current: User = Depends(auth_mod.get_current_user)):
    routes = db.query(Route).order_by(Route.created_at.desc()).all()
    return [_route_to_out(r) for r in routes]


@app.get("/routes/{route_id}", response_model=schemas.RouteOut)
def get_route(route_id: int, db: Session = Depends(get_db),
               current: User = Depends(auth_mod.get_current_user)):
    return _route_to_out(_get_owned_route(db, route_id))


@app.delete("/routes/{route_id}")
def delete_route(route_id: int, db: Session = Depends(get_db),
                  current: User = Depends(auth_mod.get_current_user)):
    route = _get_owned_route(db, route_id)
    db.delete(route)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------- RF003/004/005 ----

@app.post("/routes/{route_id}/import", response_model=schemas.RouteOut)
def import_spreadsheet(route_id: int, file: UploadFile = File(...),
                        db: Session = Depends(get_db),
                        current: User = Depends(auth_mod.get_current_user)):
    route = _get_owned_route(db, route_id)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Arquivo '{file.filename}' não é aceito. Apenas arquivos .xlsx são permitidos.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        size = 0
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                tmp.close()
                os.unlink(tmp.name)
                raise HTTPException(status_code=400, detail=f"Arquivo maior que {MAX_UPLOAD_MB}MB")
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        try:
            parsed = parse_workbook(tmp_path)
        except ParseError as e:
            raise HTTPException(status_code=422, detail=str(e))
    finally:
        os.unlink(tmp_path)

    route.source_at_id = parsed["at_id"]
    route.source_format = parsed["format"]
    if parsed["origin"]:
        route.origin_lat = parsed["origin"]["latitude"]
        route.origin_lng = parsed["origin"]["longitude"]

    # limpa paradas anteriores em caso de reimportacao
    db.query(Stop).filter(Stop.route_id == route.id).delete()

    for s in parsed["stops"]:
        needs_review = s["needs_review"]
        lat, lng = s["latitude"], s["longitude"]
        geocode_source = "import"
        if lat is None or lng is None:
            # RF005: fallback de geocodificacao (so quando a planilha nao trouxe)
            geo_result = geocode_nominatim(s["address"], s.get("city") or "Sao Paulo")
            if geo_result:
                lat, lng = geo_result
                geocode_source = "nominatim"
            else:
                needs_review = True
                lat, lng = 0.0, 0.0
                geocode_source = "manual"

        stop = Stop(
            route_id=route.id,
            address=s["address"],
            complement=s.get("complement"),
            neighborhood=s.get("neighborhood"),
            city=s.get("city"),
            zipcode=s.get("zipcode"),
            latitude=lat,
            longitude=lng,
            geocode_source=geocode_source,
            needs_review=needs_review,
        )
        db.add(stop)
        db.flush()
        for pkg_ref in s["packages"]:
            db.add(Package(stop_id=stop.id, tracking_number=pkg_ref))

    db.commit()
    db.refresh(route)
    return _route_to_out(route)


@app.put("/stops/{stop_id}/label", response_model=schemas.StopOut)
def set_custom_label(stop_id: int, body: schemas.LabelUpdate, db: Session = Depends(get_db),
                      current: User = Depends(auth_mod.get_current_user)):
    stop = db.query(Stop).filter(Stop.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail="Parada nao encontrada")
    stop.custom_label = body.custom_label
    db.commit()
    db.refresh(stop)
    return _stop_to_out(stop)


@app.put("/stops/{stop_id}/address", response_model=schemas.StopOut)
def correct_stop_address(stop_id: int, body: schemas.StopAddressUpdate, db: Session = Depends(get_db),
                          current: User = Depends(auth_mod.get_current_user)):
    """Correcao manual de endereco (RF005): quando o endereco da planilha
    esta incompleto/errado e a parada ficou marcada como needs_review."""
    stop = db.query(Stop).filter(Stop.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail="Parada nao encontrada")
    stop.address = body.address
    stop.complement = body.complement
    stop.neighborhood = body.neighborhood
    stop.city = body.city
    stop.zipcode = body.zipcode
    stop.needs_review = False
    db.commit()
    db.refresh(stop)
    return _stop_to_out(stop)


@app.put("/stops/{stop_id}/location", response_model=schemas.StopOut)
def correct_stop_location(stop_id: int, body: schemas.LocationUpdate, db: Session = Depends(get_db),
                           current: User = Depends(auth_mod.get_current_user)):
    """
    Correção manual de coordenada (RF005 estendido): a coordenada que veio
    da planilha (Shopee/Circuit) pode estar errada na origem - o RotaHub não
    tem como validar isso sozinho. Quando o entregador percebe que o pino
    está no lugar errado (arrastando no mapa), essa correção fica salva pra
    sempre nessa parada, marcada como "manual" pra não ser sobrescrita numa
    reimportação futura da mesma rota.
    """
    stop = db.query(Stop).filter(Stop.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail="Parada nao encontrada")
    stop.latitude = body.latitude
    stop.longitude = body.longitude
    stop.geocode_source = "manual"
    stop.needs_review = False
    db.commit()
    db.refresh(stop)
    return _stop_to_out(stop)


# --------------------------------------------------------------- RF006 ----

@app.post("/routes/{route_id}/optimize", response_model=schemas.RouteOut)
def optimize_route(route_id: int, db: Session = Depends(get_db),
                    current: User = Depends(auth_mod.get_current_user)):
    route = _get_owned_route(db, route_id)
    stops = [s for s in route.stops if s.status == "pending"]
    if len(stops) < 1:
        raise HTTPException(status_code=400, detail="Nenhuma parada pendente para otimizar")

    if route.origin_lat is not None and route.origin_lng is not None:
        points = [{"latitude": route.origin_lat, "longitude": route.origin_lng}] + \
                 [{"latitude": s.latitude, "longitude": s.longitude} for s in stops]
        start_index = 0
        offset = 1
    else:
        points = [{"latitude": s.latitude, "longitude": s.longitude} for s in stops]
        start_index = 0
        offset = 0

    dist_matrix, dur_matrix, source = build_distance_matrix(points)
    order = solve_tsp(dist_matrix, start_index=start_index, time_limit_seconds=12)

    seq = 1
    for idx in order:
        if idx < offset:
            continue  # pula o ponto de origem, que nao e uma parada
        stop = stops[idx - offset]
        stop.sequence = seq
        seq += 1

    route.total_distance_km = round(route_total_distance(order, dist_matrix), 2)
    route.total_duration_min = round(route_total_duration(order, dur_matrix), 1)
    route.distance_source = source
    route.status = "optimized"
    db.commit()
    db.refresh(route)
    return _route_to_out(route)


# ------------------------------------------------------- RF009-013/RF014 --

@app.post("/routes/{route_id}/start", response_model=schemas.RouteOut)
def start_route(route_id: int, db: Session = Depends(get_db),
                 current: User = Depends(auth_mod.get_current_user)):
    route = _get_owned_route(db, route_id)
    if route.status not in ("optimized", "in_progress"):
        raise HTTPException(status_code=400, detail="Otimize a rota antes de iniciar")
    route.status = "in_progress"
    route.started_at = route.started_at or datetime.datetime.utcnow()
    db.commit()
    db.refresh(route)
    return _route_to_out(route)


@app.post("/stops/{stop_id}/deliver", response_model=schemas.StopOut)
def deliver_stop(stop_id: int, db: Session = Depends(get_db),
                  current: User = Depends(auth_mod.get_current_user)):
    """RF010 + RF015 (auto-save a cada entrega - a propria escrita no banco JA e o autosave)."""
    stop = db.query(Stop).filter(Stop.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail="Parada nao encontrada")
    stop.status = "delivered"
    stop.delivered_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(stop)
    return _stop_to_out(stop)


@app.post("/stops/{stop_id}/skip", response_model=schemas.RouteOut)
def skip_stop(stop_id: int, body: schemas.SkipRequest, db: Session = Depends(get_db),
              current: User = Depends(auth_mod.get_current_user)):
    """RF012 - pular entrega, com opcao de recalcular a rota restante."""
    stop = db.query(Stop).filter(Stop.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail="Parada nao encontrada")
    stop.status = "skipped"
    stop.skip_reason = body.reason
    db.commit()

    route = stop.route
    if body.recalculate:
        remaining = [s for s in route.stops if s.status == "pending"]
        if remaining:
            points = [{"latitude": s.latitude, "longitude": s.longitude} for s in remaining]
            dist_matrix, dur_matrix, source = build_distance_matrix(points)
            order = solve_tsp(dist_matrix, start_index=0, time_limit_seconds=8)
            done_seqs = [s.sequence for s in route.stops if s.status != "pending" and s.sequence]
            seq = (max(done_seqs) + 1) if done_seqs else 1
            for idx in order:
                remaining[idx].sequence = seq
                seq += 1
            route.distance_source = source
            db.commit()

    db.refresh(route)
    return _route_to_out(route)


@app.get("/routes/{route_id}/state", response_model=schemas.RouteOut)
def get_route_state(route_id: int, db: Session = Depends(get_db),
                     current: User = Depends(auth_mod.get_current_user)):
    """RF014 - retomar rota apos fechar o navegador. O estado sempre reflete
    o banco (RF015 autosave), entao 'retomar' e simplesmente reabrir isto."""
    return _route_to_out(_get_owned_route(db, route_id))


@app.post("/routes/{route_id}/finish", response_model=schemas.FinishSummary)
def finish_route(route_id: int, db: Session = Depends(get_db),
                  current: User = Depends(auth_mod.get_current_user)):
    route = _get_owned_route(db, route_id)
    pending = [s for s in route.stops if s.status == "pending"]
    if pending:
        raise HTTPException(status_code=400, detail=f"Ainda ha {len(pending)} parada(s) pendente(s)")

    route.status = "finished"
    route.finished_at = datetime.datetime.utcnow()
    db.commit()

    delivered = sum(1 for s in route.stops if s.status == "delivered")
    skipped = sum(1 for s in route.stops if s.status == "skipped")
    elapsed = None
    if route.started_at:
        elapsed = (route.finished_at - route.started_at).total_seconds() / 60.0

    return schemas.FinishSummary(
        delivered=delivered, skipped=skipped, pending=0,
        total_distance_km=route.total_distance_km,
        elapsed_minutes=round(elapsed, 1) if elapsed else None,
    )


# -------------------------------------------------------- VERIFICAR ENDERECOS --

import time
import math
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
NOMINATIM_TIMEOUT = 10
NOMINATIM_RATE_LIMIT_DELAY = 1.2
BRASILAPI_CEP_URL = "https://brasilapi.com.br/api/cep/v2"
BRASILAPI_TIMEOUT = 6

VERIFY_THRESHOLD_METERS = 300


def _haversine_m(lat1, lon1, lat2, lon2):
    """Distancia em metros entre dois pontos (linha reta)."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _nominatim_reverse(lat, lng):
    """
    Geocodificacao REVERSA (coordenada -> endereco).
    Muito mais confiavel que tentar achar por texto no OSM.
    Retorna dict com road, suburb, city, display_name ou None.
    """
    headers = {"User-Agent": "RotaHub-Nominatim/1.0 (uso pessoal nao comercial)"}
    params = {"lat": lat, "lon": lng, "format": "json", "accept-language": "pt-BR"}
    try:
        resp = requests.get(f"{NOMINATIM_URL}/reverse", params=params,
                           headers=headers, timeout=NOMINATIM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data and "lat" in data:
            addr = data.get("address", {})
            return {
                "display_name": data.get("display_name", ""),
                "road": addr.get("road", ""),
                "house_number": addr.get("house_number", ""),
                "suburb": addr.get("suburb", addr.get("neighbourhood", "")),
                "city": addr.get("city", addr.get("municipality", "")),
                "postcode": addr.get("postcode", ""),
            }
    except requests.RequestException:
        pass
    return None


def _nominatim_forward(address, neighborhood, city, zipcode):
    """Geocodificacao forward (texto -> coordenada). Usada como fallback."""
    query_parts = [address]
    if neighborhood:
        query_parts.append(neighborhood)
    city_final = city or "Sao Paulo"
    query_parts.append(city_final)
    if zipcode:
        cleaned = zipcode.replace("-", "").replace(" ", "").strip()
        if len(cleaned) >= 5:
            query_parts.append(f"CEP {cleaned}")
    query_parts.append("Brazil")

    headers = {"User-Agent": "RotaNote-Nominatim/1.0 (uso pessoal nao comercial)"}
    params = {"q": ", ".join(query_parts), "format": "json", "limit": 5,
              "countrycodes": "br", "addressdetails": 1}
    try:
        resp = requests.get(f"{NOMINATIM_URL}/search", params=params,
                           headers=headers, timeout=NOMINATIM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        # prioriza resultado com o CEP batendo
        cleaned = (zipcode or "").replace("-", "").replace(" ", "").strip()
        best = data[0]
        for c in data:
            if cleaned and cleaned[:5] in c.get("display_name", ""):
                best = c
                break
        return float(best["lat"]), float(best["lon"])
    except requests.RequestException:
        return None


def _brasilapi_cep(zipcode):
    """
    Consulta o CEP na BrasilAPI (ViaCEP) gratuita.
    Retorna dict com street, neighborhood, city, state, lat, lng, ou None.
    """
    cep_clean = (zipcode or "").replace("-", "").replace(" ", "").strip()
    if len(cep_clean) != 8:
        return None
    try:
        resp = requests.get(f"{BRASILAPI_CEP_URL}/{cep_clean}",
                           timeout=BRASILAPI_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        coords = data.get("location", {}).get("coordinates", {})
        return {
            "street": data.get("street", ""),
            "neighborhood": data.get("neighborhood", ""),
            "city": data.get("city", ""),
            "state": data.get("state", ""),
            "lat": float(coords.get("latitude", 0) or 0),
            "lng": float(coords.get("longitude", 0) or 0),
        }
    except requests.RequestException:
        return None


def _fuzzy_match_street(street_a, street_b):
    """Comparacao fuzzy entre dois nomes de rua. Retorna score 0 a 1."""
    a = (street_a or "").lower().replace(".", "").replace("rua ", "").replace("r ", "").replace("avenida ", "").replace("av ", "").strip()
    b = (street_b or "").lower().replace(".", "").replace("rua ", "").replace("r ", "").replace("avenida ", "").replace("av ", "").strip()
    if not a or not b:
        return 0.0
    # palavras compartilhadas
    words_a = set(a.split())
    words_b = set(b.split())
    intersection = words_a & words_b
    union = words_a | words_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


@app.post("/routes/{route_id}/verify-addresses", response_model=schemas.VerifyAddressesResponse)
def verify_route_addresses(route_id: int, db: Session = Depends(get_db),
                            current: User = Depends(auth_mod.get_current_user)):
    """
    Verifica se as coordenadas das paradas batem com o endereco textual.
    
    Estrategia gratuita em 3 camadas:
    1) Nominatim reverso (coordenada -> endereco) — mais confiavel
       que forward porque o OSM tem os dados indexados por posicao.
    2) BrasilAPI (ViaCEP) — quando tem CEP, valida se a coordenada
       do CEP confere com a da planilha.
    3) Nominatim forward (texto -> coordenada) — fallback.
    """
    route = _get_owned_route(db, route_id)
    results = []
    issues = 0

    for stop in route.stops:
        original_lat, original_lng = stop.latitude, stop.longitude
        address = (stop.address or "").strip()
        neighborhood = (stop.neighborhood or "").strip()
        city = (stop.city or "").strip()
        zipcode = (stop.zipcode or "").strip()

        distance_m = None
        geocoded_lat = geocoded_lng = None
        needs_review = False
        message = "OK"
        checks = []

        # --- CAMADA 1: Nominatim reverso --------------------------------
        reverse_data = None
        rev_info = _nominatim_reverse(original_lat, original_lng)
        time.sleep(NOMINATIM_RATE_LIMIT_DELAY)
        if rev_info:
            reverse_data = rev_info
            osm_road = rev_info.get("road", "")
            osm_suburb = rev_info.get("suburb", "")

            # compara nome da street da planilha vs OSM
            street_score = _fuzzy_match_street(address, osm_road)
            checks.append(f"OSM reverse: {osm_road or '(sem rua)'}")

            if osm_road and street_score > 0.3:
                checks.append(f"rua OK (match {street_score:.0%})")
                if osm_suburb and neighborhood:
                    sub_score = _fuzzy_match_street(neighborhood, osm_suburb)
                    if sub_score > 0.3:
                        checks.append(f"bairro OK")
                    else:
                        checks.append(f"bairro: OSM={osm_suburb} vs planilha={neighborhood}")
            elif osm_road and street_score <= 0.3:
                checks.append(f"rua divergente! ({street_score:.0%})")
                needs_review = True
            elif not osm_road:
                # sem rua no OSM (avenida expressa, area rural?)
                checks.append("endereco sem rua no OSM")

        # --- Camada 2: BrasilAPI CEP -----------------------------------
        if zipcode:
            cep_data = _brasilapi_cep(zipcode)
            if cep_data and cep_data["lat"] != 0 and cep_data["lng"] != 0:
                cep_lat, cep_lng = cep_data["lat"], cep_data["lng"]
                dist_cep = _haversine_m(original_lat, original_lng, cep_lat, cep_lng)
                checks.append(f"ViaCEP: {cep_data.get('street','')} ({dist_cep:.0f}m coords)")

                if not needs_review:
                    if dist_cep > 500:
                        geocoded_lat, geocoded_lng = cep_lat, cep_lng
                        distance_m = dist_cep
                        needs_review = True

        # --- Camada 3: Nominatim forward (fallback) --------------------
        if geocoded_lat is None:
            fwd = _nominatim_forward(address, neighborhood, city, zipcode)
            if fwd:
                geocoded_lat, geocoded_lng = fwd
                distance_m = _haversine_m(original_lat, original_lng, geocoded_lat, geocoded_lng)
                checks.append(f"OSM forward: {distance_m:.0f}m")
                if distance_m > VERIFY_THRESHOLD_METERS:
                    checks[-1] = f">>> DISCREPANCIA: {distance_m:.0f}m entre planilha e OSM forward"
                    needs_review = True

        if needs_review:
            issues += 1
            message = " | ".join(checks) if checks else "Needs review"
        else:
            message = " | ".join(checks) if checks else "OK"

        results.append(schemas.VerifyResult(
            stop_id=stop.id,
            address=stop.address,
            original_lat=original_lat,
            original_lng=original_lng,
            geocoded_lat=geocoded_lat,
            geocoded_lng=geocoded_lng,
            distance_meters=round(distance_m, 1) if distance_m else None,
            needs_review=needs_review,
            message=message,
        ))

    return schemas.VerifyAddressesResponse(
        route_id=route.id,
        checked=len(results),
        issues_found=issues,
        results=results,
        source="nominatim+",
    )


# ------------------------------------------------------------ FRONTEND ----
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def _file_hash(path: str) -> str:
    """Hash curto do CONTEÚDO real do arquivo - usado como versão na URL.
    Se o arquivo mudar um byte sequer, o hash muda, a URL muda, e o
    navegador é OBRIGADO a buscar a versão nova - não depende de ninguém
    lembrar de bumpar um número manualmente (isso já causou confusão real
    numa sessão de depuração: usuário testando código velho sem saber)."""
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    except FileNotFoundError:
        return "0"


if os.path.isdir(_frontend_dir):
    @app.get("/", include_in_schema=False)
    def serve_index():
        index_path = os.path.join(_frontend_dir, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        js_hash = _file_hash(os.path.join(_frontend_dir, "app.js"))
        css_hash = _file_hash(os.path.join(_frontend_dir, "style.css"))
        html = html.replace("app.js?v=9", f"app.js?v={js_hash}")
        html = html.replace("style.css?v=9", f"style.css?v={css_hash}")
        return HTMLResponse(
            content=html,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
