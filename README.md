# Freelance Bot — Setup en 20 minutos

Bot que monitorea Upwork, Freelancer, Workana, RemoteOK y WeWorkRemotely
y te manda por Telegram solo las ofertas que matchean tu perfil (score ≥ 7/10).

---

## Paso 1 — Crear el bot de Telegram (5 min)

1. Abrí Telegram y buscá `@BotFather`
2. Escribí `/newbot` y seguí las instrucciones
3. Guardá el **token** que te da (formato: `123456:ABC-DEF...`)
4. Abrí tu bot nuevo y escribile cualquier mensaje
5. Entrá a esta URL para obtener tu Chat ID:
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   Buscá `"id":` dentro de `"chat"` — ese número es tu CHAT_ID

---

## Paso 2 — Conseguir API key de OpenAI (5 min)

1. Entrá a https://platform.openai.com/api-keys
2. Creá una API key nueva
3. Guardala (no la vas a poder ver de nuevo)

**Costo estimado:** el bot usa `gpt-4o-mini` (~$0.0001 por oferta evaluada).
Con 500 ofertas/día son menos de **$0.05/día** — prácticamente gratis.

---

## Paso 3 — Deploy en Railway (10 min)

1. Creá cuenta en https://railway.app (gratis, no pide tarjeta)
2. Nuevo proyecto → "Deploy from GitHub repo"
3. Subí estos archivos a un repo de GitHub (puede ser privado)
4. En Railway, en la sección **Variables**, agregá:

```
TELEGRAM_BOT_TOKEN   = tu token del paso 1
TELEGRAM_CHAT_ID     = tu chat id del paso 1
OPENAI_API_KEY       = tu api key del paso 2
```

5. Deploy automático — el bot arranca solo

---

## Personalización

Para cambiar tu perfil o el score mínimo editá `main.py`:

- **Tu perfil:** bloque `MI_PERFIL` al inicio del archivo
- **Score mínimo para notificar:** `if score >= 7` (podés bajarlo a 6 si querés más volumen)
- **Frecuencia de chequeo:** `CHECK_INTERVAL = 60 * 60 * 3` (actualmente cada 3 horas)
- **Agregar más fuentes:** añadí entradas al diccionario `RSS_FEEDS`

---

## Ejemplo de notificación que vas a recibir

```
⭐⭐⭐⭐ Nueva oferta — Score 8/10
📌 Landing page for SaaS product — need UI/UX + dev
🌐 Upwork - Web Design
💬 Proyecto de diseño y frontend, presupuesto mencionado $500
✅ Presupuesto ok

🔗 Ver oferta → [link directo]
```

---

## Estructura de archivos

```
freelance_bot/
├── main.py           ← script principal
├── requirements.txt  ← dependencias Python
├── railway.toml      ← config de deploy
└── seen_jobs.json    ← se crea solo, guarda IDs vistos
```
# freelance-searcher
