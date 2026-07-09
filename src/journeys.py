"""
Llamadas a /estimates y /journey de Cabify, con manejo de errores explícito.
"""
from src import cabify_client
from src.optimizer import haversine
from config.settings import config


def _stops_payload(tienda: dict, paradas: list[dict]) -> list[dict]:
    ruta_completa = [tienda] + paradas
    return [
        {"addr": p["addr"], "city": p["city"], "country": p["country"], "loc": p["loc"]}
        for p in ruta_completa
    ]


def _validar_distancia_minima(stops_payload: list[dict]) -> str | None:
    """Cabify responde 422 si dos paradas de la misma ruta están demasiado
    cerca entre sí. Revisa todos los pares (no solo consecutivos) y devuelve
    un mensaje de error si alguno está por debajo del mínimo, o None si todo bien."""
    minimo = config.DISTANCIA_MIN_ENTRE_PARADAS_M
    for i in range(len(stops_payload)):
        for j in range(i + 1, len(stops_payload)):
            distancia = haversine(stops_payload[i]["loc"], stops_payload[j]["loc"])
            if distancia < minimo:
                return (
                    f"'{stops_payload[i]['addr']}' y '{stops_payload[j]['addr']}' están a "
                    f"{distancia} m, menos del mínimo de {minimo} m entre paradas"
                )
    return None


def solicitar_estimate(requester_id: str, tienda: dict, paradas: list[dict]) -> dict:
    """Devuelve un dict con resultado normalizado: {"valido": bool, ...}."""
    stops_payload = _stops_payload(tienda, paradas)

    error_distancia = _validar_distancia_minima(stops_payload)
    if error_distancia:
        return {"valido": False, "error": error_distancia}

    body = {"start_type": "asap", "requester_id": requester_id, "stops": stops_payload}

    response = cabify_client.post("/estimates", json=body)

    if response.status_code == 200:
        opciones = response.json()
        opcion = min(
            opciones, key=lambda op: op.get("total", {}).get("amount", float("inf")), default=None
        )
        if not opcion:
            return {"valido": False, "error": "no_valid_options"}

        return {
            "valido": True,
            "opciones": opciones,
            "cheapest_option": opcion,
            # Distancia REAL de manejo que calcula Cabify (no haversine).
            "distancia": opcion["distance"],
            "duracion": opcion["duration"],
            "eta": opcion["eta"]["formatted"],
            "route_encoded": opcion.get("route"),
            "selected_product_id": opcion["product"]["id"],
        }

    if response.status_code == 422:
        return {"valido": False, "error": response.json().get("message", response.text)}

    if response.status_code == 401:
        return {"valido": False, "error": "token_expirado_persistente"}

    return {"valido": False, "error": response.text}

def crear_journey(requester_id: str, product_id: str, reason: str, rider: dict,
                   tienda: dict, paradas: list[dict]) -> dict:
    stops_payload = _stops_payload(tienda, paradas)
    body = {
        "requester_id": requester_id,
        "product_id": product_id,
        "reason": reason,
        "rider": rider,
        "stops": stops_payload,
    }

    response = cabify_client.post("/journey", json=body)

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code not in (200, 201):
        return {"valido": False, "etapa": "journey", "error": data.get("message", response.text)}

    journey_id = data.get("id", "")

    # El journey ya quedó creado en Cabify aunque esta consulta falle: no dejar
    # que un error de red acá se lleve puesto el journey_id, o el caller pierde
    # la posibilidad de rastrearlo/cancelarlo (ver cancelar_journey).
    try:
        state_response = cabify_client.get(f"/journey/{journey_id}/state", params={"requester_id": requester_id})
        state_data = state_response.json() if state_response.status_code == 200 else state_response.text
    except RuntimeError as e:
        state_data = f"no se pudo consultar el estado tras crear el journey: {e}"

    return {"valido": True, "journey_id": journey_id, "state": state_data}


def cancelar_journey(journey_id: str) -> dict:
    """Cancela un journey activo (POST /journey/{id}/state, sin body).

    Antes de asignar conductor es gratis; después puede haber penalidad si ya
    pasó el periodo de cortesía (lo decide Cabify, no esta función). Devuelve
    409 si el journey ya está terminado o en un estado no cancelable.
    """
    response = cabify_client.post(f"/journey/{journey_id}/state")

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code == 200:
        return {"valido": True, "journey_id": data.get("id", journey_id)}

    return {"valido": False, "error": data.get("message") or data.get("error") or response.text}