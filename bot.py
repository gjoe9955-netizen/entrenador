import os
import asyncio
import logging
import requests
from scipy.stats import poisson
from openai import OpenAI
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# ==================================================
# CONFIGURACIÓN DE LOGS PARA RAILWAY
# ==================================================
load_dotenv()
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()] # Esto asegura que Railway capture los logs
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN_TELEGRAM")
FOOTBALL_DATA_KEY = os.getenv("API_KEY_FOOTBALL")
SAMBA_KEY = os.getenv("SAMBA_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

bot = AsyncTeleBot(TOKEN)
ID_COMPETICION_DEFAULT = 2014  # La Liga

# ==================================================
# SISTEMA DE IA
# ==================================================
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_samba": ["DeepSeek-V3.1", "DeepSeek-V3.1-cb", "DeepSeek-V3.2", "Llama-4-Maverick-17B-128E-Instruct", "Meta-Llama-3.3-70B-Instruct"],
    "nodos_groq": ["llama-3.3-70b-versatile", "groq/compound-mini", "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.1-8b-instant"]
}

PROMTS_SISTEMA = {
    "estratega": """Eres un Analista Cuántico de Apuestas. 
    PROCESAMIENTO: Usa [POISSON], [xG], [CUOTA], [EDGE].
    MATEMÁTICAS: Usa LaTeX. Justifica el Stake según Kelly.
    SALIDA: ANALISIS TÉCNICO | COMPARATIVA xG vs POISSON | DECISIÓN FINAL.""",
    "auditor": """Eres un Gestor de Riesgos. Compara H2H con Edge. Si hay inconsistencia, RECHAZA."""
}

# ==================================================
# FUNCIONES DE CONSULTA (REVISADAS SEGÚN DOCS)
# ==================================================

async def obtener_equipos_liga(comp_id):
    """Obtiene equipos. Railway mostrará el error exacto si falla."""
    url = f"https://api.football-data.org/v4/competitions/{comp_id}/teams"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    
    try:
        logger.info(f"Solicitando equipos para competición: {comp_id}")
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=12)
        
        if r.status_code == 200:
            data = r.json()
            teams = data.get('teams', [])
            logger.info(f"Éxito: {len(teams)} equipos encontrados.")
            return {team['name'].lower(): team['id'] for team in teams}
        
        # LOGS CRÍTICOS PARA RAILWAY
        logger.error(f"FALLO API EQUIPOS: Status {r.status_code}")
        logger.error(f"RESPUESTA API: {r.text}")
        return None
    except Exception as e:
        logger.critical(f"EXCEPCIÓN EN OBTENER_EQUIPOS: {e}")
        return None

async def obtener_data_api(id_equipo):
    """Obtiene datos H2H recientes."""
    # Filtramos por partidos finalizados para obtener xG real
    url = f"https://api.football-data.org/v4/teams/{id_equipo}/matches?status=FINISHED&limit=5"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    
    try:
        logger.info(f"Consultando H2H reciente para ID: {id_equipo}")
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=12)
        
        if r.status_code == 200:
            data = r.json()
            matches = data.get('matches', [])
            if not matches:
                logger.warning(f"No hay partidos recientes para ID: {id_equipo}")
                return None
            
            # Identificar nombre según el ID buscado
            m0 = matches[0]
            nombre = m0['homeTeam']['name'] if m0['homeTeam']['id'] == int(id_equipo) else m0['awayTeam']['name']
            
            # Cálculo de goles (Goles a favor en los últimos 5 partidos)
            goles = 0
            w, e, p = 0, 0, 0
            
            for m in matches:
                es_local = m['homeTeam']['id'] == int(id_equipo)
                goles += m['score']['fullTime']['home'] if es_local else m['score']['fullTime']['away']
                
                win = m['score']['winner']
                if win == 'DRAW': e += 1
                elif (win == 'HOME_TEAM' and es_local) or (win == 'AWAY_TEAM' and not es_local): w += 1
                else: p += 1
                
            xg_reciente = round(goles / len(matches), 2)
            return {"nombre": nombre, "xg": xg_reciente, "h2h": f"{w}-{e}-{p}"}
        
        logger.error(f"FALLO API H2H: Status {r.status_code} para ID {id_equipo}")
        return None
    except Exception as e:
        logger.error(f"EXCEPCIÓN H2H: {e}")
        return None

# ==================================================
# LÓGICA DE CÁLCULO
# ==================================================
def porcentaje(x): return f"{x*100:.2f}%"

def calcular_poisson(exp_l, exp_v):
    prob_l = sum(poisson.pmf(i, exp_l) * sum(poisson.pmf(j, exp_v) for j in range(i)) for i in range(1, 10))
    return round(prob_l, 4)

def criterio_kelly(prob, cuota):
    if cuota <= 1: return 0
    f_star = (prob * cuota - 1) / (cuota - 1)
    return round(max(0, f_star * 100 * 0.25), 2)

async def ejecutar_ia(rol, prompt_data):
    cfg = SISTEMA_IA[rol]
    if not cfg["nodo"]: return "IA No configurada."
    api_key = SAMBA_KEY if cfg["api"] == "SAMBA" else GROQ_KEY
    base_url = "https://api.sambanova.ai/v1" if cfg["api"] == "SAMBA" else "https://api.groq.com/openai/v1"
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        r = await asyncio.to_thread(client.chat.completions.create,
            model=cfg["nodo"],
            messages=[{"role": "system", "content": PROMTS_SISTEMA[rol]},
                      {"role": "user", "content": f"DATASET:\n{prompt_data}"}],
            temperature=0.1, max_tokens=800)
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Error en IA {rol}: {e}")
        return f"Error IA: {str(e)[:50]}"

# ==================================================
# MANEJADORES DE COMANDOS
# ==================================================

@bot.message_handler(commands=['start', 'help'])
async def help_cmd(message):
    txt = "🤖 *BOT ANALISTA V6.1 (Railway Optimized)*\n\n" \
          "🏟 `/equipos` - Listar equipos de la liga.\n" \
          "📊 `/pronostico Local vs Visitante` - Analizar con xG reciente.\n" \
          "⚙️ `/config` - Nodos de IA."
    await bot.reply_to(message, txt, parse_mode="Markdown")

@bot.message_handler(commands=["equipos"])
async def equipos_cmd(message):
    espera = await bot.reply_to(message, "📡 Conectando con Football-Data...")
    mapeo = await obtener_equipos_liga(ID_COMPETICION_DEFAULT)
    
    if mapeo is None:
        return await bot.edit_message_text("❌ Error de API. Revisa los logs en Railway.", message.chat.id, espera.message_id)
    
    tabla = "🏟 **EQUIPOS (ID | NOMBRE)**\n" + "—" * 20 + "\n"
    # Mostrar solo los primeros 20 para no saturar Telegram
    for nombre, id_team in list(mapeo.items())[:25]:
        tabla += f"`{id_team}` | {nombre.title()}\n"
    
    await bot.edit_message_text(tabla, message.chat.id, espera.message_id, parse_mode="Markdown")

@bot.message_handler(commands=["pronostico"])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        return await bot.reply_to(message, "🚨 Configura la IA con /config")
    
    try:
        parts = message.text.replace("/pronostico", "").lower().split(" vs ")
        equipo_l = parts[0].strip()
        equipo_v = parts[1].strip()
    except:
        return await bot.reply_to(message, "Usa: `/pronostico ID vs ID` o `Nombre vs Nombre`", parse_mode="Markdown")

    espera = await bot.reply_to(message, "🔄 Extrayendo H2H y calculando Poisson...")
    
    # Intentamos mapear nombres a IDs
    mapeo = await obtener_equipos_liga(ID_COMPETICION_DEFAULT)
    id_l = mapeo.get(equipo_l, equipo_l) if mapeo else equipo_l
    id_v = mapeo.get(equipo_v, equipo_v) if mapeo else equipo_v

    data_l, data_v = await asyncio.gather(obtener_data_api(id_l), obtener_data_api(id_v))

    if not data_l or not data_v:
        logger.error(f"Fallo en data_l: {data_l} o data_v: {data_v}")
        return await bot.edit_message_text("❌ Error: No se pudieron obtener datos de uno de los equipos.", message.chat.id, espera.message_id)

    # Lógica de cálculo
    prob_l = calcular_poisson(data_l['xg'], data_v['xg'])
    cuota = 1.95 # Valor base para el ejemplo
    edge = (prob_l * cuota) - 1
    stake = criterio_kelly(prob_l, cuota)

    dataset = (f"[POISSON]: {porcentaje(prob_l)}\n"
               f"[xG REC]: {data_l['xg']} vs {data_v['xg']}\n"
               f"[CUOTA]: {cuota}\n"
               f"[EDGE]: {porcentaje(edge)}\n"
               f"[H2H 5-GAMES]: L:{data_l['h2h']} V:{data_v['h2h']}")
    
    est = await ejecutar_ia("estratega", dataset)
    aud = await ejecutar_ia("auditor", f"Data: {dataset}\nEstratega: {est}")

    res = (f"📊 *{data_l['nombre']} vs {data_v['nombre']}*\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"📈 Edge: `{porcentaje(edge)}` | Stake: `{stake}%` \n\n"
           f"🧠 *ESTRATEGA:*\n{est}\n\n🛡 *AUDITOR:*\n{aud}")
    
    await bot.edit_message_text(res, message.chat.id, espera.message_id, parse_mode="Markdown")

# --- Mantenemos tus funciones de /config originales ---
@bot.message_handler(commands=["config"])
async def config_cmd(message):
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 Config Estratega", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ Panel de Configuración:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_rol_"))
async def cb_role(call):
    rol = call.data.split("_")[-1]
    mk = InlineKeyboardMarkup().row(
        InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"),
        InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ")
    )
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_api_"))
async def cb_api(call):
    _, _, rol, api = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    mk = InlineKeyboardMarkup()
    for i, n in enumerate(lista):
        mk.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{i}"))
    await bot.edit_message_text(f"Nodo {api}:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sv_n_"))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    SISTEMA_IA[rol] = {"api": api, "nodo": lista[int(idx)]}
    mk = InlineKeyboardMarkup()
    if rol == "estratega": mk.add(InlineKeyboardButton("🛡 Configurar Auditor", callback_data="set_rol_auditor"))
    mk.add(InlineKeyboardButton("🏁 Finalizar", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} configurado.", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("🚀 Configuración completa.", call.message.chat.id, call.message.message_id)

async def main():
    logger.info("Bot iniciado. Esperando comandos...")
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
