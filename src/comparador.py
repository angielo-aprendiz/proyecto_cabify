"""
Compara varias particiones (agrupaciones de vehículos) usando el costo REAL
que devuelve /estimates de Cabify — nunca haversine.
"""
from src import journeys
from src.optimizer import generar_ordenes_candidatos


def evaluar_particion(requester_id: str, tienda: dict, particion: dict, config) -> dict:
    """Pide un /estimates real para cada vehículo de la partición y arma un
    resumen: costo total, si es válida, y por qué no si no lo es."""
    estimates = {}
    costo_total = 0
    valido = True
    motivos_invalidos = []

    for v, datos in particion.items():
        resultado = journeys.solicitar_estimate(requester_id, tienda, datos["paradas"])
        estimates[v] = resultado

        if not resultado["valido"]:
            valido = False
            motivos_invalidos.append(f"vehículo {v + 1}: {resultado['error']}")
            continue

        if resultado["distancia"] > config.DISTANCIA_MAX_POR_VEHICULO:
            valido = False
            motivos_invalidos.append(
                f"vehículo {v + 1}: distancia real {resultado['distancia'] / 1000:.1f} km "
                f"supera el máximo de {config.DISTANCIA_MAX_POR_VEHICULO / 1000:.0f} km"
            )
            continue

        costo_total += resultado["cheapest_option"]["total"]["amount"]

    return {
        "valido": valido,
        "motivos_invalidos": motivos_invalidos,
        "costo_total": costo_total,
        "estimates": estimates,
        "num_vehiculos": len(particion),
    }


def elegir_mejor_particion(requester_id: str, tienda: dict, candidatos: list[dict], config):
    """Evalúa todas las particiones candidatas y devuelve la de menor costo
    total real entre las válidas.

    Devuelve (mejor_particion, mejor_evaluacion, evaluaciones_completas) donde
    mejor_particion/mejor_evaluacion son None si ninguna candidata es válida.
    """
    evaluaciones = []
    for particion in candidatos:
        evaluacion = evaluar_particion(requester_id, tienda, particion, config)
        evaluaciones.append((particion, evaluacion))

    validas = [(p, e) for p, e in evaluaciones if e["valido"]]
    if not validas:
        return None, None, evaluaciones

    mejor_particion, mejor_evaluacion = min(validas, key=lambda pe: pe[1]["costo_total"])
    return mejor_particion, mejor_evaluacion, evaluaciones


def optimizar_orden_particion(requester_id: str, tienda: dict, particion: dict, evaluacion: dict, config) -> dict:
    """Sobre la partición YA elegida (mismo agrupamiento de paradas por vehículo),
    prueba órdenes alternativos de las paradas de cada vehículo contra /estimates
    real y se queda con el más barato. No mueve paradas entre vehículos, solo
    reordena dentro de cada uno: /estimates de Cabify cobra distinto según el
    orden en que se visitan las paradas, y la heurística de vecino más cercano
    usada al generar candidatos no garantiza el orden más barato.

    Devuelve una evaluación con la misma forma que evaluar_particion (valido,
    costo_total, estimates, num_vehiculos), con `particion` actualizada in-place
    para reflejar el orden final de paradas de cada vehículo.
    """
    estimates = dict(evaluacion["estimates"])
    costo_total = 0
    mejoras = {}

    for v, datos in particion.items():
        estimate_actual = estimates[v]
        if not estimate_actual["valido"]:
            continue

        mejor_estimate = estimate_actual
        mejor_orden = datos["paradas"]
        mejor_costo = estimate_actual["cheapest_option"]["total"]["amount"]
        costo_original = mejor_costo

        for orden in generar_ordenes_candidatos(datos["paradas"], config):
            if orden == datos["paradas"]:
                continue
            resultado = journeys.solicitar_estimate(requester_id, tienda, orden)
            if resultado["valido"] and resultado["cheapest_option"]["total"]["amount"] < mejor_costo:
                mejor_costo = resultado["cheapest_option"]["total"]["amount"]
                mejor_estimate = resultado
                mejor_orden = orden

        datos["paradas"] = mejor_orden
        estimates[v] = mejor_estimate
        costo_total += mejor_costo
        if mejor_costo < costo_original:
            mejoras[v] = (costo_original, mejor_costo)

    return {
        **evaluacion,
        "estimates": estimates,
        "costo_total": costo_total,
        "mejoras_orden": mejoras,
    }
