import feedparser
import json
import os
import time
import requests
from datetime import datetime
import anthropic

# ─────────────────────────────────────────────
# CONFIGURACIÓN — editá estos valores
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
SEEN_FILE          = "seen_jobs.json"
CHECK_INTERVAL     = 60 * 60 * 3  # cada 3 horas

MI_PERFIL = """
Soy freelancer con 3+ años de experiencia especializado en:

SERVICIOS PRINCIPALES:
- Diseño y desarrollo web completo (HTML, CSS, JavaScript, React)
- Diseño UI/UX en Figma: wireframes, prototipos, design systems
- WordPress: sitios corporativos, tiendas WooCommerce, landing pages de alta conversión
- SEO técnico y on-page: auditorías, optimización, Google Search Console, Analytics
- Email marketing y funnels de conversión

TIPOS DE PROYECTOS QUE HAGO:
- Landing pages y funnels para negocios y productos digitales
- Tiendas ecommerce (WooCommerce, Shopify)
- Sitios web para negocios locales y profesionales
- MVPs y frontends para SaaS y apps web
- Rediseños de sitios existentes con foco en conversión y UX

STACK TÉCNICO:
- Frontend: HTML5, CSS3, JavaScript ES6+, React, Tailwind CSS
- CMS: WordPress, Elementor, ACF
- SEO: Yoast, Ahrefs, Semrush, Core Web Vitals
- Diseño: Figma, Adobe XD

CONDICIONES:
- Presupuesto mínimo: USD 300 por proyecto
- Disponibilidad: proyectos nuevos inmediata
- Idiomas: español e inglés
- Zona horaria: UTC-3 (Argentina)
- Entrega rápida, comunicación clara, revisiones incluidas
"""

# ─────────────────────────────────────────────
# FUENTES RSS
# ─────────────────────────────────────────────
RSS_FEEDS = {
    "RemoteOK - Design":    "https://remoteok.com/remote-design-jobs.rss",
    "RemoteOK - Frontend":  "https://remoteok.com/remote-front-end-jobs.rss",
    "RemoteOK - Marketing": "https://remoteok.com/remote-marketing-jobs.rss",
    "RemoteOK - SEO":       "https://remoteok.com/remote-seo-jobs.rss",
    "Workana - Diseño":     "https://www.workana.com/jobs/rss?category=design-multimedia",
    "Workana - Web":        "https://www.workana.com/jobs/rss?category=web-programming",
    "Workana - Marketing":  "https://www.workana.com/jobs/rss?category=sales-marketing",
    "Jobspresso":           "https://jobspresso.co/feed/",
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
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Evaluá si esta oferta freelance es relevante para el siguiente perfil:

PERFIL:
{MI_PERFIL}

OFERTA:
Título: {job['title']}
Fuente: {job['source']}
Descripción: {job['summary']}

Respondé SOLO con este JSON en una línea, sin texto antes ni después, sin backticks, sin markdown:
{{"score": 7, "motivo": "ejemplo", "presupuesto_ok": true}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        # Extraer JSON aunque venga con texto alrededor
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return {"score": 0, "motivo": "Sin respuesta", "presupuesto_ok": False}
        return json.loads(raw[start:end])
    except Exception as e:
        print(f"Error scoring: {e} | Raw: {raw[:100] if 'raw' in dir() else 'N/A'}")
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
            print(f"      → {job['source']} | {job['link'][:60]}")


            # Solo notificar si score >= 7
            if score >= 5:
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