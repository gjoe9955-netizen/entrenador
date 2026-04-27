import os
import requests
import json
import pandas as pd
import io

# Configuración Football-Data.org
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
URL_API = "https://api.football-data.org/v4/competitions/PD/matches?status=FINISHED"
URL_CSV = "https://www.football-data.co.uk/mmz4281/2526/SP1.csv"
HEADERS = {"X-Auth-Token": API_KEY}

def train_spain():
    if not API_KEY:
        print("❌ ERROR: No se encontró la API KEY.")
        return

    try:
        print("🌐 Consultando resultados en API...")
        response = requests.get(URL_API, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"❌ Error API: {response.status_code}")
            return

        matches = response.json().get('matches', [])
        
        print("📥 Obteniendo volumen de ataque desde CSV (.uk)...")
        res_csv = requests.get(URL_CSV, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        df_csv = pd.read_csv(io.StringIO(res_csv.text)) if res_csv.status_code == 200 else None

        # Mapeo necesario para cruzar fuentes
        mapeo = {
            "Real Madrid CF": "Real Madrid", "FC Barcelona": "Barcelona",
            "Club Atlético de Madrid": "Ath Madrid", "Sevilla FC": "Sevilla",
            "Villarreal CF": "Villarreal", "Real Sociedad de Fútbol": "Real Sociedad",
            "Athletic Club": "Ath Bilbao", "Real Betis Balompié": "Betis",
            "Valencia CF": "Valencia", "Girona FC": "Girona", "Getafe CF": "Getafe",
            "RCD Espanyol de Barcelona": "Espanol", "Rayo Vallecano de Madrid": "Rayo Vallecano",
            "RC Celta de Vigo": "Celta", "RCD Mallorca": "Mallorca", "Real Valladolid CF": "Valladolid",
            "CA Osasuna": "Osasuna", "UD Las Palmas": "Las Palmas", "CD Leganés": "Leganes", "Deportivo Alavés": "Alaves"
        }

        goles = []
        for m in matches:
            if m.get('score') and m['score'].get('fullTime'):
                goles.append({
                    'home': m['homeTeam']['name'],
                    'away': m['awayTeam']['name'],
                    'goals_h': m['score']['fullTime']['home'],
                    'goals_a': m['score']['fullTime']['away']
                })
        
        df = pd.DataFrame(goles)
        avg_h, avg_a = float(df['goals_h'].mean()), float(df['goals_a'].mean())
        
        teams_stats = {}
        teams = pd.unique(df[['home', 'away']].values.ravel())
        
        # Media de tiros a puerta de la liga (aproximado 4.5 para normalizar)
        avg_shots = 4.5

        for team in teams:
            h_df, a_df = df[df['home'] == team], df[df['away'] == team]
            
            # Poisson Base (Goles)
            att_h_goles = h_df['goals_h'].mean() / avg_h if not h_df.empty else 1.0
            att_a_goles = a_df['goals_a'].mean() / avg_a if not a_df.empty else 1.0
            
            # Ajuste de Calidad (Tiros a puerta)
            factor_h, factor_a = 1.0, 1.0
            if df_csv is not None:
                csv_name = mapeo.get(team, team)
                shots_h = df_csv[df_csv['HomeTeam'] == csv_name]['HST'].mean()
                shots_a = df_csv[df_csv['AwayTeam'] == csv_name]['AST'].mean()
                
                if not pd.isna(shots_h): factor_h = shots_h / avg_shots
                if not pd.isna(shots_a): factor_a = shots_a / avg_shots

            # Mezcla: 70% Goles + 30% Tiros
            teams_stats[team] = {
                "att_h": float((att_h_goles * 0.7) + (factor_h * 0.3)),
                "def_h": float(h_df['goals_a'].mean() / avg_a) if not h_df.empty else 1.0,
                "att_a": float((att_a_goles * 0.7) + (factor_a * 0.3)),
                "def_a": float(a_df['goals_h'].mean() / avg_h) if not a_df.empty else 1.0
            }

        output = {
            "LaLiga": {
                "averages": {"league_home": avg_h, "league_away": avg_a},
                "teams": teams_stats,
                "equipo_nombres": sorted(list(teams))
            }
        }

        with open('modelo_poisson.json', 'w') as f:
            json.dump(output, f, indent=4)
        print("✅ Modelo híbrido (Goles + Tiros) generado.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    train_spain()
