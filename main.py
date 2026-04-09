import feedparser
import json
import os
import time
import requests
from datetime import datetime
from openai import OpenAI

# ─────────────────────────────────────────────
# CONFIGURACIÓN — editá estos valores
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY", "")
SEEN_FILE          = "seen_jobs.json"
CHECK_INTERVAL     = 60 * 60 * 3  # cada 3 horas

MI_PERFIL = """
Soy freelancer especializado en:
- Desarrollo web frontend (HTML, CSS, JavaScript, React)
- Diseño UI/UX (Figma, diseño de interfaces, experiencia de usuario)
- WordPress (sitios corporativos, tiendas, landing pages)
- SEO y marketing digital (on-page, técnico, Google Analytics, campañas)
Presupuesto mínimo que acepto: USD 300 por proyecto.
Idiomas: español e inglés.
"""

# ─────────────────────────────────────────────
# FUENTES RSS
# ─────────────────────────────────────────────
RSS_FEEDS = {
    "Upwork - Web Design": "https://www.upwork.com/ab/feed/jobs/rss?q=web+design&sort=recency&api_params=1",
    "Upwork - WordPress":  "https://www.upwork.com/ab/feed/jobs/rss?q=wordpress&sort=recency&api_params=1",
    "Upwork - SEO":        "https://www.upwork.com/ab/feed/jobs/rss?q=seo&sort=recency&api_params=1",
    "Upwork - Frontend":   "https://www.upwork.com/ab/feed/jobs/rss?q=frontend+developer&sort=recency&api_params=1",
    "Freelancer - Web":    "https://www.freelancer.com/rss/job.xml",
    "RemoteOK - Design":   "https://remoteok.com/remote-design-jobs.rss",
    "RemoteOK - Frontend": "https://remoteok.com/remote-front-end-jobs.rss",
    "WeWorkRemotely - Dev":"https://weworkremotely.com/remote-jobs.rss",
    "Workana - Diseño":    "https://www.workana.com/jobs/rss?category=design-multimedia",
    "Workana - Web":       "https://www.workana.com/jobs/rss?category=web-programming",
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def fetch_jobs(feed_name, url):
    try:
        feed = feedparser.parse(url)
        jobs = []
        for entry in feed.entries[:15]:  # últimos 15 por feed
            jobs.append({
                "source": feed_name,
                "title":  entry.get("title", "Sin título"),
                "link":   entry.get("link", ""),
                "summary": entry.get("summary", entry.get("description", ""))[:800],
                "id":     entry.get("id", entry.get("link", "")),
            })
        return jobs
    except Exception as e:
        print(f"Error en {feed_name}: {e}")
        return []

def score_job(job):
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""
Evaluá si esta oferta freelance es relevante para el siguiente perfil:

PERFIL:
{MI_PERFIL}

OFERTA:
Título: {job['title']}
Fuente: {job['source']}
Descripción: {job['summary']}

Respondé SOLO con este JSON (sin texto extra):
{{
  "score": <número del 1 al 10>,
  "motivo": "<una línea explicando por qué sí o por qué no>",
  "presupuesto_ok": <true o false, si el presupuesto parece ser USD 300 o más>
}}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # el más barato, ~$0.0001 por evaluación
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception as e:
        print(f"Error scoring: {e}")
        return {"score": 0, "motivo": "Error al evaluar", "presupuesto_ok": False}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Error Telegram: {e}")

def format_message(job, evaluation):
    score = evaluation.get("score", 0)
    motivo = evaluation.get("motivo", "")
    estrellas = "⭐" * min(score, 5) if score >= 7 else ""
    presupuesto = "✅ Presupuesto ok" if evaluation.get("presupuesto_ok") else "⚠️ Verificar presupuesto"

    return f"""
{estrellas} *Nueva oferta — Score {score}/10*
📌 *{job['title']}*
🌐 {job['source']}
💬 _{motivo}_
{presupuesto}

🔗 [Ver oferta]({job['link']})
""".strip()

# ─────────────────────────────────────────────
# LOOP PRINCIPAL
# ─────────────────────────────────────────────
def run():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Iniciando chequeo...")
    seen = load_seen()
    nuevos = 0

    for feed_name, url in RSS_FEEDS.items():
        jobs = fetch_jobs(feed_name, url)
        for job in jobs:
            if job["id"] in seen:
                continue

            seen.add(job["id"])
            evaluation = score_job(job)
            score = evaluation.get("score", 0)

            print(f"  [{score}/10] {job['title'][:60]}...")

            # Solo notificar si score >= 7
            if score >= 7:
                msg = format_message(job, evaluation)
                send_telegram(msg)
                nuevos += 1
                time.sleep(1)  # evitar flood en Telegram

        time.sleep(2)  # pausa entre feeds

    save_seen(seen)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Listo. {nuevos} ofertas enviadas.\n")

if __name__ == "__main__":
    # Primera corrida inmediata
    run()
    # Luego loop cada 3 horas
    while True:
        time.sleep(CHECK_INTERVAL)
        run()
