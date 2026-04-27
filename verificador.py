import os
import json
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

# Configuración
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
API_KEY_FOOTBALL = os.getenv('FOOTBALL_DATA_KEY')
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"

def obtener_resultados_recientes():
    """Consulta los resultados finalizados de LaLiga"""
    url = "https://api.football-data.org/v4/competitions/PD/matches?status=FINISHED"
    headers = {"X-Auth-Token": API_KEY_FOOTBALL}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json().get('matches', [])
        return []
    except Exception as e:
        print(f"❌ Error al consultar API: {e}")
        return []

def normalizar_nombre(nombre):
    """Limpia nombres para facilitar la coincidencia"""
    if not nombre: return ""
    return nombre.lower().replace("rcd", "").replace("cf", "").replace("real", "").strip()

def actualizar_historial():
    if not GITHUB_TOKEN:
        print("❌ Error: No se encontró GITHUB_TOKEN.")
        return
    
    # 1. Obtener Historial actual desde GitHub
    url_gh = f"https://api.github.com/repos/{REPO_PATH}/contents/{HISTORIAL_FILE}"
    headers_gh = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    try:
        r = requests.get(url_gh, headers=headers_gh)
        if r.status_code != 200:
            print("❌ No se pudo acceder al historial en GitHub.")
            return
        
        file_data = r.json()
        content_b64 = file_data['content'].replace("\n", "")
        historial = json.loads(base64.b64decode(content_b64).decode('utf-8'))
        
        resultados_reales = obtener_resultados_recientes()
        if not resultados_reales:
            print("ℹ️ No se obtuvieron resultados nuevos de la API.")
            return

        cambio = False
        for pick in historial:
            # Solo procesamos los que están pendientes
            if pick.get("resultado_real") == "Pendiente":
                for match in resultados_reales:
                    local_real = match['homeTeam']['name']
                    visit_real = match['awayTeam']['name']
                    
                    # Verificación por coincidencia de nombres normalizados
                    if (normalizar_nombre(local_real) in normalizar_nombre(pick['partido']) and 
                        normalizar_nombre(visit_real) in normalizar_nombre(pick['partido'])):
                        
                        goles_l = match['score']['fullTime']['home']
                        goles_v = match['score']['fullTime']['away']
                        marcador_real = f"{goles_l}-{goles_v}"
                        
                        pick["resultado_real"] = marcador_real
                        pick["estado"] = "REVISADO"
                        
                        # Determinar ganador real para futuras estadísticas
                        if goles_l > goles_v: pick["ganador_real"] = "Local"
                        elif goles_l < goles_v: pick["ganador_real"] = "Visitante"
                        else: pick["ganador_real"] = "Empate"
                        
                        cambio = True
                        print(f"✅ Resultado encontrado: {pick['partido']} -> {marcador_real}")
                        break

        if cambio:
            # CORRECCIÓN DE SINTAXIS AQUÍ: ensure_ascii va dentro de dumps()
            json_str = json.dumps(historial, indent=4, ensure_ascii=False)
            new_content = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
            
            payload = {
                "message": "Auditoría automática de resultados",
                "content": new_content,
                "sha": file_data['sha']
            }
            res_put = requests.put(url_gh, headers=headers_gh, json=payload)
            if res_put.status_code == 200:
                print("🚀 Historial sincronizado con éxito en GitHub.")
            else:
                print(f"❌ Error al subir a GitHub: {res_put.text}")
        else:
            print("ℹ️ No hay nuevos resultados que coincidan con los picks pendientes.")

    except Exception as e:
        print(f"❌ Error general: {e}")

if __name__ == "__main__":
    actualizar_historial()
