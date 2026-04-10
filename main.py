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
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
SEEN_FILE           = "seen_jobs.json"
CHECK_INTERVAL      = 60 * 60 * 3  # cada 3 horas
SCORE_MINIMO        = 7
SCORE_PROPUESTA     = 8  # genera propuesta automática si score >= este valor
BUDGET_MINIMO       = 200

MI_PERFIL = """
Soy Gianluca Donato, freelancer con base en Buenos Aires, Argentina.
Trabajo en la intersección entre diseño y desarrollo — puedo llevar
un proyecto desde el wireframe hasta producción sin depender de un
equipo externo.

SERVICIOS PRINCIPALES:
- Desarrollo web completo con Next.js, TypeScript, Tailwind CSS, Supabase
- Diseño UI/UX: landing pages, ecommerce, dashboards, apps web
- Integración de IA en productos web para acelerar desarrollo
- WordPress: sitios corporativos, tiendas, landing pages
- SEO técnico y on-page

PROYECTOS REALES ENTREGADOS:
- Panel de gestión de inventario y analytics para ecommerce en MercadoLibre
  (Next.js, Supabase, Tailwind — stock, listings, escaneo de código de barras)
- Ecommerce completo con checkout Mercado Pago y panel de administración
  (Next.js, Supabase, TypeScript)
- Catálogo web para marcas pequeñas sin complejidad innecesaria
- App de inventario de ropa con navegación entre usuarios

TIPOS DE PROYECTOS QUE BUSCO:
- Landing pages y funnels de conversión
- Tiendas ecommerce (WooCommerce, Shopify, custom)
- Sitios web para negocios, startups y profesionales
- MVPs y frontends para SaaS
- Rediseños con foco en conversión y UX
- Paneles internos y dashboards

CONDICIONES:
- Presupuesto mínimo: USD 300 por proyecto
- Disponibilidad: inmediata
- Idiomas: español e inglés
- Zona horaria: UTC-3 (Argentina)
- Trabajo remoto, comunicación clara, entrega en tiempo
"""

MI_PORTFOLIO = "https://gianluca-donato.vercel.app/en"

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
                "source":     feed_name,
                "title":      entry.get("title", "Sin título"),
                "link":       entry.get("link", ""),
                "summary":    entry.get("summary", entry.get("description", ""))[:800],
                "id":         entry.get("id", entry.get("link", "")),
                "budget":     "No especificado",
                "budget_max": 0,
            })
        return jobs
    except Exception as e:
        print(f"  Error RSS {feed_name}: {e}")
        return []

# ─────────────────────────────────────────────
# FREELANCER.COM API
# ─────────────────────────────────────────────
def fetch_freelancer_api():
    jobs = []
    queries = [
        "web design", "wordpress", "seo", "frontend",
        "landing page", "ui ux design", "ecommerce", "shopify"
    ]
    for query in queries:
        try:
            url = "https://www.freelancer.com/api/projects/0.1/projects/active/"
            params = {
                "query":            query,
                "limit":            10,
                "sort_field":       "time_updated",
                "job_details":      True,
                "full_description": True,
            }
            r        = requests.get(url, params=params, timeout=10)
            data     = r.json()
            result   = data.get("result") or {}
            projects = result.get("projects") or []
            for p in projects:
                budget = p.get("budget") or {}
                min_b  = int(budget.get("minimum") or 0)
                max_b  = int(budget.get("maximum") or 0)
                if max_b > 0 and max_b < BUDGET_MINIMO:
                    continue
                jobs.append({
                    "source":     f"Freelancer - {query}",
                    "title":      p.get("title", "Sin título"),
                    "link":       f"https://www.freelancer.com/projects/{p.get('seo_url', p.get('id', ''))}",
                    "summary":    p.get("description", "")[:800],
                    "id":         f"fl_{p.get('id', '')}",
                    "budget":     f"USD {min_b}–{max_b}" if max_b else "No especificado",
                    "budget_max": max_b,
                })
        except Exception as e:
            print(f"  Error Freelancer ({query}): {e}")
        time.sleep(1)
    return jobs

# ─────────────────────────────────────────────
# GURU RSS
# ─────────────────────────────────────────────
def fetch_guru_rss():
    feeds = {
        "Guru - Web Design":  "https://www.guru.com/jobs/web-design/rss",
        "Guru - Programming": "https://www.guru.com/jobs/programming-development/rss",
        "Guru - SEO":         "https://www.guru.com/jobs/online-marketing/rss",
    }
    jobs = []
    for name, url in feeds.items():
        jobs += fetch_rss(name, url)
        time.sleep(1)
    return jobs

# ─────────────────────────────────────────────
# FILTROS
# ─────────────────────────────────────────────
def is_fulltime(title, summary):
    keywords = [
        "full-time", "full time", "permanent", "salary", "benefits",
        "pto", "health insurance", "equity", "stock options",
        "associate", "director", "vp of", "head of", "staff ",
        "relación de dependencia", "tiempo completo"
    ]
    text = (title + " " + summary).lower()
    return any(k in text for k in keywords)

# ─────────────────────────────────────────────
# SCORING CON IA
# ─────────────────────────────────────────────
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
- Si es empleo full-time o relación de dependencia: score máximo 3
- Si el presupuesto máximo es menor a USD 300: score máximo 4
- Si matchea bien con el perfil y es proyecto freelance puntual: score 7-10
- Priorizá: diseño web, WordPress, SEO, landing pages, UI/UX, Next.js, ecommerce, Shopify

Respondé SOLO con este JSON en una línea, sin texto antes ni después, sin backticks:
{{"score": 7, "motivo": "ejemplo", "presupuesto_ok": true, "es_freelance": true}}"""

    raw = ""
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        raw   = message.content[0].text.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return {"score": 0, "motivo": "Sin JSON", "presupuesto_ok": False, "es_freelance": False}
        return json.loads(raw[start:end])
    except Exception as e:
        print(f"      ERROR scoring: {e} | raw: {raw[:80]}")
        return {"score": 0, "motivo": "Error", "presupuesto_ok": False, "es_freelance": False}

# ─────────────────────────────────────────────
# GENERADOR DE PROPUESTA
# ─────────────────────────────────────────────
def generate_proposal(job):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Detectar idioma del proyecto
    summary_lower = job['summary'].lower()
    title_lower   = job['title'].lower()
    is_spanish    = any(w in summary_lower + title_lower for w in [
        "necesito", "quiero", "busco", "desarrollar", "diseño", "página",
        "sitio", "tienda", "proyecto", "trabajo", "empresa"
    ])
    idioma = "español" if is_spanish else "inglés"

    prompt = f"""Sos Gianluca Donato, freelancer especializado en diseño y desarrollo web.
Escribí una propuesta corta y personalizada para este proyecto en {idioma}.

PERFIL DE GIANLUCA:
{MI_PERFIL}

PROYECTO:
Título: {job['title']}
Presupuesto: {job.get('budget', 'No especificado')}
Descripción: {job['summary']}

REGLAS PARA LA PROPUESTA:
- Máximo 5 líneas, directa y sin relleno
- Primera línea: demostrar que leíste el proyecto (mencioná algo específico)
- Segunda línea: mencionar UN proyecto real similar de tu portfolio
- Tercera línea: decir qué harías concretamente (2-3 puntos específicos)
- Cuarta línea: tiempo estimado y precio aproximado si el presupuesto lo permite
- Última línea: una pregunta que abra la conversación
- NO uses saludos genéricos como "Hi, I'm a developer with X years..."
- NO incluyas el link del portfolio en el texto, va separado
- Tono: profesional pero directo, como hablaría una persona real

Respondé SOLO con el texto de la propuesta, sin explicaciones ni formato extra."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"      ERROR propuesta: {e}")
        return None

# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
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
        print(f"  Error Telegram: {e}")

def format_message(job, evaluation, proposal=None):
    score       = evaluation.get("score", 0)
    motivo      = evaluation.get("motivo", "")
    estrellas   = "⭐" * min(score, 5)
    presupuesto = "✅ Presupuesto ok" if evaluation.get("presupuesto_ok") else "⚠️ Verificar presupuesto"
    budget_str  = f"\n💰 {job['budget']}" if job.get("budget") and job["budget"] != "No especificado" else ""

    msg = f"""{estrellas} *Score {score}/10*
📌 *{job['title']}*
🌐 {job['source']}{budget_str}
💬 _{motivo}_
{presupuesto}

🔗 [Ver oferta]({job['link']})""".strip()

    if proposal:
        msg += f"""

━━━━━━━━━━━━━━━━━━━
✍️ *Propuesta sugerida:*

{proposal}

🌐 {MI_PORTFOLIO}"""

    return msg

# ─────────────────────────────────────────────
# LOOP PRINCIPAL
# ─────────────────────────────────────────────
def run():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Iniciando chequeo...")
    seen   = load_seen()
    nuevos = 0
    todos  = []

    # Workana
    for name, url in {
        "Workana - Diseño":    "https://www.workana.com/jobs/rss?category=design-multimedia",
        "Workana - Web":       "https://www.workana.com/jobs/rss?category=web-programming",
        "Workana - Marketing": "https://www.workana.com/jobs/rss?category=sales-marketing",
        "Workana - IT":        "https://www.workana.com/jobs/rss?category=it-programming",
    }.items():
        todos += fetch_rss(name, url)
        time.sleep(1)

    # Guru
    todos += fetch_guru_rss()

    # Freelancer.com API
    todos += fetch_freelancer_api()

    print(f"  Total ofertas encontradas: {len(todos)}")

    for job in todos:
        if job["id"] in seen:
            continue
        seen.add(job["id"])

        if is_fulltime(job["title"], job["summary"]):
            print(f"  [skip] {job['title'][:60]} (full-time)")
            continue

        evaluation = score_job(job)
        score      = evaluation.get("score", 0)
        print(f"  [{score}/10] {job['title'][:60]}...")

        if score >= SCORE_MINIMO:
            proposal = None
            if score >= SCORE_PROPUESTA:
                print(f"      → Generando propuesta...")
                proposal = generate_proposal(job)

            msg = format_message(job, evaluation, proposal)
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