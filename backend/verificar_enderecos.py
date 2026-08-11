"""
Verifica, para TODAS as paradas de uma rota, se o endereço em texto (o mesmo
que o botão "Navegar" usa) geocodifica perto da coordenada que veio da
planilha. Roda no SEU computador (precisa de internet de verdade - não
funciona no ambiente de desenvolvimento do Claude).

Uso:
    python verificar_enderecos.py <route_id> <username> <password>

Exemplo:
    python verificar_enderecos.py 3 bruna rotahub2026

O que ele faz:
1. Busca todas as paradas da rota no seu RotaHub local (localhost:8000).
2. Pra cada parada, geocodifica o MESMO texto que o botão "Navegar" manda
   pro Google Maps, usando o Nominatim (serviço gratuito do OpenStreetMap).
3. Compara a coordenada geocodificada com a coordenada que veio da planilha.
4. Se a diferença for grande (>150m), marca como "VERIFICAR MANUALMENTE" -
   pode ser um problema de endereço incompleto/mal escrito na planilha, ou
   uma rua sem numeração bem indexada nessa região.

IMPORTANTE sobre o Nominatim: é um serviço público e gratuito, com uso
"gentil" esperado - por isso o script espera 1 segundo entre cada consulta,
de propósito. Pra uma rota de até ~100 paradas, isso leva 1-2 minutos.
"""
import sys
import time
import math
import requests

API_BASE = "http://localhost:8000"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim exige um User-Agent identificável - não funciona sem isso.
HEADERS = {"User-Agent": "RotaHub-VerificadorEnderecos/1.0 (uso pessoal)"}
ALERTA_METROS = 150


def haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def login(username, password):
    resp = requests.post(f"{API_BASE}/auth/login", data={"username": username, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_route(route_id, token):
    resp = requests.get(f"{API_BASE}/routes/{route_id}", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return resp.json()


def geocode(address_text):
    params = {"q": address_text, "format": "json", "limit": 1, "countrycodes": "br"}
    resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def main():
    if len(sys.argv) != 4:
        print("Uso: python verificar_enderecos.py <route_id> <username> <password>")
        sys.exit(1)

    route_id, username, password = sys.argv[1], sys.argv[2], sys.argv[3]
    token = login(username, password)
    route = get_route(route_id, token)
    stops = route["stops"]

    print(f"\nVerificando {len(stops)} paradas da rota '{route['name']}'...\n")

    problemas = []
    for i, s in enumerate(stops, start=1):
        parts = [s["address"], s.get("neighborhood"), s.get("city") or "São Paulo"]
        destino_texto = ", ".join(p for p in parts if p)

        geo = geocode(destino_texto)
        if geo is None:
            print(f"[{i:>2}] {s['address']:<45} -> Nominatim não encontrou esse endereço")
            problemas.append((s, destino_texto, None, None))
        else:
            dist = haversine_m(s["latitude"], s["longitude"], geo[0], geo[1])
            status = "OK" if dist <= ALERTA_METROS else "VERIFICAR MANUALMENTE"
            marcador = "  " if dist <= ALERTA_METROS else "⚠️ "
            print(f"{marcador}[{i:>2}] {s['address']:<45} dist. planilha↔texto: {dist:6.0f}m  [{status}]")
            if dist > ALERTA_METROS:
                problemas.append((s, destino_texto, dist, geo))

        time.sleep(1)  # respeita o limite de uso do Nominatim (1 req/s)

    print("\n" + "=" * 70)
    if not problemas:
        print("Tudo certo - nenhuma parada com discrepância grande.")
    else:
        print(f"{len(problemas)} parada(s) merecem uma olhada manual antes de sair pra rua:\n")
        for s, texto, dist, geo in problemas:
            print(f"  - {s['address']} ({s.get('complement') or 'sem complemento'})")
            if dist is not None:
                print(f"    planilha diz: {s['latitude']}, {s['longitude']}")
                print(f"    texto aponta pra: {geo[0]}, {geo[1]}  (diferença: {dist:.0f}m)")
            else:
                print(f"    texto buscado não foi encontrado: \"{texto}\"")
            print()


if __name__ == "__main__":
    main()
