"""
Autenticación contra la API de Cabify, con refresco automático de token
cuando expira (HTTP 401).
"""
import requests
from config.settings import config


class CabifyAuth:
    def __init__(self):
        self._token: str | None = None

    def _fetch_token(self) -> str:
        try:
            response = requests.post(
                config.AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": config.CABIFY_CLIENT_ID,
                    "client_secret": config.CABIFY_CLIENT_SECRET,
                },
                timeout=20,
            )
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"No se pudo conectar con Cabify para autenticar: {e}") from e

        if response.status_code != 200:
            raise RuntimeError(f"Autenticación fallida: {response.text}")

        self._token = response.json()["access_token"]
        return self._token

    @property
    def token(self) -> str:
        if self._token is None:
            self._fetch_token()
        return self._token

    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def refresh(self) -> dict:
        """Fuerza un nuevo token y devuelve headers actualizados."""
        self._fetch_token()
        return self.headers()


auth = CabifyAuth()
