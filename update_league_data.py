import requests
import json
import os

# Configuración - UNIFICADO con tu archivo .yml
API_KEY = os.getenv("API_KEY_FOOTBALL") 
BASE_URL = "https://api.football-data.org/v4"
COMPETITION = "PD" # Primera División de España
FILE_NAME = "liga_data.json"

def fetch_data():
    headers = {'X-Auth-Token': API_KEY}
    
    # 1. Obtener Tabla de Posiciones (Standings)
    print("Obteniendo standings...")
    standings_res = requests.get(f"{BASE_URL}/competitions/{COMPETITION}/standings", headers=headers)
    
    # 2. Obtener Resultados de la Temporada (Matches)
    print("Obteniendo resultados de partidos...")
    matches_res = requests.get(f"{BASE_URL}/competitions/{COMPETITION}/matches", headers=headers)
    
    if standings_res.status_code == 200 and matches_res.status_code == 200:
        data = {
            "last_updated": matches_res.json().get("competition", {}).get("lastUpdated"),
            "standings": standings_res.json().get("standings", [{}])[0].get("table", []),
            "matches": matches_res.json().get("matches", [])
        }
        
        # Guardamos la información en el JSON
        with open(FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"✅ {FILE_NAME} actualizado con éxito.")
    else:
        print(f"❌ Error al consultar la API. Status: {standings_res.status_code} / {matches_res.status_code}")
        # Imprime la respuesta para saber por qué falló (si es por plan gratuito o permisos)
        print(f"Detalle Standings: {standings_res.text[:100]}") 

if __name__ == "__main__":
    # Verificación de la variable de entorno
    if not API_KEY:
        print("❌ Error: No se encontró la variable API_KEY_FOOTBALL en el entorno.")
    else:
        fetch_data()
