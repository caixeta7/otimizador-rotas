"""
Utilitários geográficos.
- haversine(): distância em linha reta entre dois pontos (km)
- cluster_by_proximity(): agrupa pontos que representam o MESMO prédio/condomínio
  (tolerância pequena, ~25m) - usado para juntar pacotes na mesma parada física,
  SEM depender do campo "Stop" da Shopee, que provamos ser inconsistente.
- geocode_nominatim(): fallback gratuito de geocodificação (OpenStreetMap) para
  endereços sem lat/lng.
"""
import math
import time
import requests

CLUSTER_TOLERANCE_METERS = 25  # ~ mesmo prédio / mesmo lote
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def haversine(lat1, lon1, lat2, lon2):
    """Distância em km entre dois pontos (linha reta)."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def cluster_by_proximity(points, tolerance_m=CLUSTER_TOLERANCE_METERS):
    """
    points: lista de dicts com 'latitude' e 'longitude'.
    Retorna lista paralela de índices de cluster (0..N-1), agrupando pontos
    cuja distância entre si é menor que a tolerância.

    IMPORTANTE: cada cluster usa uma ÂNCORA FIXA (o primeiro ponto que abriu
    o grupo), não um centróide que se desloca a cada novo ponto adicionado.
    Um centróide móvel permite um "efeito cadeia": ponto B a 20m de A entra
    no grupo, o centro desloca pro meio dos dois, e um ponto C a 20m desse
    centro (mas até ~35-40m do A original) também entra - juntando pontos
    mais distantes entre si do que a tolerância configurada, o que na
    prática pode juntar endereços de ruas diferentes numa mesma parada.
    Com âncora fixa, todo ponto do cluster garantidamente fica a no máximo
    `tolerance_m` do ponto que abriu o grupo.
    """
    tolerance_km = tolerance_m / 1000.0
    anchors = []  # [(lat, lng)] - nunca muda depois de criado
    assignment = []

    for p in points:
        lat, lng = p["latitude"], p["longitude"]
        found = None
        for idx, (alat, alng) in enumerate(anchors):
            if haversine(lat, lng, alat, alng) <= tolerance_km:
                found = idx
                break
        if found is None:
            anchors.append((lat, lng))
            assignment.append(len(anchors) - 1)
        else:
            assignment.append(found)

    return assignment


def geocode_nominatim(address: str, city: str = "São Paulo", country: str = "Brazil", timeout=8):
    """
    Fallback gratuito via OpenStreetMap Nominatim.
    Usado SOMENTE quando a planilha não trouxe lat/lng (RF005).
    Respeita rate-limit de 1 req/s da política de uso do Nominatim.
    Retorna (lat, lng) ou None se não encontrado.
    """
    query = f"{address}, {city}, {country}"
    headers = {"User-Agent": "RotaHub/1.0 (uso pessoal - projeto nao comercial)"}
    params = {"q": query, "format": "json", "limit": 1}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        time.sleep(1.0)  # respeita rate limit de 1 req/s
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except requests.RequestException:
        pass
    return None
