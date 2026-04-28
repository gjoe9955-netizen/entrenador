# BOT ANALISTA V5.5 FOOTBALL PRO FULL
# Estable / Profesional / Debate IA / Value Betting / Kelly / H2H / Odds / Poisson

import os
import json
import asyncio
import logging
import requests
import base64
import io
import unicodedata
import pandas as pd

from scipy.stats import poisson
from datetime import datetime, timedelta, timezone

from openai import OpenAI
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# ==================================================
# CONFIG
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

load_dotenv()

TOKEN = os.getenv("TOKEN_TELEGRAM")
FOOTBALL_DATA_KEY = os.getenv("API_KEY_FOOTBALL")
ODDS_API_KEY = os.getenv("API_KEY_ODDS")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

OFFSET_JUAREZ = -6

REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# ==================================================
# MAPEO EQUIPOS
# ==================================================

MAPEO_EQUIPOS = {
    "Athletic": "Athletic",
    "Atleti": "Atleti",
    "Osasuna": "Osasuna",
    "Espanyol": "Espanyol",
    "Barça": "Barça",
    "Getafe": "Getafe",
    "Real Madrid": "Real Madrid",
    "Rayo Vallecano": "Rayo Vallecano",
    "Levante": "Levante",
    "Mallorca": "Mallorca",
    "Real Betis": "Real Betis",
    "Real Sociedad": "Real Sociedad",
    "Villarreal": "Villarreal",
    "Valencia": "Valencia",
    "Alavés": "Alavés",
    "Elche": "Elche",
    "Girona": "Girona",
    "Celta": "Celta",
    "Sevilla FC": "Sevilla FC",
    "Real Oviedo": "Real Oviedo",

    "athletic club": "Athletic",
    "bilbao": "Athletic",
    "atletico": "Atleti",
    "atletico madrid": "Atleti",
    "ath madrid": "Atleti",
    "barcelona": "Barça",
    "barca": "Barça",
    "fc barcelona": "Barça",
    "betis": "Real Betis",
    "sociedad": "Real Sociedad",
    "la real": "Real Sociedad",
    "vallecano": "Rayo Vallecano",
    "rayo": "Rayo Vallecano",
    "alaves": "Alavés",
    "sevilla": "Sevilla FC",
    "espanyol": "Espanyol",
    "espanol": "Espanyol",
    "oviedo": "Real Oviedo"
}

# ==================================================
# IA CONFIG
# ==================================================

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

# ==================================================
# UTILIDADES
# ==================================================

def normalizar(txt):
    txt = txt.lower()
    txt = ''.join(
        c for c in unicodedata.normalize('NFD', txt)
        if unicodedata.category(c) != 'Mn'
    )
    for word in ["fc", "cf", "club", "real", "de", "the", "rcd"]:
        txt = txt.replace(f" {word} ", " ")
        txt = txt.replace(f"{word} ", "")
        txt = txt.replace(f" {word}", "")
    return txt.strip()

def limpiar_markdown(texto):
    if not texto: return ""
    for c in ["*", "_", "`", "[", "]", "(", ")"]:
        texto = texto.replace(c, "")
    return texto

def porcentaje(x):
    return f"{x*100:.2f}%"

# ==================================================
# FOOTBALL-DATA ENGINE (INTEGRACIÓN LOCAL JSON)
# ==================================================

async def obtener_datos_football_data(q_local, q_visita):
    # Intentar cargar datos desde el JSON local generado por GitHub Actions
    datos_locales = None
    if os.path.exists("liga_data.json"):
        try:
            with open("liga_data.json", "r", encoding="utf-8") as f:
                datos_locales = json.load(f)
            logging.info("Utilizando datos locales de liga_data.json")
        except Exception as e:
            logging.error(f"Error al leer liga_data.json: {e}")

    if datos_locales:
        try:
            id_l, id_v = None, None
            stats = {"l": {"att": 1.2, "def": 1.0}, "v": {"att": 1.0, "def": 1.2}}
            
            for team in datos_locales.get("standings", []):
                name_api = team["team"]["shortName"]
                if q_local.lower() in name_api.lower() or name_api.lower() in q_local.lower():
                    id_l = team["team"]["id"]
                    stats["l"]["att"] = team["goalsFor"] / team["playedGames"] if team["playedGames"] > 0 else 1.2
                    stats["l"]["def"] = team["goalsAgainst"] / team["playedGames"] if team["playedGames"] > 0 else 1.0
                if q_visita.lower() in name_api.lower() or name_api.lower() in q_visita.lower():
                    id_v = team["team"]["id"]
                    stats["v"]["att"] = team["goalsFor"] / team["playedGames"] if team["playedGames"] > 0 else 1.0
                    stats["v"]["def"] = team["goalsAgainst"] / team["playedGames"] if team["playedGames"] > 0 else 1.2

            if id_l and id_v:
                gl, gv, emp = 0, 0, 0
                for m in datos_locales.get("matches", []):
                    if m["status"] == "FINISHED":
                        h_id = m["homeTeam"]["id"]
                        a_id = m["awayTeam"]["id"]
                        if (h_id == id_l and a_id == id_v) or (h_id == id_v and a_id == id_l):
                            if m["score"]["winner"] == "DRAW": emp += 1
                            elif m["score"]["winner"] == "HOME_TEAM":
                                if h_id == id_l: gl += 1
                                else: gv += 1
                            elif m["score"]["winner"] == "AWAY_TEAM":
                                if a_id == id_l: gl += 1
                                else: gv += 1

                h2h_txt = f"{q_local} {gl} | Emp {emp} | {q_visita} {gv} (JSON)"
                return h2h_txt, stats["l"]["att"], stats["l"]["def"], stats["v"]["att"], stats["v"]["def"], True
        except Exception as e:
            logging.error(f"Error procesando JSON local: {e}")

    # BACKUP: API EXTERNA SI EL JSON FALLA O NO EXISTE
    logging.info("JSON no disponible, consultando API externa...")
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    base_url = "https://api.football-data.org/v4"
    try:
        url_pd = f"{base_url}/competitions/PD/standings"
        res_pd = requests.get(url_pd, headers=headers, timeout=10).json()
        id_l, id_v = None, None
        stats = {"l": {"att": 1.2, "def": 1.0}, "v": {"att": 1.0, "def": 1.2}}
        if "standings" in res_pd:
            tabla = res_pd["standings"][0]["table"]
            for team in tabla:
                name_api = team["team"]["shortName"]
                if q_local.lower() in name_api.lower() or name_api.lower() in q_local.lower():
                    id_l = team["team"]["id"]
                    stats["l"]["att"] = team["goalsFor"] / team["playedGames"]
                    stats["l"]["def"] = team["goalsAgainst"] / team["playedGames"]
                if q_visita.lower() in name_api.lower() or name_api.lower() in q_visita.lower():
                    id_v = team["team"]["id"]
                    stats["v"]["att"] = team["goalsFor"] / team["playedGames"]
                    stats["v"]["def"] = team["goalsAgainst"] / team["playedGames"]
        if not id_l or not id_v:
            return "Equipos no identificados", 1.2, 1.0, 1.0, 1.2, False
        await asyncio.sleep(1.2) 
        url_h2h = f"{base_url}/matches?teams={id_l},{id_v}&status=FINISHED"
        res_h2h = requests.get(url_h2h, headers=headers, timeout=10).json()
        gl, gv, emp = 0, 0, 0
        if "matches" in res_h2h:
            for m in res_h2h["matches"][-5:]:
                if m["score"]["winner"] == "DRAW": emp += 1
                elif m["homeTeam"]["id"] == id_l:
                    if m["score"]["winner"] == "HOME_TEAM": gl += 1
                    else: gv += 1
                else:
                    if m["score"]["winner"] == "HOME_TEAM": gv += 1
                    else: gl += 1
        return f"{q_local} {gl} | Emp {emp} | {q_visita} {gv} (API)", stats["l"]["att"], stats["l"]["def"], stats["v"]["att"], stats["v"]["def"], True
    except Exception as e:
        logging.error(f"Error FD API: {e}")
        return "Error API", 1.2, 1.0, 1.0, 1.2, False

# ==================================================
# IA ENGINE
# ==================================================

async def ejecutar_ia(rol, prompt):
    cfg = SISTEMA_IA[rol]
    if not cfg["nodo"]: return None
    s_key = os.getenv("SAMBA_KEY") or os.getenv("SAMBANOVA_API_KEY")
    g_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY")
    api_key = s_key if cfg["api"] == "SAMBA" else g_key
    base_url = "https://api.sambanova.ai/v1" if cfg["api"] == "SAMBA" else "https://api.groq.com/openai/v1"

    prompts = {
        "estratega": """Eres trader profesional de apuestas deportivas. Analiza: 1. Poisson 2. H2H 3. Cuotas 4. Prob. Implícita 5. Edge 6. Kelly. Formato: ANALISIS: MERCADO: DECISION FINAL:""",
        "auditor": """Eres auditor profesional bankroll. Destruye picks débiles. Evalúa riesgo y veredicto."""
    }

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        r = await asyncio.to_thread(
            client.chat.completions.create,
            model=cfg["nodo"],
            messages=[{"role": "system", "content": prompts[rol]}, {"role": "user", "content": prompt}],
            temperature=0.1
        )
        return limpiar_markdown(r.choices[0].message.content)
    except Exception as e:
        return f"Error IA {rol}: {str(e)[:80]}"

# ==================================================
# GITHUB DATA
# ==================================================

async def guardar_en_github(registro):
    if not GITHUB_TOKEN: return
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        historial = []
        sha = None
        if r.status_code == 200:
            data = r.json()
            sha = data["sha"]
            historial = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
        historial.append(registro)
        content = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode("utf-8")).decode("utf-8")
        payload = {"message": "update historial", "content": content, "sha": sha}
        requests.put(url, headers=headers, json=payload, timeout=10)
    except: pass

async def obtener_historial_github():
    if not GITHUB_TOKEN: return []
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return json.loads(base64.b64decode(data["content"]).decode("utf-8"))
    except: pass
    return []

# ==================================================
# ODDS API (PLACEHOLDER)
# ==================================================

async def obtener_datos_mercado():
    return 1.85, 3.50, 4.00, True

# ==================================================
# COMANDOS PRINCIPALES
# ==================================================

@bot.message_handler(commands=["pronostico", "valor"])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Usa /config primero.")
        return
    partes = message.text.split(maxsplit=1)
    if len(partes) < 2 or " vs " not in partes[1].lower():
        await bot.reply_to(message, "Uso: /pronostico Local vs Visitante")
        return
    q_local, q_visita = partes[1].split(" vs ")
    espera = await bot.reply_to(message, "📡 Analizando mercado profesional...")
    try:
        h2h_txt, att_l, def_l, att_v, def_v, ok_api = await obtener_datos_football_data(q_local, q_visita)
        mu_l, mu_v = att_l * def_v, att_v * def_l
        ph = sum(poisson.pmf(x, mu_l) * poisson.pmf(y, mu_v) for x in range(7) for y in range(7) if x > y)
        cuota_l, cuota_e, cuota_v, ok_odds = await obtener_datos_mercado()
        p_imp = 1 / cuota_l
        edge = ph - p_imp
        kelly = ((cuota_l * ph) - 1) / (cuota_l - 1) if edge > 0 else 0
        stake = round(max(0, min(kelly * 0.25 * 100, 5)), 2)
        checks = f"{'✅' if ok_odds else '❌'} Odds  ✅ Poisson  {'✅' if ok_api else '❌'} H2H"
        if edge <= 0: verdict = "❌ NO BET"
        elif edge < 0.02: verdict = "⚠️ VALUE BAJO"
        elif edge < 0.05: verdict = "✅ APUESTA MODERADA"
        else: verdict = "🔥 VALUE FUERTE"
        prompt = f"Partido: {q_local} vs {q_visita}\nPoisson: {porcentaje(ph)}\nCuota: {cuota_l}\nEdge: {porcentaje(edge)}\nKelly: {stake}%\nH2H: {h2h_txt}"
        estratega = await ejecutar_ia("estratega", prompt)
        auditor = await ejecutar_ia("auditor", prompt) if SISTEMA_IA["auditor"]["nodo"] else "No configurado"
        texto = (f"📊 *{q_local} vs {q_visita}*\n\n{checks}\n\n⚽ Prob: `{porcentaje(ph)}` | 💰 Cuota: `{cuota_l}`\n📉 Imp: `{porcentaje(p_imp)}` | 📈 Edge: `{porcentaje(edge)}`\n🏦 Kelly: `{stake}%` | 📚 H2H: `{h2h_txt}`\n\n🧠 *ESTRATEGA*\n{estratega}\n\n🛡 *AUDITOR*\n{auditor}\n\n🏁 *VEREDICTO*\n{verdict}")
        await bot.edit_message_text(texto, message.chat.id, espera.message_id, parse_mode="Markdown")
        await guardar_en_github({"fecha": (datetime.now(timezone.utc) + timedelta(hours=OFFSET_JUAREZ)).strftime("%Y-%m-%d %H:%M"), "partido": f"{q_local} vs {q_visita}", "edge": porcentaje(edge), "stake": f"{stake}%", "veredicto": verdict})
    except Exception as e:
        await bot.edit_message_text(f"❌ Error: {e}", message.chat.id, espera.message_id)

@bot.message_handler(commands=["historial"])
async def historial_cmd(message):
    espera = await bot.reply_to(message, "📂 Recuperando registros...")
    datos = await obtener_historial_github()
    if not datos:
        await bot.edit_message_text("📭 Historial vacío.", message.chat.id, espera.message_id)
        return
    txt = "📋 *HISTORIAL RECIENTE*\n\n"
    for d in datos[-10:]:
        txt += f"📅 `{d['fecha']}`\n⚽ {d['partido']}\n📈 Edge: {d['edge']} | 🏦 Stake: {d['stake']}\n🏁 {d['veredicto']}\n\n"
    await bot.edit_message_text(txt, message.chat.id, espera.message_id, parse_mode="Markdown")

# ==================================================
# CONFIGURACIÓN Y AYUDA
# ==================================================

@bot.message_handler(commands=["help", "start"])
async def help_cmd(message):
    txt = ("🤖 *BOT ANALISTA V5.5*\n📊 `/pronostico Local vs Visita`\n📋 `/historial` | ⚙️ `/config`")
    await bot.reply_to(message, txt, parse_mode="Markdown")

@bot.message_handler(commands=["config"])
async def config_cmd(message):
    mk = InlineKeyboardMarkup()
    mk.add(InlineKeyboardButton("🧠 Config Estratega", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ Configura IA", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_rol_"))
async def cb_role(call):
    rol = call.data.split("_")[-1]
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"), InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ"))
    await bot.edit_message_text(f"API para {rol}", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_api_"))
async def cb_api(call):
    _, _, rol, api = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    mk = InlineKeyboardMarkup()
    for i, n in enumerate(lista): mk.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{i}"))
    await bot.edit_message_text("Selecciona nodo:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sv_n_"))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    SISTEMA_IA[rol] = {"api": api, "nodo": lista[int(idx)]}
    mk = InlineKeyboardMarkup()
    if rol == "estratega": mk.add(InlineKeyboardButton("🛡 Añadir Auditor", callback_data="set_rol_auditor"))
    mk.add(InlineKeyboardButton("🏁 Finalizar", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} configurado", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("🚀 Sistema listo.", call.message.chat.id, call.message.message_id)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("BOT INICIADO")
    await bot.polling(non_stop=True, timeout=60)

if __name__ == "__main__":
    asyncio.run(main())
