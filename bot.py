import os
import json
import asyncio
import logging
import requests
import base64
import time
import re
from scipy.stats import poisson
from datetime import datetime, timedelta

from google import genai
from google.genai import types
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Entorno ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

OFFSET_JUAREZ = -6
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# --- Estado Global Dinámico (SIN PRE-ESTABLECIDOS) ---
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "candidatos": {
        "GEMINI": ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-flash-8b'],
        "GROQ": ['llama-3.3-70b-versatile', 'llama3-70b-8192', 'mixtral-8x7b-32768', 'llama-3.1-8b-instant']
    },
    "vivos": {"GEMINI": [], "GROQ": []}
}

# --- Persistencia en GitHub ---
async def guardar_en_github(nuevo_registro=None, historial_completo=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=headers)
        sha = r.json()['sha'] if r.status_code == 200 else None
        
        if historial_completo is None:
            if r.status_code == 200:
                historial = json.loads(base64.b64decode(r.json()['content']).decode('utf-8'))
            else:
                historial = []
            if nuevo_registro: historial.append(nuevo_registro)
        else:
            historial = historial_completo

        nuevo_contenido = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')
        payload = {
            "message": "🤖 Actualización de Historial",
            "content": nuevo_contenido,
            "sha": sha
        }
        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"Error GitHub: {e}")

# --- Prueba de Aptitud Matemática ---
async def test_aptitud_matematica(api, nodo):
    prompt_test = "Responde solo el numero: Si lambda es 2.0, cual es la probabilidad de x=0 en Poisson? (Punto decimal)"
    if api == 'GEMINI':
        try:
            client = genai.Client(api_key=GEMINI_KEY)
            res = await asyncio.to_thread(client.models.generate_content, model=nodo, contents=prompt_test)
            return any(x in res.text for x in ["0.13", "0,13"])
        except: return False
    else:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": nodo, "messages": [{"role": "user", "content": prompt_test}], "max_tokens": 10}
        try:
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=10)
            if r.status_code == 200:
                texto = r.json()['choices'][0]['message']['content']
                return any(x in texto for x in ["0.13", "0,13"])
            return False
        except: return False

# --- Escaneo de Red ---
@bot.message_handler(commands=['scan_nodos'])
async def scan_nodos(message):
    msg = await bot.reply_to(message, "📡 **INICIANDO TEST DE APTITUD MATEMÁTICA...**\n(Espera de 10s + Delays de seguridad)")
    SISTEMA_IA["vivos"] = {"GEMINI": [], "GROQ": []}
    reporte = "🔎 **ESTADO DE NODOS (TEST POISSON):**\n\n"

    for n in SISTEMA_IA["candidatos"]["GEMINI"]:
        start = time.time()
        if await test_aptitud_matematica('GEMINI', n):
            SISTEMA_IA["vivos"]["GEMINI"].append(n)
            reporte += f"✅ `{n}` - APTO ({time.time()-start:.1f}s)\n"
        else:
            reporte += f"❌ `{n}` - NO APTO\n"
        await asyncio.sleep(1.5)
    
    for n in SISTEMA_IA["candidatos"]["GROQ"]:
        start = time.time()
        if await test_aptitud_matematica('GROQ', n):
            SISTEMA_IA["vivos"]["GROQ"].append(n)
            reporte += f"✅ `{n}` - APTO ({time.time()-start:.1f}s)\n"
        else:
            reporte += f"❌ `{n}` - NO APTO\n"
        await asyncio.sleep(2.5)

    reporte += "\n⚠️ *Usa /config para asignar roles.*"
    await bot.edit_message_text(reporte, message.chat.id, msg.message_id, parse_mode='Markdown')

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return "⚠️ Nodo no configurado."
    if config["api"] == 'GEMINI':
        try:
            client = genai.Client(api_key=GEMINI_KEY)
            res = await asyncio.to_thread(client.models.generate_content, model=config["nodo"], contents=prompt, config=types.GenerateContentConfig(temperature=0.1))
            return res.text
        except: return "❌ Error en Nodo Gemini (Timeout)"
    else:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": config["nodo"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 700}
        try:
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=10)
            return r.json()['choices'][0]['message']['content']
        except: return "❌ Error en Nodo GROQ (Timeout)"

# --- Estadísticas y Mercado ---
async def obtener_datos_mercado(equipo_l):
    if not ODDS_API_KEY: return 1.85, 3.50, 4.00, False
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

async def obtener_h2h_directo(equipo_l, equipo_v):
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        data = await api_football_call("teams")
        teams = data.get('teams', []) if data else []
        id_l = next((t['id'] for t in teams if equipo_l.lower() in t['shortName'].lower() or t['shortName'].lower() in equipo_l.lower()), None)
        id_v = next((t['id'] for t in teams if equipo_v.lower() in t['shortName'].lower() or t['shortName'].lower() in equipo_v.lower()), None)
        if id_l and id_v:
            url = f"https://api.football-data.org/v4/teams/{id_l}/matches?competitors={id_v}&status=FINISHED"
            r = await asyncio.to_thread(requests.get, url, headers=headers)
            matches = r.json().get('matches', [])
            if matches:
                l, v, e = 0, 0, 0
                for m in matches[:5]:
                    w = m['score']['winner']
                    if w == 'HOME_TEAM': l += 1
                    elif w == 'AWAY_TEAM': v += 1
                    else: e += 1
                return f"Local {l} | Visitante {v} | Empates {e}", True
        return "Sin datos directos.", False
    except: return "Error API.", False

# --- Comando Pronóstico ---
@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 **ERROR:** Configura un nodo APTO en `/config` primero."); return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, f"📡 Analizando {l_q} vs {v_q}...")

    raw_json = requests.get(URL_JSON)
    full_data = raw_json.json()
    c_l, c_e, c_v, _ = await obtener_datos_mercado(l_q)
    h2h, _ = await obtener_h2h_directo(l_q, v_q)

    liga = next(iter(full_data))
    m_l = next((t for t in full_data[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
    m_v = next((t for t in full_data[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)
    
    if not m_l or not m_v:
        await bot.edit_message_text("❌ Equipos no encontrados.", message.chat.id, msg_espera.message_id); return

    l_s, v_s = full_data[liga]['teams'][m_l], full_data[liga]['teams'][m_v]
    avg = full_data[liga]['averages']
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    
    ph, pd, pa = 0, 0, 0
    for x in range(6):
        for y in range(6):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    p_win = ph 
    edge = p_win - (1 / c_l)
    stake = max(0, min(round(((c_l * p_win) - 1) / (c_l - 1) * 25, 2), 5)) if edge > 0 else 0

    await guardar_en_github(nuevo_registro={
        "fecha": (datetime.utcnow() + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
        "partido": f"{m_l} vs {m_v}",
        "pick": m_l if edge > 0 else "No Bet",
        "poisson": f"{p_win*100:.1f}%",
        "cuota": c_l,
        "stake": f"{stake}%",
        "status": "⏳ PENDIENTE"
    })

    prompt = f"Analista Pro. Partido: {m_l} vs {m_v}. Poisson: {p_win*100:.1f}%. Cuota: {c_l}. H2H: {h2h}. Veredicto técnico."
    analisis = await ejecutar_ia("estratega", prompt)

    final = (f"🏟 **{m_l.upper()} vs {m_v.upper()}**\n"
             f"📈 Poisson: `{p_win*100:.1f}%` | Cuota: `{c_l}`\n"
             f"🎯 Pick: `{m_l if edge > 0 else 'No Bet'}` | Stake: `{stake}%`\n"
             f"————————————————————\n"
             f"🧠 **ANÁLISIS:**\n{analisis}\n\n"
             f"🛰 `Nodo: {SISTEMA_IA['estratega']['nodo']}`")

    await bot.edit_message_text(final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

# --- Configuración y Menús ---
@bot.message_handler(commands=['config'])
async def cmd_config(message):
    if not SISTEMA_IA["vivos"]["GEMINI"] and not SISTEMA_IA["vivos"]["GROQ"]:
        await bot.reply_to(message, "⚠️ Ejecuta `/scan_nodos` primero."); return
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ **CONFIGURACIÓN DE IA**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rol_'))
async def cb_rol(call):
    rol = call.data.split('_')[-1]
    markup = InlineKeyboardMarkup().row(
        InlineKeyboardButton("Red Gemini", callback_data=f"set_api_{rol}_GEMINI"),
        InlineKeyboardButton("Red Groq", callback_data=f"set_api_{rol}_GROQ")
    )
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_api_'))
async def cb_api(call):
    _, _, rol, api = call.data.split('_')
    vivos = SISTEMA_IA["vivos"][api]
    if not vivos:
        await bot.answer_callback_query(call.id, f"❌ Sin nodos APTOS en {api}.", show_alert=True); return
    markup = InlineKeyboardMarkup()
    for n in vivos:
        markup.add(InlineKeyboardButton(f"✅ {n}", callback_data=f"save_nodo_{rol}_{api}_{n}"))
    await bot.edit_message_text(f"Modelos Aptos ({api}):", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_nodo_'))
async def cb_save(call):
    _, _, rol, api, nodo = call.data.split('_')
    if await test_aptitud_matematica(api, nodo):
        SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))
        await bot.edit_message_text(f"🚀 **{rol.upper()} ASIGNADO**\nNodo: `{nodo}`", call.message.chat.id, call.message.message_id, reply_markup=markup)
    else:
        await bot.answer_callback_query(call.id, "❌ Falló el test final.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("✅ **SISTEMA LISTO**", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['help'])
async def cmd_help(message):
    help_text = (
        "🤖 **BET-BOT V5.7 (RESTORED)**\n\n"
        "1️⃣ `/scan_nodos` - Test de aptitud matemática Poisson (10s espera/retraso seguridad).\n"
        "2️⃣ `/config` - Menú interactivo para asignar roles a nodos APTOS.\n"
        "3️⃣ `/pronostico L vs V` - Cálculo Poisson, Mercado Odds, H2H y análisis de IA.\n"
        "4️⃣ `/valor L vs V` - Alias del comando pronóstico.\n"
        "5️⃣ `/help` - Muestra esta ayuda detallada.\n\n"
        "📊 *Los registros se guardan automáticamente en GitHub.*"
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

async def main(): await bot.polling(non_stop=True)
if __name__ == "__main__": asyncio.run(main())
