def obtener_cuotas_reales(local, visitante):
    if not ODDS_API_KEY: 
        logger.warning("[ODDS] No hay ODDS_API_KEY configurada.")
        return None
        
    ligas = ["soccer_spain_la_liga", "soccer_spain_segunda_division"]
    try:
        for liga in ligas:
            logger.info(f"[ODDS] Consultando API para liga: {liga}")
            url = f"https://api.the-odds-api.com/v1/sports/{liga}/odds/"
            params = {
                "apiKey": ODDS_API_KEY, 
                "regions": "eu", 
                "markets": "h2h", 
                "oddsFormat": "decimal"
            }
            r = requests.get(url, params=params, timeout=10)
            
            if r.status_code != 200:
                logger.error(f"[ODDS] Error API ({r.status_code}): {r.text}")
                continue
                
            data = r.json()
            logger.info(f"[ODDS] Se recibieron {len(data)} partidos de {liga}")
            
            for match in data:
                h_api, a_api = match['home_team'].lower(), match['away_team'].lower()
                l_busq, v_busq = local.lower(), visitante.lower()
                
                # Log de depuración para ver por qué no empareja
                logger.info(f"[ODDS] Comparando: [{l_busq} vs {v_busq}] con API: [{h_api} vs {a_api}]")
                
                # Búsqueda flexible
                if (l_busq in h_api or h_api in l_busq) and (v_busq in a_api or a_api in v_busq):
                    logger.info(f"[ODDS] ✅ ¡Match encontrado!")
                    bookie = match['bookmakers'][0]
                    cuotas = bookie['markets'][0]['outcomes']
                    res_cuotas = {}
                    for o in cuotas:
                        if o['name'] == match['home_team']: res_cuotas['L'] = o['price']
                        elif o['name'] == match['away_team']: res_cuotas['V'] = o['price']
                        else: res_cuotas['E'] = o['price']
                    return {"bookie": bookie['title'], "precios": res_cuotas}
        
        logger.warning(f"[ODDS] No se encontró el partido {local} vs {visitante} en ninguna liga.")
        return None
    except Exception as e:
        logger.error(f"[ODDS] Error crítico: {e}")
        return None
