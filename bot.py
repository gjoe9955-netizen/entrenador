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

# --- FUNCIONES DE SOPORTE ---

async def obtener_modelos_reales(api_key):
    try:
        genai.configure(api_key=api_key)
        aptos = []
        for m in genai.list_models():
            nombre = m.name.split('/')[-1]
            if 'generateContent' in m.supported_generation_methods:
                if any(x in nombre.lower() for x in ['flash', 'pro', '1.5', '2.0']):
                    try:
                        test_model = genai.GenerativeModel(nombre)
                        await asyncio.to_thread(test_model.generate_content, "hi", generation_config={"max_output_tokens": 1})
                        aptos.append(nombre)
                    except: continue
        aptos.sort(reverse=True)
        return aptos[:6]
    except: return []

def obtener_datos_poisson():
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        response = requests.get(URL_JSON, headers=headers, timeout=10)
        return response.json() if response.status_code == 200 else None
    except: return None

# --- COMANDOS FOOTBALL DATA ---

@bot.message_handler(commands=['tabla'])
async def cmd_tabla(message):
    if not FOOTBALL_DATA_KEY: return
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r = requests.get("https://api.football-data.org/v4/competitions/PD/standings", headers=headers, timeout=10)
        if r.status_code == 200:
            tabla = r.json()['standings'][0]['table']
            res = "🏆 **TOP 10 LALIGA:**\n\n"
            for t in tabla[:10]:
                res += f"{t['position']}. **{t['team']['shortName']}** - {t['points']} pts\n"
            await bot.reply_to(message, res, parse_mode='Markdown')
    except: pass

@bot.message_handler(commands=['goleadores'])
async def cmd_goleadores(message):
    if not FOOTBALL_DATA_KEY: return
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r = requests.get("https://api.football-data.org/v4/competitions/PD/scorers", headers=headers, timeout=10)
        if r.status_code == 200:
            scorers = r.json()['scorers']
            res = "⚽ **MÁXIMOS GOLEADORES:**\n\n"
            for s in scorers[:10]:
                res += f"• **{s['player']['name']}** ({s['team']['shortName']}): {s['goals']} goles\n"
            await bot.reply_to(message, res, parse_mode='Markdown')
    except: pass

@bot.message_handler(commands=['proximos'])
async def cmd_proximos(message):
    if not FOOTBALL_DATA_KEY: return
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r = requests.get("https://api.football-data.org/v4/competitions/PD/matches", headers=headers, params={"status": "SCHEDULED"}, timeout=10)
        if r.status_code == 200:
            matches = r.json()['matches']
            res = "📅 **PRÓXIMOS PARTIDOS:**\n\n"
            for m in matches[:8]:
                fecha = datetime.fromisoformat(m['utcDate'].replace('Z', '')).strftime('%d/%m %H:%M')
                res += f"• `{fecha}`: {m['homeTeam']['shortName']} vs {m['awayTeam']['shortName']}\n"
            await bot.reply_to(message, res, parse_mode='Markdown')
    except: pass

# --- COMANDOS CORE ---

@bot.message_handler(commands=['start', 'help'])
async def cmd_help(message):
    help_text = (
        "⚽ **SISTEMA DE PREDICCIÓN Y VALOR**\n\n"
        "🤖 **CONFIGURACIÓN IA:**\n"
        "🔍 `/test` - Escanea nodos de IA y permite seleccionar el motor activo (Flash/Pro).\n"
        "🧠 `/modelo` - Muestra qué nodo de IA está configurado actualmente.\n\n"
        "📈 **ANÁLISIS Y PREDICCIÓN:**\n"
        "🎯 `/pronostico Local vs Visitante` - Genera análisis completo cruzando Poisson, Rachas y Cuotas.\n"
        "📋 `/equipos` - Muestra la lista de equipos soportados por el modelo de datos local.\n"
        "📜 `/historial` - Muestra los últimos 5 pronósticos generados.\n\n"
        "📊 **DATOS EN TIEMPO REAL (LALIGA):**\n"
        "🏆 `/tabla` - Muestra el Top 10 de la clasificación actual.\n"
        "⚽ `/goleadores` - Lista los 10 jugadores con más goles actualmente.\n"
        "📅 `/proximos` - Muestra los siguientes 8 partidos programados.\n\n"
        "⚠️ *Nota: Escribe los equipos tal como aparecen en /equipos para evitar errores.*"
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if not data:
        await bot.reply_to(message, "❌ Error al conectar con GitHub."); return
    try:
        liga_key = next(iter(data))
        equipos = sorted(data[liga_key]['teams'].keys())
        lista = ", ".join([f"`{e}`" for e in equipos])
        await bot.reply_to(message, f"📋 **EQUIPOS ({liga_key}):**\n\n{lista}", parse_mode='Markdown')
    except:
        await bot.reply_to(message, "❌ Estructura de JSON no compatible.")

@bot.message_handler(commands=['test'])
async def cmd_test(message):
    wait = await bot.reply_to(message, "🔍 Escaneando nodos disponibles...")
    modelos = await obtener_modelos_reales(GEMINI_KEY)
    await bot.delete_message(message.chat.id, wait.message_id)
    if not modelos:
        await bot.reply_to(message, "❌ No hay nodos activos."); return
    markup = InlineKeyboardMarkup()
    for m in modelos:
        markup.add(InlineKeyboardButton(f"Nodo: {m}", callback_data=f"set_{m}"))
    await bot.send_message(message.chat.id, "🎯 **SELECCIONE MOTOR IA:**", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
async def cb_set_model(call):
    config_ia["modelo_actual"] = call.data.split('_')[1]
    await bot.edit_message_text(f"✅ **NODO SELECCIONADO:** `{config_ia['modelo_actual']}`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not config_ia["modelo_actual"]:
        await bot.reply_to(message, "⚠️ Primero selecciona un nodo con `/test`."); return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Usa: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    full_data = obtener_datos_poisson()
    if not full_data: return

    liga_key = next(iter(full_data))
    data_liga = full_data[liga_key]
    m_l = next((t for t in data_liga['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
    m_v = next((t for t in data_liga['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)
    
    if not m_l or not m_v:
        await bot.reply_to(message, "❌ Equipo no hallado."); return

    l_s, v_s = data_liga['teams'][m_l], data_liga['teams'][m_v]
    avg = data_liga['averages']
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    ph, pd, pa = 0, 0, 0
    for x in range(9):
        for y in range(9):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    sent = await bot.reply_to(message, f"📈 Analizando {m_l} vs {m_v}...")
    
    header_checks = "🛠 **REPORTE:** ✅ Cuotas | ✅ Poisson | ✅ Rachas\n"
    try:
        model = genai.GenerativeModel(config_ia["modelo_actual"])
        prompt = f"Analiza {m_l} vs {m_v}. Poisson: L {ph*100:.1f}%, E {pd*100:.1f}%, V {pa*100:.1f}%. Define Nivel (BRONCE/PLATA/ORO/DIAMANTE) y Stake."
        response = await asyncio.to_thread(model.generate_content, prompt)
        await bot.edit_message_text(header_checks + response.text, message.chat.id, sent.message_id, parse_mode='Markdown')
    except: pass

async def main():
    logger.info("🚀 Bot iniciado.")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
