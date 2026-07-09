# Sistema de Ruteo Cabify (CVRP)

Optimiza rutas de transporte de empleados con OR-Tools y crea los viajes
directamente en Cabify vía API.

## Estructura

```
cabify_routing/
├── .env.example       # plantilla de credenciales (copiar a .env)
├── .gitignore          # protege .env y archivos generados
├── requirements.txt
├── main.py             # punto de entrada
├── config/
│   └── settings.py     # carga credenciales desde .env
├── src/
│   ├── auth.py          # token + refresco automático
│   ├── cabify_client.py # wrapper HTTP con reintento en 401
│   ├── users.py         # carga/búsqueda de usuarios
│   ├── optimizer.py     # genera varias agrupaciones candidatas (OR-Tools, clustering, etc.)
│   ├── comparador.py    # evalúa candidatas con costo/distancia REALES de /estimates y elige la mejor
│   ├── journeys.py      # estimates, journeys, rollback
│   ├── map_utils.py     # mapa folium
│   └── polyline_utils.py
└── output/              # mapas generados (no se sube a git)
```

## Instalación

```bash
cd cabify_routing
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuración de credenciales

```bash
cp .env.example .env
```

Edita `.env` y pon tus credenciales reales de Cabify. Este archivo **nunca**
se sube a git (ya está en `.gitignore`).

**Importante**: si las credenciales que estaban en el notebook de Colab
quedaron expuestas en texto plano en algún lugar (chats, repos, capturas),
rótalas en el panel de Cabify antes de poner este sistema en producción.

## Uso

```bash
python main.py
```

El mapa con las rutas se guarda en `output/rutas.html` y se puede abrir
directamente en el navegador.

## Pendientes según el plan de mejoras

- [x] Credenciales fuera del código (`.env`)
- [x] Refresco automático de token en 401
- [x] Rollback de journeys si falla la creación a mitad del lote
- [x] Distancias reales de manejo: el límite de km (`DISTANCIA_MAX_POR_VEHICULO`)
      y el costo total ya no se calculan con Haversine en línea recta, sino
      con la distancia y el precio reales que devuelve `/estimates` para cada
      agrupación candidata (ver `src/comparador.py`). Haversine solo se usa
      como heurística barata dentro de `optimizer.py` para armar/ordenar las
      agrupaciones candidatas, nunca para decidir costo o validez final.
- [x] Comparar varias agrupaciones antes de elegir: `optimizer.generar_candidatos`
      arma varias particiones posibles (un solo vehículo con todas las paradas,
      distintas agrupaciones de OR-Tools, clustering geográfico con distinto
      número de vehículos, y el caso extremo de un vehículo por parada).
      `comparador.elegir_mejor_particion` le pide un `/estimates` real a cada
      una y se queda con la de menor costo total entre las válidas — así se
      evita el caso en que dividir en varios vehículos salga más caro que un
      solo viaje con varias paradas.
      Nota de costo: esto implica más llamadas a `/estimates` por corrida
      (una por vehículo y por candidata). Si el volumen de paradas crece mucho,
      puede valer la pena limitar cuántas candidatas se generan.
- [ ] Tráfico en tiempo real / predicción de demanda
- [ ] El orden final de paradas que arma este sistema (`_ordenar_por_vecino_cercano`)
      sigue siendo solo una sugerencia para el payload de `/estimates`; Cabify
      puede reordenar las paradas al calcular la ruta real.
