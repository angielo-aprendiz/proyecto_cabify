"""
Generación de PARTICIONES CANDIDATAS de vehículos (agrupaciones de paradas).

Importante: este módulo ya NO decide cuál partición es "la mejor". Solo genera
varias formas razonables de agrupar las paradas en vehículos. La decisión final
(¿cuál agrupación resulta más barata / válida?) se toma en `comparador.py`
usando la distancia y el costo REALES que devuelve /estimates de Cabify — no
haversine.

Haversine se sigue usando aquí, pero únicamente como heurística barata para:
  1) que OR-Tools tenga una función de costo con la que agrupar paradas
     (agrupar por línea recta es una aproximación razonable y gratis), y
  2) ordenar las paradas dentro de un vehículo por vecino más cercano.
Nunca se usa para validar el límite de km ni para elegir la agrupación final.
"""
import math
import itertools
from ortools.constraint_solver import routing_enums_pb2, pywrapcp


def haversine(loc1, loc2) -> int:
    R = 6_371_000
    lat1, lon1 = math.radians(loc1[0]), math.radians(loc1[1])
    lat2, lon2 = math.radians(loc2[0]), math.radians(loc2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return int(R * 2 * math.asin(math.sqrt(a)))


def _ordenar_por_vecino_cercano(tienda: dict, paradas: list[dict]) -> list[dict]:
    """Ordena un grupo de paradas por vecino más cercano partiendo de la tienda.
    Es solo una heurística de orden para enviar un `stops` razonable a /estimates
    (Cabify puede igual reordenar internamente, ver punto 4 de la revisión)."""
    restantes = list(paradas)
    ordenado = []
    actual = tienda["loc"]
    while restantes:
        siguiente = min(restantes, key=lambda p: haversine(actual, p["loc"]))
        ordenado.append(siguiente)
        restantes.remove(siguiente)
        actual = siguiente["loc"]
    return ordenado


def _particion_valida(particion: dict, config) -> bool:
    if not particion or len(particion) > config.NUM_VEHICULOS_MAX:
        return False
    for datos in particion.values():
        if datos["personas"] > config.MAX_PERSONAS_POR_VEHICULO:
            return False
    return True


def _firma(particion: dict) -> tuple:
    """Firma canónica para deduplicar particiones equivalentes (mismo agrupamiento,
    sin importar el índice de vehículo ni el orden interno)."""
    return tuple(sorted(tuple(sorted(p["addr"] for p in d["paradas"])) for d in particion.values()))


def _resolver_or_tools(tienda: dict, paradas_raw: list[dict], num_vehiculos: int, config) -> dict | None:
    """Agrupa paradas en `num_vehiculos` vehículos minimizando distancia haversine
    (heurística de agrupación, no de validación de km reales)."""
    all_locs = [tienda["loc"]] + [p["loc"] for p in paradas_raw]
    n = len(all_locs)
    distance_matrix = [[haversine(all_locs[i], all_locs[j]) for j in range(n)] for i in range(n)]

    n_total = n + num_vehiculos
    starts = [0] * num_vehiculos
    ends = list(range(n, n_total))

    manager = pywrapcp.RoutingIndexManager(n_total, num_vehiculos, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_idx, to_idx):
        i, j = manager.IndexToNode(from_idx), manager.IndexToNode(to_idx)
        if i >= n or j >= n:
            return 0
        return distance_matrix[i][j]

    transit_cb = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

    for v in range(num_vehiculos):
        routing.SetFixedCostOfVehicle(config.COSTO_FIJO_VEHICULO, v)

    def demand_callback(from_idx):
        node = manager.IndexToNode(from_idx)
        if node == 0 or node >= n:
            return 0
        return paradas_raw[node - 1]["personas"]

    demand_cb = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb, 0, [config.MAX_PERSONAS_POR_VEHICULO] * num_vehiculos, True, "Capacidad"
    )

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 10

    solution = routing.SolveWithParameters(search_params)
    if not solution:
        return None

    particion = {}
    idx = 0
    for v in range(num_vehiculos):
        index = routing.Start(v)
        ruta = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0 and node < n:
                ruta.append(paradas_raw[node - 1])
            index = solution.Value(routing.NextVar(index))
        if ruta:
            particion[idx] = {"paradas": ruta, "personas": sum(p["personas"] for p in ruta)}
            idx += 1

    return particion if particion else None


def _cluster_geografico(paradas_raw: list[dict], k: int, iters: int = 25) -> list[list[dict]]:
    """K-means simple en lat/lon (sin dependencias extra) para generar agrupaciones
    geográficas distintas a las de OR-Tools, y así tener candidatos variados."""
    if k <= 0:
        return []
    if k >= len(paradas_raw):
        return [[p] for p in paradas_raw]

    # Semillas iniciales: las k paradas más separadas entre sí (determinístico)
    centros = [paradas_raw[0]["loc"]]
    while len(centros) < k:
        candidato = max(paradas_raw, key=lambda p: min(haversine(p["loc"], c) for c in centros))
        centros.append(candidato["loc"])

    asignacion = [0] * len(paradas_raw)
    for _ in range(iters):
        cambiado = False
        for i, p in enumerate(paradas_raw):
            nuevo = min(range(k), key=lambda c: haversine(p["loc"], centros[c]))
            if nuevo != asignacion[i]:
                asignacion[i] = nuevo
                cambiado = True

        nuevos_centros = []
        for c in range(k):
            miembros = [paradas_raw[i]["loc"] for i in range(len(paradas_raw)) if asignacion[i] == c]
            if miembros:
                lat = sum(m[0] for m in miembros) / len(miembros)
                lon = sum(m[1] for m in miembros) / len(miembros)
                nuevos_centros.append([lat, lon])
            else:
                nuevos_centros.append(centros[c])
        centros = nuevos_centros

        if not cambiado:
            break

    grupos = [[] for _ in range(k)]
    for i, p in enumerate(paradas_raw):
        grupos[asignacion[i]].append(p)
    return [g for g in grupos if g]


def _2opt(paradas: list[dict]) -> list[dict]:
    """Mejora un orden de paradas con 2-opt sobre distancia haversine hasta
    que ningún intercambio de tramo reduzca la distancia total (óptimo local,
    barato de calcular, sin llamadas a la API)."""

    def costo(orden: list[dict]) -> int:
        return sum(haversine(orden[i]["loc"], orden[i + 1]["loc"]) for i in range(len(orden) - 1))

    mejor = list(paradas)
    mejorado = True
    while mejorado:
        mejorado = False
        for i in range(len(mejor) - 1):
            for j in range(i + 1, len(mejor)):
                candidato = mejor[:i] + mejor[i:j + 1][::-1] + mejor[j + 1:]
                if costo(candidato) < costo(mejor):
                    mejor = candidato
                    mejorado = True
    return mejor


def generar_ordenes_candidatos(paradas: list[dict], config) -> list[list[dict]]:
    """Genera órdenes alternativos de las MISMAS paradas de un vehículo, para
    que comparador.py los verifique con /estimates real y se quede con el más
    barato (el costo de Cabify depende del orden en que se envían los `stops`,
    no solo de qué paradas van juntas).

    Con pocas paradas prueba fuerza bruta (todas las permutaciones): correcto
    pero N! llamadas a la API. Con más paradas eso es inviable, así que se usa
    2-opt sobre haversine para proponer un único orden mejorado (heurística,
    no garantiza el óptimo, pero cuesta 1 sola llamada de verificación).
    """
    if len(paradas) <= 1:
        return [list(paradas)]

    if len(paradas) <= config.MAX_PARADAS_ORDEN_EXACTO:
        return [list(orden) for orden in itertools.permutations(paradas)]

    return [_2opt(paradas)]


def _dividir_por_capacidad(grupo: list[dict], capacidad_max: int) -> list[list[dict]]:
    """Si un cluster geográfico excede la capacidad de un vehículo, lo parte en
    sub-grupos consecutivos que sí quepan."""
    subgrupos = []
    actual, personas_actual = [], 0
    for p in grupo:
        if actual and personas_actual + p["personas"] > capacidad_max:
            subgrupos.append(actual)
            actual, personas_actual = [], 0
        actual.append(p)
        personas_actual += p["personas"]
    if actual:
        subgrupos.append(actual)
    return subgrupos


def _costo_proxy_particion(tienda: dict, particion: dict, config) -> int:
    """Costo aproximado y GRATIS (sin llamar a /estimates) de una partición,
    usado solo para RANKEAR candidatos antes de gastar llamadas reales a la
    API. Suma, por cada vehículo, la distancia haversine de su ruta (tienda ->
    paradas en el orden dado) más el costo fijo por vehículo usado — el mismo
    criterio que ya usa OR-Tools internamente (ver `_resolver_or_tools`).
    No es el costo real de Cabify (eso depende de tarifas, tráfico, producto,
    etc.), solo una heurística barata para descartar candidatos claramente
    peores sin consultar la API."""
    total = 0
    for datos in particion.values():
        ruta = [tienda["loc"]] + [p["loc"] for p in datos["paradas"]]
        distancia = sum(haversine(ruta[i], ruta[i + 1]) for i in range(len(ruta) - 1))
        total += distancia + config.COSTO_FIJO_VEHICULO
    return total


def filtrar_mejores_candidatos(tienda: dict, candidatos: list[dict], config, top_n: int | None = None) -> list[dict]:
    """Rankea las particiones candidatas por el costo-proxy de
    `_costo_proxy_particion` (barato, sin API) y devuelve solo las `top_n`
    más prometedoras.

    Sin este filtro, `comparador.elegir_mejor_particion` llama a /estimates
    por CADA vehículo de CADA candidata generada (pueden ser 20-30+ llamadas
    por tienda). Al quedarnos solo con las `top_n` candidatas con menor costo
    estimado, se reducen drásticamente las llamadas reales sin cambiar el
    criterio de selección final (sigue siendo el costo REAL de /estimates
    entre las candidatas evaluadas). -> desicion tomada despues de generar varios timeout """
    top_n = config.TOP_N_CANDIDATOS if top_n is None else top_n
    if len(candidatos) <= top_n:
        return candidatos
    return sorted(candidatos, key=lambda p: _costo_proxy_particion(tienda, p, config))[:top_n]


def generar_candidatos(tienda: dict, paradas_raw: list[dict], config) -> list[dict]:
    """Genera varias particiones candidatas para comparar su costo REAL después.

    Se incluyen, entre otras:
      - Un solo vehículo con todas las paradas (si la capacidad lo permite):
        un viaje dividido en varios vehículos puede terminar costando más que uno solo con
        varias parads.
      - Agrupaciones optimizadas por OR-Tools con distintos números de vehículos.
      - Agrupaciones por clustering geográfico con distintos números de vehículos.
      - El caso extremo de un vehículo por parada (si hay cupo de vehículos),
        para poder cuantificar cuánto cuesta "no compartir" viajes.
    Cada partición se valida (capacidad y máximo de vehículos) pero NINGUNA se
    descarta aquí por distancia: ese chequeo se hace con la distancia real de
    /estimates en comparador.py.
    """
    total_personas = sum(p["personas"] for p in paradas_raw)
    min_vehiculos = math.ceil(total_personas / config.MAX_PERSONAS_POR_VEHICULO)
    max_vehiculos = min(config.NUM_VEHICULOS_MAX, len(paradas_raw))

    candidatos = []
    vistos = set()

    def _agregar(particion):
        if particion and _particion_valida(particion, config):
            firma = _firma(particion)
            if firma not in vistos:
                vistos.add(firma)
                candidatos.append(particion)

    # 1) Un solo vehículo con todas las paradas, si cabe.
    if total_personas <= config.MAX_PERSONAS_POR_VEHICULO:
        ordenado = _ordenar_por_vecino_cercano(tienda, paradas_raw)
        _agregar({0: {"paradas": ordenado, "personas": total_personas}})

    # 2) OR-Tools con distinto número de vehículos disponibles.
    for k in {min_vehiculos, max_vehiculos}:
        if k >= 1:
            _agregar(_resolver_or_tools(tienda, paradas_raw, k, config))

    # 3) Clustering geográfico con distinto número de grupos, partiendo por
    #    capacidad si algún cluster resulta demasiado grande.
    for k in range(min_vehiculos, max_vehiculos + 1):
        clusters = _cluster_geografico(paradas_raw, k)
        particion, idx = {}, 0
        for cluster in clusters:
            for sub in _dividir_por_capacidad(cluster, config.MAX_PERSONAS_POR_VEHICULO):
                ordenado = _ordenar_por_vecino_cercano(tienda, sub)
                particion[idx] = {"paradas": ordenado, "personas": sum(p["personas"] for p in sub)}
                idx += 1
        _agregar(particion)

    # 4) Caso extremo: un vehículo por parada (si hay cupo suficiente).
    if len(paradas_raw) <= max_vehiculos:
        _agregar({i: {"paradas": [p], "personas": p["personas"]} for i, p in enumerate(paradas_raw)})

    return candidatos
