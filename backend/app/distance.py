"""
RF006 - Matriz de distância/tempo entre paradas.

Estratégia (o diferencial do RotaHub vs Circuit):
1) Tenta o OSRM público (router.project-osrm.org) - Table Service - que devolve
   distância e tempo REAIS de rua entre todos os pontos numa única chamada.
   Isso evita o problema relatado pelo usuário (voltas desnecessárias), porque
   o TSP passa a otimizar pela rua de verdade, não pela linha reta.
2) Se o OSRM não responder (timeout, offline, fora do ar), cai automaticamente
   para uma matriz Haversine (linha reta) como fallback, para o app nunca travar.
   Isso é sinalizado em Route.distance_source, para o usuário saber qual foi usado.
"""
import requests
from .geo import haversine

OSRM_BASE_URL = "https://router.project-osrm.org"
OSRM_TIMEOUT = 15
AVG_URBAN_SPEED_KMH = 25  # usado para estimar tempo no fallback haversine


def build_distance_matrix(points):
    """
    points: lista de dicts com 'latitude' e 'longitude', na ordem em que
    devem aparecer na matriz (índice 0..N-1).

    Retorna (distance_matrix_km, duration_matrix_min, source) onde source é
    "osrm" ou "haversine".
    """
    matrix = _try_osrm_table(points)
    if matrix is not None:
        return matrix[0], matrix[1], "osrm"
    return _haversine_matrix(points), _haversine_duration_matrix(points), "haversine"


def _try_osrm_table(points):
    if len(points) < 2:
        return None
    if len(points) > 300:
        # a API pública do OSRM tem limite prático de tamanho de request;
        # para rotas muito grandes, recomenda-se instância própria (self-hosted).
        return None
    coords = ";".join(f"{p['longitude']},{p['latitude']}" for p in points)
    url = f"{OSRM_BASE_URL}/table/v1/driving/{coords}"
    params = {"annotations": "distance,duration"}
    try:
        resp = requests.get(url, params=params, timeout=OSRM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "Ok":
            return None
        distances_m = data["distances"]
        durations_s = data["durations"]
        if any(row is None for row in distances_m):
            return None
        dist_km = [[(v or 0) / 1000.0 for v in row] for row in distances_m]
        dur_min = [[(v or 0) / 60.0 for v in row] for row in durations_s]
        return dist_km, dur_min
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def _haversine_matrix(points):
    n = len(points)
    m = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                m[i][j] = haversine(
                    points[i]["latitude"], points[i]["longitude"],
                    points[j]["latitude"], points[j]["longitude"],
                )
    return m


def _haversine_duration_matrix(points):
    dist = _haversine_matrix(points)
    # Linha reta subestima tempo real (ruas não são retas) - aplicamos um
    # fator de correção de 1.3x (heurística comum em roteamento urbano) além
    # da velocidade média urbana, para o fallback não ser otimista demais.
    factor = 1.3
    return [[(d * factor / AVG_URBAN_SPEED_KMH) * 60 for d in row] for row in dist]
