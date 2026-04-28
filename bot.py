import os
import json
import asyncio
import logging
import requests
import base64
import io
import pandas as pd
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

# --- Diccionario de Mapeo: API/JSON -> CSV ---
MAPEO_EQUIPOS = {
    "Girona FC": "Girona",
    "Rayo Vallecano de Madrid": "Vallecano",
    "Villarreal CF": "Villarreal",
    "Real Oviedo": "Oviedo",
    "RCD Mallorca": "Mallorca",
    "FC Barcelona": "Barcelona",
    "Deportivo Alavés": "Alaves",
    "Levante UD": "Levante",
    "Valencia CF": "Valencia",
    "Real Sociedad de Fútbol": "Sociedad",
    "RC Celta de Vigo": "Celta",
    "Getafe CF": "Getafe",
    "Athletic Club": "Ath Bilbao",
    "Sevilla FC": "Sevilla",
    "RCD Espanyol de Barcelona": "Espanol",
    "Club Atlético de Madrid": "Ath Madrid",
    "Elche CF": "Elche",
    "Real Betis Balompié": "Betis",
    "Real Madrid CF": "Real Madrid",
    "CA Osasuna": "Osasuna"
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

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    
    s_key = os.getenv('SAMBA_KEY') or os.getenv('SAMBANOVA_API_KEY')
    g_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_KEY')
    
    api_key = s_key if config["api"] == 'SAMBA' else g_key
    base_url = "https://api.sambanova.ai/v1" if config["api"] == 'SAMBA' else "https://api.groq.com/openai/v1"

    if not api_key: return f"❌ Error: API Key para {config['api']} no configurada."

    instrucciones = {
        "estratega": (
            "Eres un experto en Value Betting y modelos estadísticos. "
            "Analiza: 1) Probabilidad Poisson detallada vs Cuota Real. 2) Tendencia H2H del CSV. "
            "Tu objetivo es identificar si existe una ventaja matemática real (Edge).\n\n"
            "REGLAS:\n"
            "- Si el Edge es > 2%, busca confirmación en el H2H para el PICK.\n"
            "- Si el Edge es negativo, el PICK debe ser NO APOSTAR.\n\n"
            "FORMATO OBLIGATORIO:\n"
            "• ANÁLISIS: Justificación técnica integrando Poisson y H2H.\n"
            "• MERCADO RELEVANTE: Cuota analizada y su valor real.\n"
            "• PREDICCIÓN: Pronóstico directo o NO APOSTAR."
        ),
        "auditor": (
            "Eres un Auditor de Riesgos Matemáticos. PROHIBIDO SALUDAR.\n\n"
            "Valida la coherencia entre el Edge y la decisión del estratega. "
            "Si el Edge es negativo, no permitas ninguna apuesta. Máximo 50 palabras."
        )
    }

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        res = await asyncio.to_thread(
            client.chat.completions.create,
            model=config["nodo"],
            messages=[{"role": "system", "content": instrucciones[rol]}, {"role": "user", "content": prompt}],
            temperature=0.1
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"❌ Error IA: {str(e)[:60]}"

# --- Persistencia en GitHub ---
async def guardar_en_github(nuevo_registro=None, historial_completo=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r_get = requests.get(url, headers=headers)
        sha = r_get.json()['sha'] if r_get.status_code == 200 else None
        
        if historial_completo is None:
            historial = json.loads(base64.b64decode(r_get.json()['content']).decode('utf-8')) if r_get.status_code == 200 else []
            if nuevo_registro:
                index_existente = next((i for i, reg in enumerate(historial) if reg['partido'] == nuevo_registro['partido'] and reg['status'] == "⏳ PENDIENTE"), None)
                if index_existente is not None: historial[index_existente] = nuevo_registro
                else: historial.append(nuevo_registro)
        else: historial = historial_completo

        nuevo_contenido = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')
        payload = {"message": "🤖 Sync Historial", "content": nuevo_contenido, "sha": sha}
        requests.put(url, headers=headers, json=payload)
    except Exception as e: logging.error(f"Error GitHub: {e}")

# --- APIs de Datos (FIXED ODDS) ---
async def obtener_datos_mercado(equipo_l):
    if not ODDS_API_KEY: return 1.85, 3.50, 4.00, False
    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/"
        params = {'apiKey': ODDS_API_KEY, 'regions': 'eu', 'markets': 'h2h'}
        r = await asyncio.to_thread(requests.get, url, params=params, timeout=10)
        
        target = equipo_l.lower()
        if r.status_code == 200:
            for match in r.json():
                home = match['home_team'].lower()
                # Coincidencia flexible para evitar fallos por "FC" o "Real"
                if target in home or home in target:
                    odds = match['bookmakers'][0]['markets'][0]['outcomes']
                    ol = next(o['price'] for o in odds if o['name'].lower() == home)
                    ov = next(o['price'] for o in odds if o['name'].lower() == match['away_team'].lower())
                    oe = next(o['price'] for o in odds if any(x in o['name'].lower() for x in ['draw', 'tie', 'empate']))
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
    URL_CSV = "https://www.football-data.co.uk/mmz4281/2526/SP1.csv"
    try:
        csv_l = MAPEO_EQUIPOS.get(equipo_l, equipo_l.split()[0])
        csv_v = MAPEO_EQUIPOS.get(equipo_v, equipo_v.split()[0])
        r = await asyncio.to_thread(requests.get, URL_CSV, timeout=10)
        if r.status_code != 200: return "Error CSV.", False
        df = pd.read_csv(io.StringIO(r.text))
        mask = ((df['HomeTeam'] == csv_l) & (df['AwayTeam'] == csv_v) | (df['HomeTeam'] == csv_v) & (df['AwayTeam'] == csv_l))
        h2h = df[mask]
        if h2h.empty: return "Sin H2H en CSV.", False
        l, v, e = 0, 0, 0
        for _, row in h2h.iterrows():
            is_l_home = (row['HomeTeam'] == csv_l)
            if row['FTR'] == 'H':
                if is_l_home: l += 1
                else: v += 1
            elif row['FTR'] == 'A':
                if is_l_home: v += 1
                else: l += 1
            else: e += 1
        return f"Local {l} | Vis {v} | Emp {e}", True
    except: return "Error CSV.", False

# --- Pronóstico ---
@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura los nodos con `/config`."); return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ `/pronostico Local vs Visitante`."); return
    
    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 Analizando probabilidades...")
    
    try:
        raw_json = requests.get(URL_JSON, timeout=10).json()
        liga = next(iter(raw_json))
        m_l = next((t for t in raw_json[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
        m_v = next((t for t in raw_json[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)
        
        if not m_l or not m_v:
            await bot.edit_message_text("❌ Equipos no coinciden.", message.chat.id, msg_espera.message_id); return
        
        c_l, c_e, c_v, check_odds = await obtener_datos_mercado(m_l)
        h2h_str, check_h2h = await obtener_h2h_directo(m_l, m_v)
        l_stats, v_stats = raw_json[liga]['teams'][m_l], raw_json[liga]['teams'][m_v]
        avg = raw_json[liga]['averages']
        
        mu_l = l_stats['att_h'] * v_stats['def_a'] * avg['league_home']
        mu_v = v_stats['att_a'] * l_stats['def_h'] * avg['league_away']
        
        ph, pd, pa = 0, 0, 0
        for x in range(7):
            for y in range(7):
                prob = poisson.pmf(x, mu_l) * poisson.pmf(y, mu_v)
                if x > y: ph += prob
                elif x == y: pd += prob
                else: pa += prob
        
        edge = ph - (1/c_l)
        kelly = ((c_l * ph) - 1) / (c_l - 1) if edge > 0 else 0
        stake = round(max(0, min(kelly * 0.25 * 100, 5.0)), 2)
        
        await guardar_en_github(nuevo_registro={
            "fecha": (datetime.now(timezone.utc) + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
            "partido": f"{m_l} vs {m_v}", "pick": m_l if edge > 0 else "No Bet",
            "poisson": f"{ph*100:.1f}%", "cuota": c_l, "edge": f"{edge*100:.1f}%",
            "stake": f"{stake}%", "nivel": "TOP" if edge > 0.05 else "VALUE", "status": "⏳ PENDIENTE"
        })
        
        header = f"🛠 REPORTE: {'✅' if check_odds else '❌'} Cuotas | ✅ Poisson | {'✅' if check_h2h else '❌'} H2H\n{'—'*20}\n"
        prompt_full = (f"Encuentro: {m_l} vs {m_v}\n"
                       f"Lambdas: L:{mu_l:.2f} V:{mu_v:.2f}\n"
                       f"Probabilidades Poisson: Gana:{ph*100:.1f}% | Empate:{pd*100:.1f}% | Pierde:{pa*100:.1f}%\n"
                       f"Cuotas Mercado: Local:{c_l} Empate:{c_e} Visita:{c_v}\n"
                       f"Edge Calculado: {edge*100:.1f}%\nH2H Histórico: {h2h_str}")
        
        analisis = await ejecutar_ia("estratega", prompt_full)
        res_final = f"{header}{analisis}\n\n🛰 **ESTRATEGA:** `{SISTEMA_IA['estratega']['api']}`"
        
        if SISTEMA_IA["auditor"]["nodo"]:
            auditoria = await ejecutar_ia("auditor", f"Edge {edge*100:.1f}% | Estratega dice: {analisis}")
            res_final += f"\n\n🛡 **AUDITOR:**\n{auditoria}"
        
        await bot.edit_message_text(res_final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')
    except Exception as e:
        await bot.edit_message_text(f"❌ Error: {e}", message.chat.id, msg_espera.message_id)

# --- Comandos Visuales ---
@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}").json()
        if not r: return await bot.reply_to(message, "📭 **HISTORIAL VACÍO**")
        txt = "📊 **ÚLTIMOS PICKS**\n\n"
        for i in r[-5:]:
            st = i.get('status', '⏳')
            icon = "✅" if "WIN" in st else "❌" if "LOSS" in st else "⏳"
            txt += f"{icon} **{i['partido']}**\n🎯 Pick: {i['pick']} | 💰 Stake: {i['stake']}\n{'—'*15}\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    except: await bot.reply_to(message, "❌ Error al leer historial.")

@bot.message_handler(commands=['validar'])
async def cmd_validar(message):
    msg = await bot.reply_to(message, "🔍 Validando resultados...")
    try:
        historial = requests.get(f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}").json()
        data_api = await api_football_call("matches?status=FINISHED")
        actualizados = 0
        if data_api:
            for item in historial:
                if item.get("status") == "⏳ PENDIENTE":
                    for m in data_api['matches']:
                        h_api, a_api = m['homeTeam']['shortName'].lower(), m['awayTeam']['shortName'].lower()
                        if h_api in item['partido'].lower() and a_api in item['partido'].lower():
                            res = m['score']['winner']
                            item['status'] = "✅ WIN" if (res == 'HOME_TEAM' and h_api in item['pick'].lower()) else "❌ LOSS"
                            actualizados += 1
        if actualizados > 0:
            await guardar_en_github(historial_completo=historial)
            await bot.edit_message_text(f"✅ {actualizados} actualizados.", message.chat.id, msg.message_id)
        else: await bot.edit_message_text("ℹ️ Sin cambios.", message.chat.id, msg.message_id)
    except: await bot.edit_message_text("❌ Error.", message.chat.id, msg.message_id)

@bot.message_handler(commands=['partidos'])
async def cmd_partidos(message):
    data = await api_football_call("matches?status=SCHEDULED")
    if not data: return
    txt = "📅 **PRÓXIMOS JUEGOS**\n\n"
    for m in data['matches'][:8]:
        dt = datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=OFFSET_JUAREZ)
        txt += f"🕒 `{dt.strftime('%H:%M')}` | **{m['homeTeam']['shortName']} vs {m['awayTeam']['shortName']}**\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['tabla'])
async def cmd_tabla(message):
    data = await api_football_call("standings")
    if not data: return
    txt = "🏆 **TOP 10 LALIGA:**\n"
    for t in data['standings'][0]['table'][:10]:
        txt += f"`{t['position']}.` **{t['team']['shortName']}** ({t['points']} pts)\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    res = requests.get(URL_JSON).json()
    liga = next(iter(res))
    equipos = ", ".join([f"`{e}`" for e in res[liga]['teams'].keys()])
    await bot.reply_to(message, f"📋 **EQUIPOS VÁLIDOS:**\n{equipos}", parse_mode='Markdown')

@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "🛠 **CONFIGURACIÓN DE RED IA**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
async def handle_callbacks(call):
    if call.data.startswith('set_rol_'):
        rol = call.data.split('_')[-1]
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"), InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ"))
        await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith('set_api_'):
        _, _, rol, api = call.data.split('_')
        nodos = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]
        markup = InlineKeyboardMarkup()
        for idx, n in enumerate(nodos): markup.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{idx}"))
        await bot.edit_message_text(f"Nodo {api} para {rol}:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith('sv_n_'):
        _, _, rol, api, idx = call.data.split('_')
        lista = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]
        SISTEMA_IA[rol] = {"api": api, "nodo": lista[int(idx)]}
        markup = InlineKeyboardMarkup()
        if rol == "estratega": markup.add(InlineKeyboardButton("⚖️ AÑADIR AUDITOR", callback_data="set_rol_auditor"))
        markup.add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))
        await bot.edit_message_text(f"✅ {rol.upper()} configurado.", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data == "config_fin":
        await bot.edit_message_text("🚀 **SISTEMA ACTIVADO**", call.message.chat.id, call.message.message_id)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
