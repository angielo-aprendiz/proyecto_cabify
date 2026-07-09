"""
Carga de configuración y credenciales desde variables de entorno (.env).
Nunca poner credenciales directamente en este archivo ni en ningún .py.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Busca el .env en la raíz del proyecto, sin importar desde dónde se ejecute
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno '{var_name}'. "
            f"Copia .env.example a .env y completa tus credenciales."
        )
    return value


class Config:
    CABIFY_CLIENT_ID: str = _require_env("CABIFY_CLIENT_ID")
    CABIFY_CLIENT_SECRET: str = _require_env("CABIFY_CLIENT_SECRET")
    BASE_URL: str = os.environ.get("CABIFY_BASE_URL", "https://cabify.com")
    AUTH_URL: str = f"{BASE_URL}/auth/api/authorization"
    API_URL: str = f"{BASE_URL}/api/v4"

    RIDER_NOMBRE: str = os.environ.get("RIDER_NOMBRE", "Prueba optimizacion de viajes")
    RIDER_CELULAR: str = os.environ.get("RIDER_CELULAR", "")
    RIDER_CC: str = os.environ.get("RIDER_CC", "57")

    # Parámetros del optimizador (puedes moverlos también a .env si quieres tunearlos sin tocar código)
    MAX_PERSONAS_POR_VEHICULO = 4
    NUM_VEHICULOS_MAX = 5
    COSTO_FIJO_VEHICULO = 5_000
    # Cabify rechaza (422) journeys/estimates con paradas demasiado próximas entre sí.
    # Se valida en journeys.py antes de llamar a /estimates y /journey.
    DISTANCIA_MIN_ENTRE_PARADAS_M = 200

    # Límite de distancia real de manejo (la que devuelve /estimates, no haversine)
    # por vehículo. Se valida en comparador.py: una partición con algún vehículo
    # por encima de esto se descarta como inválida.
    DISTANCIA_MAX_POR_VEHICULO = 30_000

    # Por encima de este número de paradas por vehículo, probar todos los
    # órdenes posibles (N!) contra /estimates sería demasiadas llamadas a la
    # API, así que se usa 2-opt sobre haversine en su lugar (una sola llamada
    # de verificación en vez de N!).
    # Con 4 esto significaba hasta 4! = 24 llamadas por vehículo solo para
    # optimizar el orden; con 60 tiendas eso escala mal. En 2, el peor caso
    # es 2! = 2 (una sola llamada extra) y de ahí para arriba se usa 2-opt
    # (1 llamada de verificación), que en rutas de pocas paradas ya da un
    # orden muy cercano al óptimo.
    MAX_PARADAS_ORDEN_EXACTO = 2

    # Cuántas particiones candidatas (de las que genera `generar_candidatos`)
    # se evalúan realmente contra /estimates. `optimizer.filtrar_mejores_candidatos`
    # rankea las candidatas por un costo-proxy gratis (haversine + costo fijo
    # por vehículo) y solo las `TOP_N_CANDIDATOS` mejores llegan a gastar
    # llamadas reales a la API. Subir este número evalúa más opciones (mejor
    # calidad, más llamadas); bajarlo ahorra llamadas pero puede perderse la
    # partición realmente más barata si el proxy se equivoca de ranking.
    TOP_N_CANDIDATOS = 3

    # Historial de viajes: siempre se guarda en output/historial_viajes.csv.
    # Si además se configuran estas dos variables, cada fila se sincroniza
    # también con Google Sheets (service account de Google Cloud con acceso
    # a la hoja). Si se dejan vacías, el historial queda solo en el CSV local.
    GOOGLE_SHEETS_CREDENTIALS: str = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
    GOOGLE_SHEETS_ID: str = os.environ.get("GOOGLE_SHEETS_ID", "")


config = Config()
