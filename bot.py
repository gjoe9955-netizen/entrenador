import os
import json
import asyncio
import logging
import requests
import base64
from scipy.stats import poisson
from datetime import datetime, timedelta

from openai import OpenAI
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Entorno ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
SAMBA_KEY = os.getenv('SAMBA_KEY')
GROQ_KEY = os.getenv('GROQ_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

OFFSET_JUAREZ = -6
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# --- Estado Global Dinámico ---
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_samba": [
        "DeepSeek-V3.1", 
        "DeepSeek-V3.1-cb", 
        "DeepSeek-V3.2", 
        "Llama-4-Maverick-17B-128E-Instruct", 
        "Meta-Llama-3.3-70B-Instruct"
    ],
    "nodos_groq": [
        "llama-3.3-70b-versatile", 
        "groq/compound-mini", 
        "meta-llama/llama-4-scout-17b-16e-instruct", 
        "llama-3.1-8b-instant", 
        "groq/compound"
    ]
}

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    
    if config["api"] == 'SAMBA':
        client = OpenAI(api_key=SAMBA_KEY, base_url="https://api.sambanova.ai/v1")
    else:
        client = OpenAI(api_key=GROQ_KEY, base_url="https://api.groq.com/openai/v1")

    try:
        res = await asyncio.to_thread(
            client.chat.completions.create,
            model=config["nodo"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        return res.choices[0].message.content
    except:
        return f"❌ Error en Nodo {config['api']}"

# --- Persistencia en GitHub ---
async def guardar_en_github(nuevo_registro=None, historial_completo=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=headers)
        sha = r.json()['sha'] if r.status_code == 200 else None
        
        if historial_completo is None:
            historial = json.loads(base64.b64decode(r.json()['content']).decode('utf-8')) if r.status_code == 200 else []
            if nuevo_registro: historial.append(nuevo_registro)
        else:
            historial = historial_completo

        nuevo_contenido = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')
        payload = {"message": "🤖 Historial Update", "content": nuevo_contenido, "sha": sha}
        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"Error GitHub: {e}")

# --- Núcleo Estadístico (Poisson) ---
async def obtener_datos_mercado(equipo_l):
    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/"
        params = {'apiKey': ODDS_API_KEY, 'regions': 'eu', 'markets': 'h2h'}
        r = await asyncio.to_thread(requests.get, url, params=params, timeout=10)
        if r.status_code == 200:
            for match in r.json():
                home = match['home_team'].lower()
                if equipo_l.lower() in home or home in equipo_l.lower():
                    odds = match['bookmakers'][0]['markets'][0]['outcomes']
                    ol = next(o['price'] for o in odds if o['name'] == match['home_team'])
                    ov = next(o['price'] for o in odds if o['name'] == match['away_team'])
                    oe = next(o['price'] for o in odds if o['name'] == 'Draw')
                    return ol, oe, ov, True
    except: pass
    return 1.85, 3.50, 4.00, False

async def api_football_call(endpoint):
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r = await asyncio.to_thread(requests.get, f"https://api.football-data.org/v4/competitions/PD/{endpoint}", headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

# --- Comandos del Bot ---
@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura los nodos con `/config`."); return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 Procesando Datos...")

    # Carga de datos JSON y Poisson (Resumido para brevedad, funcional igual al original)
    raw_json = requests.get(URL_JSON).json()
    liga = next(iter(raw_json))
    m_l = next((t for t in raw_json[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
    m_v = next((t for t in raw_json[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)

    if not m_l or not m_v:
        await bot.edit_message_text("❌ Equipo no encontrado en JSON.", message.chat.id, msg_espera.message_id); return

    c_l, c_e, c_v, check_odds = await obtener_datos_mercado(m_l)
    
    # [Lógica Poisson omitida aquí por espacio, pero permanece idéntica en tu archivo local]
    # ... (lh, la, ph, pd, pa, p_percent, edge_real, stake_final, nivel)

    prompt_e = f"Analista Senior. Partido: {m_l} vs {m_v}. Poisson: {p_percent:.1f}%. Cuota: {c_l}. NIVEL: {nivel}. STAKE: {stake_final}%."
    analisis = await ejecutar_ia("estratega", prompt_e)
    
    footer = f"\n\n🛰 **ESTRATEGA:** `{SISTEMA_IA['estratega']['api']}` ({SISTEMA_IA['estratega']['nodo']})"
    await bot.edit_message_text(f"{analisis}{footer}", message.chat.id, msg_espera.message_id, parse_mode='Markdown')

# --- Gestión de Configuración (Fix Callback 64 bytes) ---
@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "🛠 **CONFIGURACIÓN DE RED**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rol_'))
async def cb_rol(call):
    rol = call.data.split('_')[-1]
    markup = InlineKeyboardMarkup().row(
        InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"),
        InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ")
    )
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_api_'))
async def cb_api(call):
    _, _, rol, api = call.data.split('_')
    nodos = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]
    
    markup = InlineKeyboardMarkup()
    for idx, n in enumerate(nodos):
        # Usamos IDX para evitar el error de 64 bytes
        markup.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{idx}"))
    await bot.edit_message_text(f"Selecciona Nodo {api}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('sv_n_'))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split('_')
    lista = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]
    seleccion = lista[int(idx)]
    
    SISTEMA_IA[rol] = {"api": api, "nodo": seleccion}
    
    markup = InlineKeyboardMarkup()
    if rol == "estratega": markup.add(InlineKeyboardButton("⚖️ AÑADIR AUDITOR", callback_data="set_rol_auditor"))
    markup.add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} listo: `{seleccion}`", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("🚀 **SISTEMA LISTO**", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['test'])
async def cmd_test(message):
    # Lógica dinámica para refrescar listas si es necesario
    await bot.reply_to(message, "🛠 Ejecutando escaneo dinámico de nodos...")
    # [Aquí va el código de test que creamos antes para actualizar SISTEMA_IA['nodos_...']]

async def main(): await bot.polling(non_stop=True)
if __name__ == "__main__": asyncio.run(main())
