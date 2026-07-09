"""
Historial de dos etapas del flujo, cada una en su propia tabla (CSV local +
pestaña de Google Sheets):

  - "estimates": una fila por vehículo de la partición ganadora, apenas se
    tiene el /estimates real (válido o no). Responde "¿qué se llegó a cotizar?".
  - "journeys": una fila por intento de creación de journey (creado, fallido,
    omitido por el usuario, o cancelado por rollback). Responde "¿qué se
    llegó a reservar de verdad?".

El CSV es la fuente de verdad: se escribe en el momento en que ocurre cada
evento, no al final de la corrida, así que sobrevive a un crash a mitad de
camino. La sincronización con Google Sheets es best-effort además de eso —
si falla (sin credenciales, sin red, cuota agotada), nunca debe frenar el
flujo real; solo avisa por consola y se sigue con el CSV local.
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from config.settings import config

OUTPUT_DIR = Path("output")

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

COLUMNAS_ESTIMATES = [
    "timestamp", "run_id", "tienda", "dia_semana", "hora_del_dia", "requester_id", "vehiculo",
    "valido", "personas", "producto", "distancia_km", "duracion", "costo_cop",
    "paradas", "paradas_loc", "tienda_loc", "opciones_json", "orden_optimizado",
    "num_particiones_evaluadas", "particiones_costos_json", "error",
]

COLUMNAS_JOURNEYS = [
    "timestamp", "run_id", "tienda", "requester_id", "vehiculo", "journey_id", "estado",
    "personas", "producto", "distancia_km", "duracion", "costo_cop", "paradas",
    "orden_optimizado", "error",
]

_spreadsheet = None
_spreadsheet_listo = False
_worksheets: dict = {}


def _csv_path(nombre_tabla: str) -> Path:
    return OUTPUT_DIR / f"historial_{nombre_tabla}.csv"


def _asegurar_csv(nombre_tabla: str, columnas: list) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    ruta = _csv_path(nombre_tabla)
    if not ruta.exists():
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(columnas)
    return ruta


def _get_spreadsheet():
    """Conecta una sola vez por proceso. Si falla o no hay credenciales,
    no vuelve a intentarlo (para no repetir el mismo error en cada fila)."""
    global _spreadsheet, _spreadsheet_listo
    if _spreadsheet_listo:
        return _spreadsheet
    _spreadsheet_listo = True

    if not (config.GOOGLE_SHEETS_CREDENTIALS and config.GOOGLE_SHEETS_ID):
        return None

    try:
        import gspread
        gc = gspread.service_account(filename=config.GOOGLE_SHEETS_CREDENTIALS)
        _spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_ID)
    except Exception as e:
        print(f" No se pudo conectar con Google Sheets, se seguirá solo con el CSV local: {e}")
        _spreadsheet = None

    return _spreadsheet


def _get_worksheet(nombre_tabla: str, columnas: list):
    """Devuelve la pestaña `nombre_tabla` del spreadsheet, creándola con
    encabezado si no existe todavía. Se cachea por nombre para no repetir
    la búsqueda en cada fila."""
    if nombre_tabla in _worksheets:
        return _worksheets[nombre_tabla]

    libro = _get_spreadsheet()
    if libro is None:
        return None

    try:
        import gspread
        try:
            hoja = libro.worksheet(nombre_tabla)
        except gspread.exceptions.WorksheetNotFound:
            hoja = libro.add_worksheet(title=nombre_tabla, rows=1000, cols=len(columnas))
            hoja.append_row(columnas)
        _worksheets[nombre_tabla] = hoja
    except Exception as e:
        print(f"No se pudo preparar la pestaña '{nombre_tabla}' en Sheets: {e}")
        _worksheets[nombre_tabla] = None

    return _worksheets[nombre_tabla]


def _escribir(nombre_tabla: str, columnas: list, fila: dict):
    ruta = _asegurar_csv(nombre_tabla, columnas)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=columnas).writerow(fila)

    hoja = _get_worksheet(nombre_tabla, columnas)
    if hoja is None:
        return
    try:
        hoja.append_row([str(fila.get(c, "")) for c in columnas])
    except Exception as e:
        print(f"No se pudo escribir en la pestaña '{nombre_tabla}' de Sheets (queda igual en el CSV local): {e}")


def registrar_estimate(
    run_id: str, requester_id: str, vehiculo: int, datos: dict, estimate: dict,
    orden_optimizado: bool = False, tienda: dict | None = None, evaluaciones: list | None = None,
) -> dict:
    """Registra el /estimates real que se llegó a cotizar para este vehículo
    (de la partición ya elegida), sea válido o no.

    Además de lo básico, guarda contexto pensado para un futuro modelo:
    coordenadas (no solo direcciones), día/hora de la corrida, TODAS las
    opciones que devolvió Cabify (no solo la más barata), y el costo de
    TODAS las particiones candidatas comparadas en esta corrida (no solo
    la ganadora) — sin esto no se podría entrenar nada que prediga la
    partición ganadora sin volver a llamar a /estimates para cada una.
    """
    opcion = estimate.get("cheapest_option", {})
    ahora_utc = datetime.now(timezone.utc)
    ahora_local = datetime.now()

    opciones_resumen = [
        {
            "producto": o.get("product", {}).get("name"),
            "costo_cop": o.get("total", {}).get("amount"),
            "distancia_km": round(o["distance"] / 1000, 1) if o.get("distance") else None,
            "duracion": o.get("duration"),
            "eta": o.get("eta", {}).get("formatted"),
        }
        for o in estimate.get("opciones", [])
    ]

    particiones_resumen = [
        {
            "num_vehiculos": ev["num_vehiculos"],
            "costo_total": ev["costo_total"],
            "valido": ev["valido"],
            "motivos_invalidos": ev["motivos_invalidos"],
        }
        for _, ev in (evaluaciones or [])
    ]

    fila = {
        "timestamp": ahora_utc.isoformat(),
        "run_id": run_id,
        "tienda": tienda.get("addr", "") if tienda else "",
        "dia_semana": DIAS_ES[ahora_local.weekday()],
        "hora_del_dia": ahora_local.hour,
        "requester_id": requester_id,
        "vehiculo": vehiculo + 1,
        "valido": estimate.get("valido", False),
        "personas": datos.get("personas", ""),
        "producto": opcion.get("product", {}).get("name", ""),
        "distancia_km": round(estimate["distancia"] / 1000, 1) if estimate.get("distancia") else "",
        "duracion": estimate.get("duracion", ""),
        "costo_cop": opcion.get("total", {}).get("amount", ""),
        "paradas": " → ".join(p["addr"] for p in datos.get("paradas", [])),
        "paradas_loc": json.dumps([p["loc"] for p in datos.get("paradas", [])]),
        "tienda_loc": json.dumps(tienda["loc"]) if tienda else "",
        "opciones_json": json.dumps(opciones_resumen, ensure_ascii=False),
        "orden_optimizado": orden_optimizado,
        "num_particiones_evaluadas": len(evaluaciones) if evaluaciones is not None else "",
        "particiones_costos_json": json.dumps(particiones_resumen, ensure_ascii=False),
        "error": estimate.get("error", ""),
    }
    _escribir("estimates", COLUMNAS_ESTIMATES, fila)
    return fila


def registrar_viaje(
    run_id: str, requester_id: str, vehiculo: int, datos: dict, estimate: dict,
    journey_resultado: dict, orden_optimizado: bool, tienda: dict | None = None,
) -> dict:
    """Registra un intento de journey (creado, fallido u omitido). `estimate`
    es el /estimates ya elegido (costo/distancia real); `journey_resultado`
    es lo que devuelve journeys.crear_journey."""
    opcion = estimate.get("cheapest_option", {})
    fila = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "tienda": tienda.get("addr", "") if tienda else "",
        "requester_id": requester_id,
        "vehiculo": vehiculo + 1,
        "journey_id": journey_resultado.get("journey_id", ""),
        "estado": "creado" if journey_resultado.get("valido") else journey_resultado.get("etapa", "fallido"),
        "personas": datos.get("personas", ""),
        "producto": opcion.get("product", {}).get("name", ""),
        "distancia_km": round(estimate["distancia"] / 1000, 1) if estimate.get("distancia") else "",
        "duracion": estimate.get("duracion", ""),
        "costo_cop": opcion.get("total", {}).get("amount", ""),
        "paradas": " → ".join(p["addr"] for p in datos.get("paradas", [])),
        "orden_optimizado": orden_optimizado,
        "error": journey_resultado.get("error", ""),
    }
    _escribir("journeys", COLUMNAS_JOURNEYS, fila)
    return fila


def registrar_evento(
    run_id: str, requester_id: str, vehiculo: int, journey_id: str, estado: str,
    error: str = "", tienda: dict | None = None,
) -> dict:
    """Registra un evento suelto sobre un journey ya existente (p.ej. una
    cancelación de rollback), como fila nueva — el historial es append-only."""
    fila = {col: "" for col in COLUMNAS_JOURNEYS}
    fila.update({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "tienda": tienda.get("addr", "") if tienda else "",
        "requester_id": requester_id,
        "vehiculo": vehiculo + 1,
        "journey_id": journey_id,
        "estado": estado,
        "error": error,
    })
    _escribir("journeys", COLUMNAS_JOURNEYS, fila)
    return fila
