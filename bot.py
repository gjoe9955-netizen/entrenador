import os
import json
import asyncio
import logging
import requests
import time
from datetime import datetime
from scipy.stats import poisson

# Librerías actualizadas
from google import genai
from google.genai import types
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración Inicial ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

# Tokens y Keys
TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
NVIDIA_KEY = os.getenv('NVIDIA_KEY') # Asegúrate de tener esta en tu .env
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')

# URLs de Datos
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"

bot = AsyncTeleBot(TOKEN)

# Diccionario Global de Configuración (NODOS VALIDADOS)
SISTEMA_IA = {
    "api_activa": None,  # 'GEMINI' o 'NVIDIA'
    "nodo_estratega": None,
    "nodos_gemini": ['gemini-2.5-flash-lite', 'gemini-3.1-flash-lite-preview'],
    "nodos_nvidia": ['meta/llama-3.1-70b-instruct', 'meta/llama-3.1-8b-instruct']
}

# --- MOTORES DE IA ACTUALIZADOS ---

async def llamar_gemini(nodo, prompt):
    client = genai.Client(api_key=GEMINI_KEY)
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=nodo,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=500, temperature=0.2)
        )
        return response.text
    except Exception as e:
        return f"❌ Error Gemini: {str(e)[:50]}"

async def llamar_nvidia(nodo, prompt):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": nodo,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2, "max_tokens": 500
    }
    try:
        response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        return f"❌ Error NVIDIA (Code {response.status_code})"
    except Exception as e:
        return f"❌ Error Técnico NVIDIA: {str(e)[:50]}"

# --- LÓGICA DE DATOS (POISSON & FOOTBALL-DATA) ---

def obtener_datos_poisson():
    try:
        response = requests.get(URL_JSON, timeout=10)
        return response.json() if response.status_code == 200 else None
    except: return None

async def obtener_dict_motivacion():
    if not FOOTBALL_DATA_KEY: return {}
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r = requests.get("https://api.football-data.org/v4/competitions/PD/standings", headers=headers, timeout=10)
        if r.status_code != 200: return {}
        standings = r.json()['standings'][0]['table']
        motivaciones = {}
        for t in standings:
            nombre = t['team']['shortName']
            pos = t['position']
            if pos <= 4: sit = "🏆 CHAMPIONS (Máxima)"
            elif 5 <= pos <= 7: sit = "🇪🇺 EUROPA (Alta)"
            elif pos >= 18: sit = "🆘 DESCENSO (Crítica)"
            else: sit = "⚠️ MEDIA-BAJA (Alerta)"
            motivaciones[nombre] = {"pos": pos, "situacion": sit}
        return motivaciones
    except: return {}

# --- COMANDOS Y BOTONERAS CON DESVANECIMIENTO ---

@bot.message_handler(commands=['test', 'config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🟢 GOOGLE GEMINI", callback_data="api_GEMINI"),
        InlineKeyboardButton("🟢 NVIDIA NIM", callback_data="api_NVIDIA")
    )
    await bot.reply_to(message, "🛠 **SELECTOR MULTI-API**\nSelecciona la infraestructura de inteligencia:", 
                       reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('api_'))
async def cb_elegir_api(call):
    api = call.data.split('_')[1]
    SISTEMA_IA["api_activa"] = api
    
    # Efecto de desvanecimiento (Editamos el mensaje para mostrar nodos)
    markup = InlineKeyboardMarkup()
    nodos = SISTEMA_IA["nodos_gemini"] if api == 'GEMINI' else SISTEMA_IA["nodos_nvidia"]
    
    for n in nodos:
        nombre_corto = n.split('/')[-1]
        markup.add(InlineKeyboardButton(f"Nodo: {nombre_corto}", callback_data=f"nodo_{n}"))
    
    await bot.edit_message_text(
        f"✅ **INFRAESTRUCTURA: {api}**\nAhora elige el nodo estratega para Poisson:",
        call.message.chat.id, call.message.message_id,
        reply_markup=markup, parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('nodo_'))
async def cb_finalizar_config(call):
    nodo = call.data.split('nodo_')[1]
    SISTEMA_IA["nodo_estratega"] = nodo
    
    # Limpieza final (Desvanecimiento completo)
    api = SISTEMA_IA["api_activa"]
    texto_final = (
        f"🚀 **SISTEMA CONFIGURADO**\n\n"
        f"🌐 **API:** `{api}`\n"
        f"🧠 **Estratega:** `{nodo.split('/')[-1]}`\n"
        f"📊 **Motor:** Poisson + FootballData\n\n"
        f"Ya puedes usar `/pronostico`."
    )
    await bot.edit_message_text(texto_final, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# --- PROCESAMIENTO DE PRONÓSTICO (MOTOR HÍBRIDO) ---

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not SISTEMA_IA["nodo_estratega"]:
        await bot.reply_to(message, "⚠️ Configura la IA con `/config` primero."); return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Formato: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    full_data = obtener_datos_poisson()
    if not full_data: 
        await bot.reply_to(message, "❌ Error: Base de datos Poisson no disponible."); return

    # Mapeo de equipos
    liga_key = next(iter(full_data))
    data_liga = full_data[liga_key]
    m_l = next((t for t in data_liga['teams'] if t.lower() in l_q.lower()), None)
    m_v = next((t for t in data_liga['teams'] if t.lower() in v_q.lower()), None)
    
    if not m_l or not m_v:
        await bot.reply_to(message, f"❌ No encontré a {l_q} o {v_q}. Revisa `/equipos`."); return

    # Lógica Poisson
    l_s, v_s = data_liga['teams'][m_l], data_liga['teams'][m_v]
    avg = data_liga['averages']
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    ph, pd, pa = 0, 0, 0
    for x in range(7): # Reducimos rango para velocidad
        for y in range(7):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    # Datos de contexto
    motivacion = await obtener_dict_motivacion()
    info_l = motivacion.get(m_l, {"pos": "?", "situacion": "Normal"})
    info_v = motivacion.get(m_v, {"pos": "?", "situacion": "Normal"})

    msg_espera = await bot.reply_to(message, f"🧬 Analizando con {SISTEMA_IA['api_activa']}...")

    # Prompt Maestro para el "Estratega"
    prompt = (
        f"Analiza valor para: {m_l} vs {m_v}.\n"
        f"ESTADÍSTICA POISSON: Local {ph*100:.1f}%, Empate {pd*100:.1f}%, Visitante {pa*100:.1f}%.\n"
        f"TABLA: {m_l} (Pos {info_l['pos']} - {info_l['situacion']}) | {m_v} (Pos {info_v['pos']} - {info_v['situacion']}).\n"
        "Define NIVEL (BRONCE/PLATA/ORO/DIAMANTE) y justifica basándote en si la urgencia de puntos supera la estadística."
    )

    # Llamada a la API correspondiente
    if SISTEMA_IA["api_activa"] == 'GEMINI':
        resultado = await llamar_gemini(SISTEMA_IA["nodo_estratega"], prompt)
    else:
        resultado = await llamar_nvidia(SISTEMA_IA["nodo_estratega"], prompt)

    reporte = f"🏟 **{m_l} vs {m_v}**\n{'—'*15}\n{resultado}"
    await bot.edit_message_text(reporte, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

# --- OTROS COMANDOS ---

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if data:
        liga = next(iter(data))
        equipos = ", ".join([f"`{e}`" for e in data[liga]['teams'].keys()])
        await bot.reply_to(message, f"📋 **EQUIPOS DISPONIBLES:**\n\n{equipos}", parse_mode='Markdown')

@bot.message_handler(commands=['start', 'help'])
async def cmd_start(message):
    await bot.reply_to(message, "⚽ **BOT MULTI-API POISSON**\n1. Usa `/config` para activar el cerebro.\n2. Usa `/pronostico` para analizar.")

async def main():
    logger.info("🚀 Sistema Híbrido Iniciado.")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
