import os
import json
import asyncio
import logging
import requests
import base64
from scipy.stats import poisson
from datetime import datetime, timedelta

from google import genai
from google.genai import types
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Entorno ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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

# --- Estado Global ---
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "vivos": {"GEMINI": [], "GROQ": []},
    "nodos_defecto": {
        "GEMINI": ['gemini-2.0-flash-exp', 'gemini-1.5-flash', 'gemini-1.5-pro'],
        "GROQ": ['llama-3.3-70b-versatile', 'llama3-8b-8192', 'mixtral-8x7b-32768']
    }
}

# --- Persistencia en GitHub ---
async def guardar_en_github(nuevo_registro):
    if not GITHUB_TOKEN: return
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = await asyncio.to_thread(requests.get, url, headers=headers)
        sha = r.json()['sha'] if r.status_code == 200 else None
        
        if r.status_code == 200:
            content = base64.b64decode(r.json()['content']).decode('utf-8')
            historial = json.loads(content)
        else:
            historial = []
        
        historial.append(nuevo_registro)
        nuevo_contenido = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')
        payload = {"message": "🤖 Registro de Pronóstico", "content": nuevo_contenido, "sha": sha}
        await asyncio.to_thread(requests.put, url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"Error GitHub: {e}")

# --- Test de Aptitud Rápido (PRUEBA OBLIGATORIA) ---
async def probar_nodo(api, nodo):
    """
    Realiza una llamada real al modelo. 
    Si no responde en el tiempo límite, el nodo queda DESCARTADO.
    """
    prompt_test = "Responde únicamente con la palabra OK."
    try:
        if api == 'GEMINI':
            client = genai.Client(api_key=GEMINI_KEY)
            # Prueba real de generación de contenido
            response = await asyncio.wait_for(
                asyncio.to_thread(client.models.generate_content, model=nodo, contents=prompt_test),
                timeout=8.0
            )
            # Validamos que haya respuesta de texto
            if response and response.text:
                return nodo, True
        elif api == 'GROQ':
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            payload = {"model": nodo, "messages": [{"role": "user", "content": prompt_test}], "max_tokens": 5}
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=8.0)
            if r.status_code == 200:
                return nodo, True
    except Exception as e:
        logging.warning(f"Nodo {nodo} falló la prueba de aptitud: {e}")
    return nodo, False

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return "IA no configurada."
    try:
        if config["api"] == 'GEMINI':
            client = genai.Client(api_key=GEMINI_KEY)
            res = await asyncio.to_thread(client.models.generate_content, model=config["nodo"], contents=prompt)
            return res.text
        elif config["api"] == 'GROQ':
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            payload = {"model": config["nodo"], "messages": [{"role": "user", "content": prompt}]}
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=12)
            return r.json()['choices'][0]['message']['content']
    except:
        return "❌ Error en respuesta de IA."

# --- APIs de Datos con Verificadores ---
async def obtener_datos_mercado(equipo_l):
    if not ODDS_API_KEY: return 1.85, 3.50, 4.00, False
    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/"
        params = {'apiKey': ODDS_API_KEY, 'regions': 'eu', 'markets': 'h2h'}
        r = await asyncio.to_thread(requests.get, url, params=params, timeout=10)
        if r.status_code == 200:
            for match in r.json():
                if equipo_l.lower() in match['home_team'].lower() or match['home_team'].lower() in equipo_l.lower():
                    odds = match['bookmakers'][0]['markets'][0]['outcomes']
                    ol = next(o['price'] for o in odds if o['name'] == match['home_team'])
                    ov = next(o['price'] for o in odds if o['name'] == match['away_team'])
                    oe = next(o['price'] for o in odds if o['name'] == 'Draw')
                    return ol, oe, ov, True
    except: pass
    return 1.85, 3.50, 4.00, False

async def obtener_h2h_real(equipo_l, equipo_v):
    if not FOOTBALL_DATA_KEY: return "N/A", False
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r_teams = await asyncio.to_thread(requests.get, "https://api.football-data.org/v4/competitions/PD/teams", headers=headers, timeout=10)
        if r_teams.status_code == 200:
            teams = r_teams.json().get('teams', [])
            id_l = next((t['id'] for t in teams if equipo_l.lower() in t['shortName'].lower() or t['name'].lower() in equipo_l.lower()), None)
            id_v = next((t['id'] for t in teams if equipo_v.lower() in t['shortName'].lower() or t['name'].lower() in equipo_v.lower()), None)
            if id_l and id_v:
                m_url = f"https://api.football-data.org/v4/teams/{id_l}/matches?competitors={id_v}&status=FINISHED"
                rm = await asyncio.to_thread(requests.get, m_url, headers=headers, timeout=10)
                matches = rm.json().get('matches', [])
                if matches:
                    l, v, e = 0, 0, 0
                    for m in matches[:5]:
                        winner = m['score']['winner']
                        if winner == 'HOME_TEAM': l += 1
                        elif winner == 'AWAY_TEAM': v += 1
                        else: e += 1
                    return f"L:{l} V:{v} E:{e}", True
    except: pass
    return "N/A", False

# --- Comandos del Bot ---

@bot.message_handler(commands=['scan_nodos'])
async def scan_nodos(message):
    """
    Ejecuta la prueba de aptitud en paralelo para todos los nodos por defecto.
    Solo los que pasen la prueba serán elegibles.
    """
    msg = await bot.reply_to(message, "⚡ **INICIANDO PRUEBA DE APTITUD DE NODOS...**")
    tareas = []
    
    # Creamos la lista de tareas de prueba
    for api, modelos in SISTEMA_IA["nodos_defecto"].items():
        for m in modelos:
            tareas.append(probar_nodo(api, m))
    
    # Ejecutamos todas las pruebas en paralelo
    resultados = await asyncio.gather(*tareas)
    
    # Reiniciamos la lista de nodos vivos
    SISTEMA_IA["vivos"] = {"GEMINI": [], "GROQ": []}
    
    # Clasificamos según el resultado de la prueba real
    total_gemini = len(SISTEMA_IA["nodos_defecto"]["GEMINI"])
    for i, (nodo, paso_la_prueba) in enumerate(resultados):
        api_tipo = "GEMINI" if i < total_gemini else "GROQ"
        if paso_la_prueba:
            SISTEMA_IA["vivos"][api_tipo].append(nodo)

    reporte = "📋 **REPORTE DE NODOS VERIFICADOS:**\n"
    for api, lista in SISTEMA_IA["vivos"].items():
        reporte += f"\n🔹 {api}:\n"
        if lista:
            for n in lista: reporte += f"  └ `{n}` ✅ (Apto)\n"
        else:
            reporte += "  └ ❌ Ningún nodo superó la prueba\n"
            
    await bot.edit_message_text(reporte + "\nUsa `/config` para elegir uno de los nodos aptos.", message.chat.id, msg.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['pronostico'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura la IA con `/config` primero."); return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Usa: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 **OBTENIENDO DATOS Y CALCULANDO...**")

    # 1. Verificador Poisson
    v_poisson = "❌"
    try:
        raw_json = await asyncio.to_thread(requests.get, URL_JSON, timeout=10)
        full_data = raw_json.json()
        v_poisson = "✅"
    except: pass

    # 2. Verificador Mercado
    c_l, c_e, c_v, check_odds = await obtener_datos_mercado(l_q)
    v_odds = "✅" if check_odds else "❌"

    # 3. Verificador H2H
    h2h_txt, check_h2h = await obtener_h2h_real(l_q, v_q)
    v_h2h = "✅" if check_h2h else "❌"

    # Lógica de Probabilidades
    try:
        liga = next(iter(full_data))
        m_l = next((t for t in full_data[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
        m_v = next((t for t in full_data[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)
        
        l_s, v_s = full_data[liga]['teams'][m_l], full_data[liga]['teams'][m_v]
        avg = full_data[liga]['averages']
        lh, la = l_s['att_h'] * v_s['def_a'] * avg['league_home'], v_s['att_a'] * l_s['def_h'] * avg['league_away']
        
        prob_win = sum(poisson.pmf(x, lh) * poisson.pmf(y, la) for x in range(7) for y in range(7) if x > y)
        edge = prob_win - (1/c_l)
        stake = max(0, min(round(((c_l * prob_win) - 1) / (c_l - 1) * 25, 2), 5.0)) if edge > 0 else 0

        header = (
            f"🏟 **{m_l.upper()} VS {m_v.upper()}**\n"
            f"————————————————————\n"
            f"📊 **FUENTES TÉCNICAS:**\n"
            f"┣ {v_poisson} Poisson DB\n"
            f"┣ {v_odds} Odds API (`{c_l:.2f}`)\n"
            f"┗ {v_h2h} Football-Data (`{h2h_txt}`)\n"
            f"————————————————————\n"
        )
        
        ticket = (
            f"🎫 **TICKET DE VALOR:**\n"
            f"```\n"
            f"PICK:  {m_l}\n"
            f"PROB:  {prob_win*100:.1f}%\n"
            f"EDGE:  {edge*100:+.1f}%\n"
            f"STAKE: {stake}%\n"
            f"```\n"
        )

        analisis = await ejecutar_ia("estratega", f"Analiza {m_l} vs {m_v}. Win Prob: {prob_win*100:.1f}%. Cuota: {c_l}. Veredicto técnico.")
        
        final_msg = f"{header}{ticket}🧠 **ANALISIS IA:**\n_{analisis}_"
        await bot.edit_message_text(final_msg, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

        # Registro en GitHub
        asyncio.create_task(guardar_en_github({
            "fecha": (datetime.utcnow() + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
            "partido": f"{m_l} vs {m_v}", "pick": m_l, "cuota": c_l, "stake": f"{stake}%", "status": "⏳"
        }))
    except Exception as e:
        await bot.edit_message_text(f"❌ Error en cálculo: {str(e)}", message.chat.id, msg_espera.message_id)

@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 CONFIGURAR IA", callback_data="set_ia_estratega"))
    await bot.reply_to(message, "⚙️ **CONFIGURACIÓN DEL MOTOR**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "set_ia_estratega")
async def cb_api(call):
    markup = InlineKeyboardMarkup().row(
        InlineKeyboardButton("Gemini", callback_data="api_GEMINI"),
        InlineKeyboardButton("Groq", callback_data="api_GROQ")
    )
    await bot.edit_message_text("Elige API:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('api_'))
async def cb_modelos(call):
    api = call.data.split('_')[1]
    vivos = SISTEMA_IA["vivos"][api]
    if not vivos:
        await bot.answer_callback_query(call.id, "❌ No hay nodos que hayan pasado la prueba. Ejecuta /scan_nodos.", show_alert=True); return
    markup = InlineKeyboardMarkup()
    for n in vivos: markup.add(InlineKeyboardButton(n, callback_data=f"save_{api}_{n}"))
    await bot.edit_message_text(f"Modelos {api} APTOS:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_'))
async def cb_save(call):
    _, api, nodo = call.data.split('_')
    SISTEMA_IA["estratega"] = {"api": api, "nodo": nodo}
    await bot.edit_message_text(f"✅ IA configurada y verificada: `{nodo}`", call.message.chat.id, call.message.message_id)

async def main():
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
