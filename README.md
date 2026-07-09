# Sistema de Ruteo Cabify (CVRP)

Optimiza rutas de transporte de empleados con OR-Tools y crea los viajes
directamente en Cabify vía API.

## Estructura

```
cabify_routing/
├── .env #Credenciales de configuración
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
