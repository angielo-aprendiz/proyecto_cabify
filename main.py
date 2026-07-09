"""
Punto de entrada del sistema de ruteo + Cabify.
Ejecutar con: python main.py
"""
import math
import re
import sys
import uuid

sys.stdout.reconfigure(encoding="utf-8")

from config.settings import config
from src import users, journeys, comparador, historial
from src.optimizer import generar_candidatos, filtrar_mejores_candidatos
from src.map_utils import construir_mapa

OUTPUT_DIR = "output"

# Cada tienda ya trae resuelto qué empleados le tocan en este turno (la
# rotación por demanda se decide antes, fuera de este sistema) — acá solo
# se procesa una lista de tiendas, cada una con su propio grupo de paradas.


#  Estructura para pasar datos 
    # {
    #     "tienda": {"addr": "...", "city": "Bogota", "country": "CO", "loc": [..., ...]},
    #     "paradas_raw": [...],
    #     "rider": {
    #         "name": "Prueba cuenta 2",
    #         "mobile": {"mobile_num": "3XXXXXXXXX", "mobile_cc": "57"},
    #     },
    # },
    #Ecalabilidad, traer los turnos de cada tienda y elegir los empleados que estarán despues de las 11, COORDENADAS OBLIGATORIAS
TIENDAS = [
    {
        "tienda": {
            "addr": "Chapinero", "city": "Bogota", "country": "CO",
            "loc": [4.641589164733887, -74.06221771240234],
        },
        "paradas_raw": [
            {"addr": "Tv. 3C #49 - 77, Bogotá", "personas": 1, "city": "Bogota", "country": "CO", "loc": [4.637097,-74.062218]},
            {"addr": "Santa Fé, Bogotá", "personas": 1, "city": "Bogota", "country": "CO", "loc": [4.632605,-74.062218]},
        ],
        # Sin "rider" -> usa el rider_default de .env (RIDER_NOMBRE/RIDER_CELULAR/RIDER_CC).
    },
    {
        "tienda": {
            "addr": "Tesoro", "city": "Medellín", "country": "CO",
            "loc": [6.199906826019287, -75.56246185302734],
        },
        "paradas_raw": [
            {"addr": "Cra. 29a #320, El Poblado, Medellín, El Poblado, Medellín, Antioquia", "personas": 1, "city": "Medellín", "country": "CO", "loc": [6.202448, -75.559907]},
            {"addr": "Cl. 1 #29-300, El Poblado, Medellín, El Poblado, Medellín, Antioquia", "personas": 1, "city": "Medellín", "country": "CO", "loc": [6.205624, -75.556716]},
        ],
        "rider": {
            "name": "prueba API 2",
            "mobile": {"mobile_num": "3227689794", "mobile_cc": "57"},
        },
        "requester":"Angie Lorena Jiménez Porras"
        # Sin "requester" -> usa el requester_default (ver main()).
    },
]
def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")


def procesar_tienda(run_id: str, requester_id: str, rider: dict, tienda: dict, paradas_raw: list[dict]):
    print(f"\n{'#'*65}\nTIENDA: {tienda['addr']}\n{'#'*65}")

    total_personas = sum(p["personas"] for p in paradas_raw)
    print(f"Empleados a recoger: {total_personas}")
    print(f"Vehículos mínimos: {math.ceil(total_personas / config.MAX_PERSONAS_POR_VEHICULO)}")

    # ── 3. Generar varias agrupaciones candidatas de vehículos ─────────
    # (haversine solo se usa aquí como heurística para agrupar/ordenar;
    # NO decide costo ni validez — eso se hace abajo con /estimates real)
    candidatos = generar_candidatos(tienda, paradas_raw, config)
    print(f"\nSe generaron {len(candidatos)} agrupación(es) candidata(s).")

    # Antes de gastar llamadas reales, nos quedamos solo con las candidatas
    # más prometedoras según un costo-proxy gratis (haversine + costo fijo
    # por vehículo) — ver `optimizer.filtrar_mejores_candidatos`.
    candidatos_a_evaluar = filtrar_mejores_candidatos(tienda, candidatos, config)
    print(f"Se evaluarán con /estimates real las {len(candidatos_a_evaluar)} más prometedoras "
          f"de {len(candidatos)} (según distancia estimada), para ahorrar llamadas a la API.")

    # ── 4. Evaluar cada candidata con costo y distancia REALES de /estimates,
    #      y elegir la más barata entre las válidas ─────────────────────
    print("Consultando /estimates para cada candidata (esto hace varias llamadas a la API)...")
    mejor_particion, mejor_evaluacion, evaluaciones = comparador.elegir_mejor_particion(
        requester_id, tienda, candidatos_a_evaluar, config
    )

    print(f"\n{'='*65}\nCOMPARACIÓN DE AGRUPACIONES (costo real vía /estimates)\n{'='*65}")
    for i, (particion, evaluacion) in enumerate(evaluaciones):
        if evaluacion["valido"]:
            print(f"Opción {i+1}: {evaluacion['num_vehiculos']} vehículo(s) — "
                  f"{evaluacion['costo_total']:,} COP")
        else:
            razones = "; ".join(evaluacion["motivos_invalidos"])
            print(f"Opción {i+1}: {evaluacion['num_vehiculos']} vehículo(s) —  {razones}")

    if mejor_particion is None:
        print(f"\nNinguna agrupación de vehículos produjo estimates válidos para '{tienda['addr']}'. Se omite esta tienda.")
        return

    print(f"\nMejor opción: {mejor_evaluacion['num_vehiculos']} vehículo(s) — "
          f"{mejor_evaluacion['costo_total']:,} COP (elegida por costo total más bajo)")

    # ── 4.5. Dentro de la partición elegida, probar órdenes alternativos de
    #        paradas por vehículo contra /estimates real y quedarse con el
    #        más barato (no mueve paradas entre vehículos) ──────────────
    print("\nOptimizando orden de paradas dentro de cada vehículo (contra /estimates real)...")
    mejor_evaluacion = comparador.optimizar_orden_particion(
        requester_id, tienda, mejor_particion, mejor_evaluacion, config
    )
    mejoras_orden = mejor_evaluacion["mejoras_orden"]
    if mejoras_orden:
        for v, (antes, despues) in mejoras_orden.items():
            print(f"  Vehículo {v + 1}: {antes:,} → {despues:,} COP (mejor orden encontrado)")
        print(f"  Costo total tras optimizar orden: {mejor_evaluacion['costo_total']:,} COP")
    else:
        print("  El orden por vecino más cercano ya era el más barato en todos los vehículos.")

    rutas_por_vehiculo = mejor_particion
    resultados_estimates = mejor_evaluacion["estimates"]

    # ── 4.6. Historial de lo cotizado: una fila por vehículo de la partición
    #        elegida, se haya llegado a reservar o no ────────────────────
    for v, estimate in resultados_estimates.items():
        historial.registrar_estimate(
            run_id, requester_id, v, rutas_por_vehiculo[v], estimate, v in mejoras_orden,
            tienda=tienda, evaluaciones=evaluaciones,
        )

    # ── 5. Mapa ───────────────────────────────────────────────
    mapa = construir_mapa(tienda, rutas_por_vehiculo, resultados_estimates)
    mapa_path = f"{OUTPUT_DIR}/rutas_{_slug(tienda['addr'])}.html"
    mapa.save(mapa_path)
    print(f"\n Mapa guardado en {mapa_path}")

    # ── 6. Resumen y confirmación ────────────────────────────
    viajes_validos = {v: r for v, r in resultados_estimates.items() if r.get("valido")}
    if not viajes_validos:
        print(f"No hay estimates válidos para '{tienda['addr']}'. No se crearán journeys para esta tienda.")
        return

    print(f"\n{'='*65}\nRESUMEN DE VIAJES A ENVIAR ({len(viajes_validos)} vehículo(s)) — {tienda['addr']}\n{'='*65}")
    total_aprox = 0
    for v, r in viajes_validos.items():
        datos = rutas_por_vehiculo[v]
        opcion = r["cheapest_option"]
        nombres = " → ".join(p["addr"] for p in datos["paradas"])
        print(f"V{v+1} | {datos['personas']} pers. | {r['distancia']/1000:.1f} km | "
              f"{opcion['product']['name']} | {opcion['total']['amount']:,} COP")
        print(f"   Ruta: {nombres}")
        total_aprox += opcion["total"]["amount"]
    print(f"\nCOSTO TOTAL ESTIMADO: {total_aprox:,} COP\n")

    confirmacion = input(
        f"¿Confirmas el envío de TODOS los viajes de '{tienda['addr']}'? [s = sí / n = uno a uno / x = cancelar]: "
    ).strip().lower()

    if confirmacion == "x":
        print("Envío cancelado para esta tienda.")
        return

    # ── 7. Crear journeys (con rollback si algo falla a mitad de camino) ──
    reason = "pruebas api"

    journeys_creados = []  # (vehiculo, journey_id), para rollback si algo sale mal
    resultados_journey = {}

    try:
        for v, r in viajes_validos.items():
            datos = rutas_por_vehiculo[v]

            if confirmacion == "n":
                ok = input(f"\nVehículo {v+1} | {datos['personas']} persona(s) — ¿Enviar? [s/n]: ").strip().lower()
                if ok != "s":
                    resultado_omitido = {"valido": False, "etapa": "omitido_por_usuario"}
                    resultados_journey[v] = resultado_omitido
                    historial.registrar_viaje(
                        run_id, requester_id, v, datos, r, resultado_omitido, v in mejoras_orden, tienda=tienda
                    )
                    continue

            resultado = journeys.crear_journey(
                requester_id, r["selected_product_id"], reason, rider, tienda, datos["paradas"]
            )
            resultados_journey[v] = resultado
            historial.registrar_viaje(
                run_id, requester_id, v, datos, r, resultado, v in mejoras_orden, tienda=tienda
            )

            if resultado["valido"]:
                journeys_creados.append((v, resultado["journey_id"]))
                print(f" Vehículo -> {v+1} — journey {resultado['journey_id']}")
            else:
                print(f" Vehículo -> {v+1} — {resultado.get('error')}")

    except Exception as e:
        print(f"\n !! Error inesperado durante la creación de journeys: {e}")
        print("Iniciando rollback de journeys ya creados...")
        for v, jid in journeys_creados:
            resultado_cancel = journeys.cancelar_journey(jid)
            historial.registrar_evento(
                run_id, requester_id, v, jid, "cancelado_rollback", str(resultado_cancel), tienda=tienda
            )
            print(f"  Cancelado {jid}: {resultado_cancel}")
        raise

    print(f"\n{'='*55}\nRESULTADO FINAL — {tienda['addr']}\n{'='*55}")
    for v, res in resultados_journey.items():
        if res.get("valido"):
            print(f"Vehículo {v+1}: ID {res['journey_id']}")
        else:
            print(f"Vehículo {v+1}: -> {res.get('etapa', '?')} — {res.get('error', '')}")


def main():
    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]

    # ── 1. Usuarios ────────────────────────────────────────
    all_users = users.cargar_usuarios()
    requester_default_query = "Duban Hernandez Alvarez" #debe quedar vacio ya que al mandar la prueba real todo lo que no se le asigne un requester se va hacia esa cuenta

    rider_default = {
        "name": config.RIDER_NOMBRE,
        "mobile": {"mobile_num": config.RIDER_CELULAR, "mobile_cc": config.RIDER_CC},
    }

    # ── 2-7. Una tienda a la vez, cada una con su propio grupo de paradas ──
    # Si un grupo trae su propio "rider" (para probar con otro nombre/celular),
    # se usa ese; si no, cae al rider_default de .env. Lo mismo para
    # "requester": si la tienda no trae uno propio, cae al requester_default_query.
    # Se cachea por query para no volver a pedir el requester_id si dos tiendas
    # usan el mismo usuario
    #Se procesa todo por tienda para evitar hacer muchas peticiones al servidor y hacer caer al sistema 
    requester_ids_cache: dict[str, str] = {}
    for grupo in TIENDAS:
        rider = grupo.get("rider", rider_default)
        requester_query = grupo.get("requester", requester_default_query)

        if requester_query not in requester_ids_cache:
            requester_id = users.seleccionar_usuario(all_users, requester_query)
            if not requester_id:
                print(f"NO SE ENCONTRÓ UN RIDER VALDO ->'{requester_query}'. Se omite todo el viaje '{grupo['tienda']['addr']}'.")
                continue
            requester_ids_cache[requester_query] = requester_id
        requester_id = requester_ids_cache[requester_query]

        procesar_tienda(run_id, requester_id, rider, grupo["tienda"], grupo["paradas_raw"])
if __name__ == "__main__":
    main()
