"""
Wrapper de requests que reintenta automáticamente con un token nuevo
si la API responde 401 (token expirado), y con backoff ante timeouts o
errores de conexión transitorios (la red hacia cabify.com puede colgarse
un momento sin que sea un fallo real de la API).
"""
import time
import requests
from src.auth import auth
from config.settings import config

MAX_INTENTOS_RED = 3
BACKOFF_BASE_SEGUNDOS = 2


def _enviar_con_reintentos(method: str, url: str, headers: dict, **kwargs) -> requests.Response:
    ultimo_error = None
    for intento in range(1, MAX_INTENTOS_RED + 1):
        try:
            return requests.request(method, url, headers=headers, timeout=20, **kwargs)
        except requests.exceptions.RequestException as e:
            ultimo_error = e
            if intento < MAX_INTENTOS_RED:
                espera = BACKOFF_BASE_SEGUNDOS * intento
                print(f" Fallo de red hacia Cabify (intento {intento}/{MAX_INTENTOS_RED}, {method} {url}): {e}. Reintentando en {espera}s...")
                time.sleep(espera)

    raise RuntimeError(
        f"No se pudo conectar con Cabify tras {MAX_INTENTOS_RED} intentos ({method} {url}): {ultimo_error}"
    ) from ultimo_error


def _request(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{config.API_URL}{path}"

    response = _enviar_con_reintentos(method, url, auth.headers(), **kwargs)

    if response.status_code == 401:
        print("Token expirado — renovando...")
        new_headers = auth.refresh()
        response = _enviar_con_reintentos(method, url, new_headers, **kwargs)

    return response


def get(path: str, **kwargs) -> requests.Response:
    return _request("GET", path, **kwargs)


def post(path: str, **kwargs) -> requests.Response:
    return _request("POST", path, **kwargs)
