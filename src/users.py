"""
Carga y búsqueda de usuarios de Cabify.
"""
from src import cabify_client


def cargar_usuarios() -> list[dict]:
    all_users = []
    page, per = 1, 100

    while True:
        response = cabify_client.get(f"/users?page={page}&per={per}")
        print(f"➡️  GET página {page} — STATUS: {response.status_code}")

        if response.status_code != 200:
            raise RuntimeError(f"Error al obtener usuarios: {response.text}")

        data = response.json()
        users = data.get("data", [])
        total_pages = data.get("pages", data.get("total_pages", 1))

        if not users:
            break

        all_users.extend(users)

        if page >= total_pages:
            break
        page += 1

    print(f" TOTAL USUARIOS CARGADOS: {len(all_users)}")
    return all_users


def buscar_usuario(all_users: list[dict], query: str) -> list[dict]:
    query_lower = query.strip().lower()
    resultados = [
        u for u in all_users
        if query_lower in f"{u['name']} {u.get('surname', '')}".strip().lower()
        or query_lower in (u.get("employee_code") or "").lower()
        or query_lower in u["id"].lower()
    ]

    if not resultados:
        print(f"No se encontró ningún usuario con '{query}'")
    return resultados


def seleccionar_usuario(all_users: list[dict], query: str) -> str | None:
    """Devuelve el REQUESTER_ID del usuario seleccionado, o None."""
    resultados = buscar_usuario(all_users, query)
    if not resultados:
        return None

    if len(resultados) == 1:
        usuario = resultados[0]
    else:
        print(f"\nResultados para '{query}': {len(resultados)} encontrado(s)")
        for i, u in enumerate(resultados, 1):
            nombre = f"{u['name']} {u.get('surname', '')}".strip()
            print(f"{i:<3} {nombre:<30} {u.get('employee_code', 'N/A'):<15} {u['id']}")
        try:
            opcion = int(input(f"Elige el número (1-{len(resultados)}): "))
            usuario = resultados[opcion - 1]
        except (ValueError, IndexError):
            print("Selección inválida")
            return None

    nombre = f"{usuario['name']} {usuario.get('surname', '')}".strip()
    print(f" REQUESTER_ID asignado -> {usuario['id']} — {nombre}")
    return usuario["id"]
