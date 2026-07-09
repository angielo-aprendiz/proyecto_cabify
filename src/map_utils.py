"""Generación del mapa folium con rutas y paradas."""
import folium
from src.polyline_utils import decode_polyline

COLORES = ["#E63946", "#2A9D8F", "#7719cf", "#19bf42", "#264653"]


def construir_mapa(tienda: dict, rutas_por_vehiculo: dict, resultados_estimates: dict):
    mapa = folium.Map(location=tienda["loc"], zoom_start=13)

    folium.Marker(
        location=tienda["loc"],
        tooltip="Tienda — punto de partida",
        icon=folium.Icon(color="black", icon="home", prefix="fa"),
    ).add_to(mapa)

    for v, datos in rutas_por_vehiculo.items():
        color = COLORES[v % len(COLORES)]
        resultado = resultados_estimates.get(v, {})

        if resultado.get("valido"):
            coords_ruta = decode_polyline(resultado.get("route_encoded"))
            if coords_ruta:
                folium.PolyLine(
                    locations=coords_ruta, color=color, weight=4, opacity=0.8,
                    tooltip=f"Vehículo {v+1} — {datos['personas']} empleados",
                ).add_to(mapa)

        for i, parada in enumerate(datos["paradas"]):
            orden = i + 1
            folium.Marker(
                location=parada["loc"],
                tooltip=f"V{v+1} · Parada {orden}/{datos['personas']} — {parada['addr']}",
                icon=folium.DivIcon(
                    html=f"""
                        <div style="
                            background:{color};color:white;border-radius:50%;
                            width:32px;height:32px;display:flex;
                            align-items:center;justify-content:center;
                            font-weight:bold;font-size:14px;
                            border:2px solid white;
                            box-shadow:0 2px 5px rgba(0,0,0,0.5);">
                            {orden}
                        </div>""",
                    icon_size=(32, 32),
                    icon_anchor=(16, 16),
                ),
            ).add_to(mapa)

    return mapa
