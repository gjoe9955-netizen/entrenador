import os
import json
import asyncio
import logging
import requests
import base64
from datetime import datetime
import telebot
from telebot.async_telebot import AsyncTeleBot
from google import generativeai as genai
from scipy.stats import poisson
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Logs ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"

bot = AsyncTeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
config_ia = {"modelo_actual": None}

# --- Funciones de Datos ---

def obtener_datos_poisson():
    try:
        response = requests.get(URL_JSON, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error(f"Error cargando Poisson: {e}")
        return None

def obtener_contexto_gratuito(local, visitante):
    """Obtiene rachas de LaLiga (PD) usando la API Key unificada"""
    if not FOOTBALL_DATA_KEY: return "Sin API Key para rachas."
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    url = "https://api.football-data.org/v4/competitions/PD/matches?status=FINISHED"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        matches = r.json().get('matches', [])
        def extraer_racha(team_name):
            racha = []
            for m in reversed(matches):
                if len(racha) >= 5: break
                h, a = m['homeTeam']['name'], m['awayTeam']['name']
                if team_name in [h, a]:
                    res = m['score']['fullTime']
                    if res['home'] == res['away']: racha.append("E")
                    elif (res['home'] > res['away'] and team_name == h) or (res['away'] > res['home'] and team_name == a):
                        racha.append("G")
                    else: racha.append("P")
            return "-".join(racha) if racha else "Sin datos"
        return f"📊 RACHAS:\n- {local}: {extraer_racha(local)}\n- {visitante}: {extraer_racha(visitante)}"
    except: return "Error obteniendo contexto."

def calcular_probabilidades(local_q, visitante_q):
    data_full = obtener_datos_poisson()
    if not data_full or "LaLiga" not in data_full: return None
    data = data_full["LaLiga"]
    teams = data["teams"]
    
    # Búsqueda flexible de nombres
    m_l = next((t for t in teams if local_q.lower() in t.lower()), None)
    m_v = next((t for t in teams if visitante_q.lower() in t.lower()), None)
    
    if not m_l or not m_v: return None
    
    l_s, v_s = teams[m_l], teams[m_v]
    avg = data["averages"]
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    
    ph, pd, pa = 0, 0, 0
    for x in range(9):
        for y in range(9):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p
    return {"lh": lh, "la": la, "ph": ph, "pd": pd, "pa": pa, "n_l": m_l, "n_v": m_v}

# --- Manejadores ---

@bot.message_handler(commands=['test'])
async def cmd_test(message):
    wait = await bot.reply_to(message, "🔍 Escaneando nodos...")
    try:
        modelos = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                name = m.name.split('/')[-1]
                if any(x in name for x in ['1.5', '2.0', 'flash']): modelos.append(name)
        modelos = sorted(list(set(modelos)))[:6]
        if not modelos: 
            await bot.edit_message_text("❌ No se hallaron nodos.", message.chat.id, wait.message_id)
            return
        markup = InlineKeyboardMarkup()
        for m in modelos: markup.add(InlineKeyboardButton(f"Nodo: {m}", callback_data=f"set_{m}"))
        await bot.delete_message(message.chat.id, wait.message_id)
        await bot.send_message(message.chat.id, "🎯 **MOTOR IA:**", reply_markup=markup, parse_mode='Markdown')
    except: await bot.edit_message_text("❌ Error de conexión.", message.chat.id, wait.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
async def cb_set(call):
    config_ia["modelo_actual"] = call.data.split('_')[1]
    await bot.edit_message_text(f"✅ **ACTIVO:** `{config_ia['modelo_actual']}`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if data and "LaLiga" in data:
        lista = data["LaLiga"].get("equipo_nombres", sorted(data["LaLiga"]["teams"].keys()))
        await bot.reply_to(message, f"📋 **Equipos en el modelo:**\n`{', '.join(lista)}`", parse_mode='Markdown')
    else: await bot.reply_to(message, "❌ Modelo no cargado.")

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not config_ia["modelo_actual"]:
        await bot.reply_to(message, "⚠️ Usa `/test` para activar un nodo."); return
    
    raw = message.text.split(None, 1)[1] if len(message.text.split()) > 1 else ""
    if " vs " not in raw:
        await bot.reply_to(message, "⚠️ Usa: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in raw.split(" vs ")]
    res = calcular_probabilidades(l_q, v_q)
    
    if not res:
        await bot.reply_to(message, "❌ Equipo no reconocido."); return

    sent = await bot.reply_to(message, f"📈 Analizando con `{config_ia['modelo_actual']}`...")
    contexto = obtener_contexto_gratuito(res['n_l'], res['n_v'])
    
    try:
        model = genai.GenerativeModel(config_ia["modelo_actual"])
        prompt = f"Analiza como experto en Value Betting:\nPARTIDO: {res['n_l']} vs {res['n_v']}\nPOISSON: L {res['ph']*100:.1f}%, E {res['pd']*100:.1f}%, V {res['pa']*100:.1f}%\n{contexto}\n\nResponde con este formato:\n🔥 ANÁLISIS: [Breve]\n🎯 PICK: [Mercado]\n💰 CUOTA SUGERIDA: [X.XX]\n⚠️ CONFIANZA: [Nivel]\nPICK_RESUMEN: [4 palabras]"
        
        response = await asyncio.to_thread(model.generate_content, prompt)
        await bot.edit_message_text(response.text, message.chat.id, sent.message_id)
    except Exception as e:
        await bot.edit_message_text(f"❌ Error IA: {str(e)[:50]}", message.chat.id, sent.message_id)

async def main():
    logger.info("🚀 Bot iniciado.")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
