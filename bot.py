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
    "vivos": {"GEMINI": [], "GROQ": []} # Aquí solo entrarán los que pasen el test matemático
}

# --- Prueba de Aptitud Matemática ---
async def test_aptitud_matematica(api, nodo):
    """
    Solicita un cálculo de Poisson simple para verificar si el nodo 
    está 'vivo' y si es capaz de razonar matemáticamente.
    """
    prompt_test = "Responde solo el numero: Si lambda es 2.0, cual es la probabilidad de x=0 en Poisson? (Punto decimal)"
    # La respuesta correcta es ~0.135
    
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

# --- Comando de Escaneo (Con Test de Aptitud) ---
@bot.message_handler(commands=['scan_nodos'])
async def scan_nodos(message):
    msg = await bot.reply_to(message, "📡 **INICIANDO TEST DE APTITUD MATEMÁTICA...**\n(Esperando 10s por nodo + Delays de seguridad)")
    SISTEMA_IA["vivos"] = {"GEMINI": [], "GROQ": []}
    reporte = "🔎 **ESTADO DE NODOS (TEST POISSON):**\n\n"

    # Escaneo Gemini
    reporte += "✨ **RED GEMINI:**\n"
    for n in SISTEMA_IA["candidatos"]["GEMINI"]:
        start = time.time()
        # Test de aptitud en lugar de simple ping
        if await test_aptitud_matematica('GEMINI', n):
            SISTEMA_IA["vivos"]["GEMINI"].append(n)
            reporte += f"✅ `{n}` - APTO ({time.time()-start:.1f}s)\n"
        else:
            reporte += f"❌ `{n}` - NO APTO/OFFLINE\n"
        await asyncio.sleep(1.5) # Delay para enfriar la API
    
    # Escaneo Groq
    reporte += "\n⚡ **RED GROQ:**\n"
    for n in SISTEMA_IA["candidatos"]["GROQ"]:
        start = time.time()
        if await test_aptitud_matematica('GROQ', n):
            SISTEMA_IA["vivos"]["GROQ"].append(n)
            reporte += f"✅ `{n}` - APTO ({time.time()-start:.1f}s)\n"
        else:
            reporte += f"❌ `{n}` - NO APTO/OFFLINE\n"
        await asyncio.sleep(2.5) # Mayor delay para Groq

    reporte += "\n⚠️ *Usa /config para asignar los roles solo con nodos APTOS.*"
    await bot.edit_message_text(reporte, message.chat.id, msg.message_id, parse_mode='Markdown')

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return "⚠️ Nodo no configurado."
    
    if config["api"] == 'GEMINI':
        client = genai.Client(api_key=GEMINI_KEY)
        try:
            res = await asyncio.to_thread(
                client.models.generate_content, 
                model=config["nodo"], 
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1)
            )
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

# --- Lógica de Pronósticos (Sin cambios en Poisson) ---
@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 **SISTEMA BLOQUEADO:** Debes ejecutar `/scan_nodos` y configurar un nodo APTO en `/config` primero."); return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Formato: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, f"📡 Analizando con nodo {SISTEMA_IA['estratega']['nodo']}...")

    # ... (Resto de la lógica de Poisson y APIs de fútbol igual que la versión anterior)
    # Por brevedad en esta respuesta, asumo la continuidad de la lógica de cálculo
    await bot.edit_message_text("📊 Procesando datos estadísticos...", message.chat.id, msg_espera.message_id)
    # [Lógica Poisson omitida para enfoque en la gestión de nodos]
    # ... 

# --- Gestión de Nodos por Selección ---
@bot.message_handler(commands=['config'])
async def cmd_config(message):
    if not SISTEMA_IA["vivos"]["GEMINI"] and not SISTEMA_IA["vivos"]["GROQ"]:
        await bot.reply_to(message, "⚠️ **ERROR:** No hay nodos APTOS en memoria. Ejecuta `/scan_nodos` primero."); return
    
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ **CONFIGURACIÓN DINÁMICA**\nSolo se muestran modelos que pasaron el test matemático.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rol_'))
async def cb_rol(call):
    rol = call.data.split('_')[-1]
    markup = InlineKeyboardMarkup().row(
        InlineKeyboardButton("Red Gemini", callback_data=f"set_api_{rol}_GEMINI"),
        InlineKeyboardButton("Red Groq", callback_data=f"set_api_{rol}_GROQ")
    )
    await bot.edit_message_text(f"Selecciona API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

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
    
    await bot.answer_callback_query(call.id, f"Verificando {nodo} una última vez...")
    # Verificación final antes de guardar
    if await test_aptitud_matematica(api, nodo):
        SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))
        await bot.edit_message_text(f"🚀 **{rol.upper()} ASIGNADO**\nNodo: `{nodo}`\nEstado: Verificado y APTO.", call.message.chat.id, call.message.message_id, reply_markup=markup)
    else:
        await bot.answer_callback_query(call.id, "❌ Falló el test de último segundo. El nodo está inestable.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("✅ **SISTEMA CONFIGURADO CON NODOS VIVOS**", call.message.chat.id, call.message.message_id)

async def main(): await bot.polling(non_stop=True)
if __name__ == "__main__": asyncio.run(main())
