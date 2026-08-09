"""
RF006 - Otimização de rota (TSP) com Google OR-Tools.

Por que isso resolve o problema relatado ("Circuit manda dar uma volta
desnecessária"): apps como o Circuit costumam usar heurísticas gulosas
(vizinho mais próximo), que otimizam passo-a-passo sem enxergar a rota
inteira - por isso "abandonam" uma rua e são obrigados a voltar depois.

O OR-Tools roda um solver real de roteamento com metaheurística de melhoria
(Guided Local Search), que reavalia a rota completa e minimiza a distância
total - não só o próximo passo. Isso naturalmente agrupa paradas da mesma
rua, mesmo que não sejam "as mais próximas" no momento exato da parada atual.
"""
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# precisão fixa para converter float (km) em inteiro (metros) - o OR-Tools
# trabalha com custos inteiros
SCALE = 1000


def solve_tsp(distance_matrix_km, start_index=0, time_limit_seconds=10):
    """
    distance_matrix_km: matriz NxN de distâncias em km (pode ser assimétrica,
    já que ruas de mão única tornam ida != volta).
    start_index: índice do ponto de partida (0 = primeiro ponto da lista,
    normalmente a origem/depósito).

    Retorna a lista de índices na ordem otimizada da rota (sem voltar à
    origem no final - é uma rota aberta, não um ciclo, já que o entregador
    não precisa retornar ao ponto de partida).
    """
    n = len(distance_matrix_km)
    if n <= 1:
        return list(range(n))
    if n == 2:
        return [0, 1] if start_index == 0 else [1, 0]

    # Truque padrão para TSP de ROTA ABERTA (o entregador nao precisa voltar
    # ao ponto de partida): adiciona um no ficticio com distancia 0 para/de
    # todos os outros nos, e forca a rota a terminar nele. O solver entao
    # escolhe livremente onde "parar de verdade".
    dummy = n
    augmented = [row[:] + [0.0] for row in distance_matrix_km]
    augmented.append([0.0] * (n + 1))

    manager = pywrapcp.RoutingIndexManager(n + 1, 1, [start_index], [dummy])
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(round(augmented[from_node][to_node] * SCALE))

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.FromSeconds(time_limit_seconds)

    solution = routing.SolveWithParameters(search_parameters)
    if solution is None:
        # fallback de segurança: ordem original
        return list(range(n))

    order = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != dummy:
            order.append(node)
        index = solution.Value(routing.NextVar(index))
    return order


def route_total_distance(order, distance_matrix_km):
    return sum(
        distance_matrix_km[order[i]][order[i + 1]] for i in range(len(order) - 1)
    )


def route_total_duration(order, duration_matrix_min):
    return sum(
        duration_matrix_min[order[i]][order[i + 1]] for i in range(len(order) - 1)
    )
