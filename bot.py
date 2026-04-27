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

# Variables de Entorno
TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN') 
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"

bot = AsyncTeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)

# --- MOTOR DE MODELOS DINÁMICOS ---
# Esto permite que el comando /test funcione probando nodos activos
MODELS_TO_TEST = ["gemini-1.5-flash", "gemini-1.5-pro"]

async def testear_modelos_ia():
    results = []
    for model_name in MODELS_TO_TEST:
        try:
            m = genai.GenerativeModel(model_name)
            start = datetime.now()
            m.generate_content("ping")
            end = datetime.now()
            latency = (end - start).total_seconds()
            results.append({"model": model_name, "status": "✅ ONLINE", "latencia": f"{latency:.2f}s"})
        except Exception:
            results.append({"model": model_name, "status": "❌ OFFLINE", "latencia": "N/A"})
    return results

# --- Lógica Matemática ---

def ajuste_dixon_coles(x, y, lh, la, rho=-0.15):
    if x == 0 and y == 0: return 1 - (lh * la * rho)
    if x == 0 and y == 1: return 1 + (lh * rho)
    if x == 1 and y == 0: return 1 + (la * rho)
    if x == 1 and y == 1: return 1 - rho
    return 1.0

def calcular_probabilidades(local, visitante, data):
    stats = data['LaLiga']['teams']
    avg = data['LaLiga']['averages']
    s_l, s_v = stats[local], stats[visitante]
    
    lh = s_l['att_h'] * s_v['def_a'] * avg['league_home']
    la = s_v['att_a'] * s_l['def_h'] * avg['league_away']
    
    ph, pd, pa = 0, 0, 0
    for x in range(7):
        for y in range(7):
            p = (poisson.pmf(x, lh) * poisson.pmf(y, la)) * ajuste_dixon_coles(x, y, lh, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p
    return {"lh": lh, "la": la, "p_h": ph, "p_d": pd, "p_a": pa}

def obtener_datos_poisson():
    try:
        r = requests.get(URL_JSON, timeout=10)
        return r.json()
    except: return None

async def guardar_en_historial(partido, pick, analisis):
    if not GITHUB_TOKEN: return
    try:
        url_gh = f"https://api.github.com/repos/{REPO_PATH}/contents/{HISTORIAL_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        r = requests.get(url_gh, headers=headers)
        sha = r.json()['sha'] if r.status_code == 200 else None
        content = json.loads(base64.b64decode(r.json()['content']).decode('utf-8')) if sha else []
        
        content.append({
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "partido": partido,
            "pick_pronosticado": pick,
            "analisis_resumen": analisis[:300] + "...",
            "resultado_real": "Pendiente"
        })
        
        new_b64 = base64.b64encode(json.dumps(content, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')
        payload = {"message": f"Nuevo pick: {partido}", "content": new_b64, "sha": sha}
        requests.put(url_gh, headers=headers, json=payload)
    except Exception as e: logger.error(f"Error historial: {e}")

# --- Handlers de Comandos ---

@bot.message_handler(commands=['start'])
async def cmd_start(message):
    await bot.reply_to(message, "🚀 **Motor Poisson Activo**\n/predecir - Nuevo análisis\n/test - Test de Nodos IA\n/historial - Ver picks\n/help - Info técnica")

@bot.message_handler(commands=['test'])
async def cmd_test(message):
    sent = await bot.reply_to(message, "🔍 Testeando latencia de nodos Gemini...")
    nodos = await testear_modelos_ia()
    respuesta = "📊 **ESTADO DE NODOS IA:**\n\n"
    for n in nodos:
        respuesta += f"• `{n['model']}`: {n['status']} ({n['latencia']})\n"
    await bot.edit_message_text(respuesta, message.chat.id, sent.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
async def cmd_help(message):
    help_text = """
🛠 **SOPORTE TÉCNICO**
• `/predecir`: Inicia motor Poisson + Dixon-Coles.
• `/test`: Verifica qué modelo de Gemini responde más rápido.
• `/historial`: Consulta resultados en GitHub.
• `/equipos`: Lista de equipos cargados en el JSON.
    """
    await bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if data:
        lista = "\n".join([f"• {t}" for t in sorted(data['LaLiga']['teams'].keys())])
        await bot.reply_to(message, f"📋 **EQUIPOS EN SISTEMA:**\n\n{lista}", parse_mode='Markdown')

@bot.message_handler(commands=['predecir'])
async def cmd_predecir(message):
    data = obtener_datos_poisson()
    if not data:
        await bot.reply_to(message, "❌ Error: No hay datos de Poisson disponibles.")
        return
    markup = InlineKeyboardMarkup()
    teams = sorted(data['LaLiga']['teams'].keys())
    for i in range(0, len(teams), 2):
        row = [InlineKeyboardButton(teams[i], callback_query_data=f"L:{teams[i]}")]
        if i+1 < len(teams): row.append(InlineKeyboardButton(teams[i+1], callback_query_data=f"L:{teams[i+1]}"))
        markup.add(*row)
    await bot.send_message(message.chat.id, "🏟 Selecciona el equipo **LOCAL**:", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: True)
async def callback_query(call):
    data = obtener_datos_poisson()
    if call.data.startswith("L:"):
        local = call.data.split(":")[1]
        markup = InlineKeyboardMarkup()
        teams = sorted(data['LaLiga']['teams'].keys())
        for i in range(0, len(teams), 2):
            t1, t2 = teams[i], teams[i+1] if i+1 < len(teams) else None
            row = [InlineKeyboardButton(t1, callback_query_data=f"V:{local}:{t1}")]
            if t2: row.append(InlineKeyboardButton(t2, callback_query_data=f"V:{local}:{t2}"))
            markup.add(*row)
        await bot.edit_message_text(f"🏠 Local: **{local}**\nSelecciona el **VISITANTE**:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

    elif call.data.startswith("V:"):
        _, local, visitante = call.data.split(":")
        sent = await bot.edit_message_text(f"⏳ Analizando con Dixon-Coles: {local} vs {visitante}...", call.message.chat.id, call.message.message_id)
        res = calcular_probabilidades(local, visitante, data)
        
        # Selección automática del mejor modelo para la predicción
        ia_model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Analista Pro LaLiga. Poisson: {local} vs {visitante}. Lambdas: H {res['lh']:.2f}, A {res['la']:.2f}. Probs: L {res['p_h']:.1%}, E {res['p_d']:.1%}, V {res['p_a']:.1%}. Da pick de Value y Marcador."
        
        try:
            response = ia_model.generate_content(prompt)
            await bot.edit_message_text(f"🏟 **{local} vs {visitante}**\n\n{response.text}", call.message.chat.id, sent.message_id, parse_mode='Markdown')
            await guardar_en_historial(f"{local} vs {visitante}", "Análisis Pro", response.text)
        except Exception as e:
            await bot.edit_message_text(f"❌ Error en IA: {e}", call.message.chat.id, sent.message_id)

@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    url_hist = f"https://raw.githubusercontent.com/{REPO_PATH}/main/{HISTORIAL_FILE}"
    r = requests.get(url_hist)
    if r.status_code == 200:
        logs = r.json()[-5:]
        texto = "📜 **ÚLTIMOS PICKS:**\n\n"
        for l in logs: texto += f"• {l['partido']}: {l.get('resultado_real', 'Pendiente')}\n"
        await bot.reply_to(message, texto, parse_mode='Markdown')
    else: await bot.reply_to(message, "📭 Historial no encontrado.")

if __name__ == "__main__":
    logger.info("🚀 Bot iniciado con motor de testeo...")
    asyncio.run(bot.polling())
