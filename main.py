import feedparser
import json
import os
import time
import requests
from datetime import datetime
import anthropic

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
SEEN_FILE          = "seen_jobs.json"
CHECK_INTERVAL     = 60 * 60 * 3  # cada 3 horas
SCORE_MINIMO       = 6

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
- Disponibilidad: inmediata
- Idiomas: español e inglés
- Zona horaria: UTC-3 (Argentina)
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
    "Dribbble Jobs":        "https://dribbble.com/jobs.rss",
    "Authentic Jobs":       "https://authenticjobs.com/feed/",
    "Jobspresso":           "https://jobspresso.co/feed/",
    "Smashing Magazine":    "https://www.smashingmagazine.com/jobs/feed/",
    "Coroflot":             "https://www.coroflot.com/jobs/rss",
}

# ─────────────────────────────────────────────
# FREELANCER.COM API (sin key)
# ─────────────────────────────────────────────
def fetch_freelancer_api():
    jobs = []
    queries = ["web design", "wordpress", "seo", "frontend", "ui ux", "landing page"]
    for query in queries:
        try:
            url = "https://www.freelancer.com/api/projects/0.1/projects/active/"
            params = {
                "query": query,
                "limit": 10,
                "sort_field": "time_updated",
                "job_details": True,
            }
            headers = {"freelancer-oauth-v1": ""}
            r = requests.get(url, params=params, headers=headers, timeout=10)
            data = r.json()
            projects = data.get("result", {}).get("projects", [])
            for p in projects:
                budget = p.get("budget", {})
                min_b  = budget.get("minimum", 0) or 0
                max_b  = budget.get("maximum", 0) or 0
                jobs.append({
                    "source":  f"Freelancer - {query}",
                    "title":   p.get("title", "Sin título"),
                    "link":    f"https://www.freelancer.com/projects/{p.get('seo_url', '')}",
                    "summary": p.get("description", "")[:800],
                    "id":      str(p.get("id", "")),
                    "budget":  f"USD {int(min_b)}–{int(max_b)}" if max_b else "No especificado",
                })
        except Exception as e:
            print(f"Error Freelancer API ({query}): {e}")
        time.sleep(1)
    return jobs

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

def fetch_rss(feed_name, url):
    try:
        feed = feedparser.parse(url)
        jobs = []
        for entry in feed.entries[:15]:
            jobs.append({
                "source":  feed_name,
                "title":   entry.get("title", "Sin título"),
                "link":    entry.get("link", ""),
                "summary": entry.get("summary", entry.get("description", ""))[:800],
                "id":      entry.get("id", entry.get("link", "")),
                "budget":  "No especificado",
            })
        return jobs
    except Exception as e:
        print(f"Error RSS {feed_name}: {e}")
        return []

def is_fulltime(title, summary):
    keywords = [
        "full-time", "full time", "permanent", "salary", "benefits",
        "pto", "health insurance", "equity", "stock options",
        "associate", "director", "vp of", "head of", "staff ",
        "relación de dependencia", "tiempo completo"
    ]
    text = (title + " " + summary).lower()
    return any(k in text for k in keywords)

def score_job(job):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Evaluá si esta oferta es un PROYECTO FREELANCE relevante para el siguiente perfil.

PERFIL:
{MI_PERFIL}

OFERTA:
Título: {job['title']}
Fuente: {job['source']}
Presupuesto: {job.get('budget', 'No especificado')}
Descripción: {job['summary']}

REGLAS DE SCORING:
- Si la oferta es un empleo full-time o relación de dependencia: score máximo 3
- Si el presupuesto es menor a USD 300 o muy bajo: score máximo 4
- Si matchea bien el perfil y es proyecto freelance puntual: score 7-10
- Priorizá proyectos de diseño web, WordPress, SEO, landing pages, UI/UX, frontend

Respondé SOLO con este JSON en una línea, sin texto antes ni después, sin backticks:
{{"score": 7, "motivo": "ejemplo de motivo", "presupuesto_ok": true, "es_freelance": true}}"""

    raw = ""
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return {"score": 0, "motivo": "Sin respuesta JSON", "presupuesto_ok": False, "es_freelance": False}
        return json.loads(raw[start:end])
    except Exception as e:
        print(f"Error scoring: {e} | Raw: {raw[:100]}")
        return {"score": 0, "motivo": "Error al evaluar", "presupuesto_ok": False, "es_freelance": False}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  TELEGRAM_CHAT_ID,
        "text":                     message,
        "parse_mode":               "Markdown",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Error Telegram: {e}")

def format_message(job, evaluation):
    score       = evaluation.get("score", 0)
    motivo      = evaluation.get("motivo", "")
    estrellas   = "⭐" * min(score, 5)
    presupuesto = "✅ Presupuesto ok" if evaluation.get("presupuesto_ok") else "⚠️ Verificar presupuesto"
    budget_str  = f"\n💰 {job['budget']}" if job.get("budget") and job["budget"] != "No especificado" else ""

    return f"""{estrellas} *Score {score}/10*
📌 *{job['title']}*
🌐 {job['source']}{budget_str}
💬 _{motivo}_
{presupuesto}

🔗 [Ver oferta]({job['link']})""".strip()

# ─────────────────────────────────────────────
# LOOP PRINCIPAL
# ─────────────────────────────────────────────
def run():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Iniciando chequeo...")
    seen   = load_seen()
    nuevos = 0
    todos  = []

    # RSS feeds
    for feed_name, url in RSS_FEEDS.items():
        todos += fetch_rss(feed_name, url)
        time.sleep(1)

    # Freelancer.com API
    todos += fetch_freelancer_api()

    print(f"  Total ofertas encontradas: {len(todos)}")

    for job in todos:
        if job["id"] in seen:
            continue
        seen.add(job["id"])

        # Filtro rápido antes de llamar a la API
        if is_fulltime(job["title"], job["summary"]):
            print(f"  [skip] {job['title'][:60]} (full-time detectado)")
            continue

        evaluation = score_job(job)
        score      = evaluation.get("score", 0)

        print(f"  [{score}/10] {job['title'][:60]}...")

        if score >= SCORE_MINIMO:
            msg = format_message(job, evaluation)
            send_telegram(msg)
            nuevos += 1
            time.sleep(1)

    save_seen(seen)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Listo. {nuevos} ofertas enviadas.\n")

if __name__ == "__main__":
    run()
    while True:
        time.sleep(CHECK_INTERVAL)
        run()