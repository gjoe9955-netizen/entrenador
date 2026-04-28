import os
import json
import asyncio
import logging
import requests
import base64
import io
import unicodedata
import pandas as pd
from difflib import SequenceMatcher
from scipy.stats import poisson
from datetime import datetime, timedelta, timezone

from openai import OpenAI
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Entorno ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
FOOTBALL_DATA_KEY = os.getenv('API_KEY_FOOTBALL')
ODDS_API_KEY = os.getenv('API_KEY_ODDS')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

OFFSET_JUAREZ = -6
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# --- Diccionario de Mapeo ---
MAPEO_EQUIPOS = {
    "Girona FC": "Girona", "Rayo Vallecano de Madrid": "Vallecano",
    "Villarreal CF": "Villarreal", "Real Oviedo": "Oviedo",
    "RCD Mallorca": "Mallorca", "FC Barcelona": "Barcelona",
    "Deportivo Alavés": "Alaves", "Levante UD": "Levante",
    "Valencia CF": "Valencia", "Real Sociedad de Fútbol": "Sociedad",
    "RC Celta de Vigo": "Celta", "Getafe CF": "Getafe",
    "Athletic Club": "Ath Bilbao", "Sevilla FC": "Sevilla",
    "RCD Espanyol de Barcelona": "Espanol", "Club Atlético de Madrid": "Ath Madrid",
    "Elche CF": "Elche", "Real Betis Balompié": "Betis",
    "Real Madrid CF": "Real Madrid", "CA Osasuna": "Osasuna"
}

# --- Estado Global Dinámico ---
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_samba": [
        "DeepSeek-V3.1", "DeepSeek-V3.1-cb", "DeepSeek-V3.2",
        "Llama-4-Maverick-17B-128E-Instruct", "Meta-Llama-3.3-70B-Instruct"
    ],
    "nodos_groq": [
        "llama-3.3-70b-versatile", "groq/compound-mini",
        "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.1-8b-instant", "groq/compound"
    ]
}

# --- Utilidades ---
def normalizar(texto):
    if not texto:
        return ""
    texto = texto.lower()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    for word in ["fc", "rcd", "sd", "cf", "real", "club", "de", "the"]:
        texto = texto.replace(f" {word} ", " ").replace(f"{word} ", "").replace(f" {word}", "")
    return texto.strip()

def calcular_similitud(a, b):
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]:
        return None

    s_key = os.getenv('SAMBA_KEY') or os.getenv('SAMBANOVA_API_KEY')
    g_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_KEY')

    api_key = s_key if config["api"] == 'SAMBA' else g_key
    base_url = "https://api.sambanova.ai/v1" if config["api"] == 'SAMBA' else "https://api.groq.com/openai/v1"

    # ===== PROMPTS MEJORADOS (ÚNICO CAMBIO) =====
    instrucciones = {
        "estratega": (
            "Eres analista profesional de apuestas deportivas especializado en value betting.\n"
            "Tu función es detectar ventaja matemática real entre modelo y mercado.\n\n"
            "Usa únicamente:\n"
            "- Probabilidad Poisson\n"
            "- Probabilidad final ajustada\n"
            "- Cuotas actuales\n"
            "- Historial H2H entregado\n"
            "- Stake Kelly\n\n"
            "Evalúa:\n"
            "1. Si existe value real.\n"
            "2. Riesgo del pick.\n"
            "3. Si la cuota está inflada o correcta.\n"
            "4. Mejor opción disponible.\n\n"
            "Si edge < 1.5%, recomienda NO BET.\n"
            "Nunca inventes datos.\n"
            "Sé técnico, frío y directo.\n\n"
            "RESPONDE EXACTAMENTE:\n"
            "• ANÁLISIS:\n"
            "máximo 2 líneas.\n\n"
            "• MERCADO:\n"
            "valor o no valor.\n\n"
            "• PREDICCIÓN:\n"
            "Pick final + confianza (Alta/Media/Baja)."
        ),
        "auditor": (
            "Eres gestor profesional de riesgo y bankroll.\n"
            "Evalúa si el stake Kelly sugerido es prudente.\n"
            "Responde SOLO una línea:\n"
            "RIESGO: Bajo / Medio / Alto + motivo técnico.\n"
            "Máximo 20 palabras."
        )
    }
    # ===========================================

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        res = await asyncio.to_thread(
            client.chat.completions.create,
            model=config["nodo"],
            messages=[
                {"role": "system", "content": instrucciones[rol]},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"❌ Error en Nodo {config['api']}: {str(e)[:50]}"

# --- Persistencia GitHub ---
async def guardar_en_github(nuevo_registro=None, historial_completo=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        r = requests.get(url, headers=headers)
        sha = r.json().get('sha') if r.status_code == 200 else None

        if historial_completo is None:
            historial = json.loads(base64.b64decode(r.json()['content']).decode('utf-8')) if r.status_code == 200 else []
            if nuevo_registro:
                historial = [reg for reg in historial if reg['partido'] != nuevo_registro['partido']]
                historial.append(nuevo_registro)
        else:
            historial = historial_completo

        content = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')

        requests.put(
            url,
            headers=headers,
            json={"message": "🤖 Update Historial", "content": content, "sha": sha}
        )

    except Exception as e:
        logging.error(f"Error GitHub: {e}")

# --- APIs de Datos ---
async def obtener_datos_mercado(equipo_l):
    if not ODDS_API_KEY:
        return 1.85, 3.50, 4.00, False

    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'eu',
            'markets': 'h2h',
            'oddsFormat': 'decimal'
        }

        r = await asyncio.to_thread(requests.get, url, params=params, timeout=10)

        if r.status_code == 200:
            data = r.json()
            mejor_match = None
            max_ratio = 0

            for match in data:
                ratio = calcular_similitud(equipo_l, match['home_team'])
                if ratio > max_ratio:
                    max_ratio = ratio
                    mejor_match = match

            if mejor_match and max_ratio > 0.70:
                for bookmaker in mejor_match['bookmakers']:
                    m_data = bookmaker['markets'][0]['outcomes']
                    try:
                        ol = next(o['price'] for o in m_data if o['name'] == mejor_match['home_team'])
                        ov = next(o['price'] for o in m_data if o['name'] == mejor_match['away_team'])
                        oe = next(o['price'] for o in m_data if o['name'] in ['Draw', 'Tie'])
                        return ol, oe, ov, True
                    except:
                        continue

        logging.warning(f"No hallado match para {equipo_l}")

    except Exception as e:
        logging.error(f"Error Odds: {e}")

    return 1.85, 3.50, 4.00, False

async def obtener_h2h_directo(equipo_l, equipo_v):
    URL_CSV = "https://www.football-data.co.uk/mmz4281/2526/SP1.csv"

    try:
        csv_l = MAPEO_EQUIPOS.get(equipo_l, equipo_l)
        csv_v = MAPEO_EQUIPOS.get(equipo_v, equipo_v)

        r = await asyncio.to_thread(requests.get, URL_CSV, timeout=10)
        df = pd.read_csv(io.StringIO(r.text))

        mask = (
            ((df['HomeTeam'] == csv_l) & (df['AwayTeam'] == csv_v)) |
            ((df['HomeTeam'] == csv_v) & (df['AwayTeam'] == csv_l))
        )

        h2h = df[mask]

        if h2h.empty:
            return "Sin H2H.", False

        l, v, e = 0, 0, 0

        for _, row in h2h.iterrows():
            if row['FTR'] == 'H':
                l += 1 if row['HomeTeam'] == csv_l else 0
                v += 1 if row['HomeTeam'] == csv_v else 0
            elif row['FTR'] == 'A':
                v += 1 if row['HomeTeam'] == csv_l else 0
                l += 1 if row['HomeTeam'] == csv_v else 0
            else:
                e += 1

        return f"L {l} | V {v} | E {e}", True

    except:
        return "CSV N/A", False
