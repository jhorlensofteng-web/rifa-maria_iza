import os
import csv
import sqlite3
from io import BytesIO
from datetime import datetime
from contextlib import closing
from flask import Flask, request, redirect, url_for, Response
from flask import render_template_string, abort
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import black, HexColor

# ============================
# Config
# ============================
RAFFLE_TITLE = os.getenv("RAFFLE_TITLE", "Rifa para Casamento de Tatiana e Fernando! Nos ajude!")
TOTAL_NUMBERS = int(os.getenv("TOTAL_NUMBERS", "200"))
ADMIN_KEY = os.getenv("ADMIN_KEY", "valeria_loren")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8083"))
DB_PATH = os.getenv("DB_PATH", "raffle.db")

app = Flask(__name__)

# ============================
# DB Helpers
# ============================
SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    number INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('free','sold')) DEFAULT 'free',
    buyer_name TEXT,
    buyer_contact TEXT,
    paid INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(get_conn()) as conn, conn:
        conn.execute(SCHEMA)
        # Popular números 1..TOTAL_NUMBERS se não existir
        cur = conn.execute("SELECT COUNT(*) AS c FROM tickets")
        count = cur.fetchone()[0]
        # Garantir coluna paid em bases antigas
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
        if "paid" not in columns:
            conn.execute("ALTER TABLE tickets ADD COLUMN paid INTEGER NOT NULL DEFAULT 0")
        if count < TOTAL_NUMBERS:
            existing = set(row[0] for row in conn.execute("SELECT number FROM tickets"))
            to_insert = [n for n in range(1, TOTAL_NUMBERS + 1) if n not in existing]
            now = datetime.utcnow().isoformat()
            conn.executemany(
                "INSERT INTO tickets (number, status, paid, updated_at) VALUES (?,?,?,?)",
                [(n, 'free', 0, now) for n in to_insert]
            )

# Garante que o banco está pronto logo na importação (útil para servidores WSGI).
init_db()

def format_datetime(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value or "-"
    return dt.strftime("%d/%m/%Y %H:%M")

app.jinja_env.filters["format_datetime"] = format_datetime

def build_buyers_pdf(rows):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin_x = 20 * mm
    margin_y = 20 * mm

    pdf.setTitle(f"{RAFFLE_TITLE} — Compradores")

    def draw_header():
        pdf.setFont("Helvetica-Bold", 12)
        pdf.setFillColor(HexColor("#BE123C"))
        pdf.drawString(margin_x, height - margin_y, RAFFLE_TITLE)
        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(black)
        pdf.drawString(margin_x, height - margin_y - 12, f"Relatório de compradores — atualizado em {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}")
        pdf.line(margin_x, height - margin_y - 16, width - margin_x, height - margin_y - 16)

    draw_header()
    y = height - margin_y - 30

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin_x, y, "Número")
    pdf.drawString(margin_x + 40 * mm, y, "Nome")
    pdf.drawString(margin_x + 100 * mm, y, "Contato")
    pdf.drawString(margin_x + 140 * mm, y, "Atualizado")
    pdf.drawString(margin_x + 170 * mm, y, "Status")
    y -= 12

    pdf.setFont("Helvetica", 10)
    for row in rows:
        if y < margin_y + 20:
            pdf.showPage()
            draw_header()
            pdf.setFont("Helvetica-Bold", 11)
            y = height - margin_y - 24
            pdf.drawString(margin_x, y, "Número")
            pdf.drawString(margin_x + 40 * mm, y, "Nome")
            pdf.drawString(margin_x + 100 * mm, y, "Contato")
            pdf.drawString(margin_x + 140 * mm, y, "Atualizado")
            pdf.drawString(margin_x + 170 * mm, y, "Status")
            y -= 12
            pdf.setFont("Helvetica", 10)

        pdf.drawString(margin_x, y, f"#{int(row['number']):03d}")
        pdf.drawString(margin_x + 40 * mm, y, (row["buyer_name"] or "-")[:40])
        pdf.drawString(margin_x + 100 * mm, y, (row["buyer_contact"] or "-")[:25])
        pdf.drawString(margin_x + 140 * mm, y, format_datetime(row["updated_at"]))
        pdf.drawString(margin_x + 170 * mm, y, "Pago" if row["paid"] else "Pendente")
        y -= 14

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


# ============================
# Templates (Tailwind + mobile)
# ============================
BASE_HEAD = f"""
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{RAFFLE_TITLE}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cpath fill='%23e11d48' d='M16 29s-9-5.686-13-11.314C-.432 12.067 1.318 6 6.2 4.226a6.2 6.2 0 0 1 6.8 1.554L16 8.942l3-3.162c2.19-2.307 5.72-2.834 8.4-1.554 4.88 1.774 6.63 7.84 3.2 13.46C25 23.314 16 29 16 29z'/%3E%3C/svg%3E" type="image/svg+xml">
<script src="https://cdn.tailwindcss.com"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap');
  body {{
    font-family: 'Poppins', sans-serif;
  }}
  :root {{
    color-scheme: light;
  }}
  .raffle-card {{
    backdrop-filter: blur(12px);
    border-radius: 2rem;
  }}
  /* --- Tickets --- */
  .ticket {{
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 1.25rem;
    padding: 0.8rem 0;
    font-weight: 600;
    font-size: 0.9rem;
    letter-spacing: 0.08em;
    transition: all 200ms ease;
    box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.5), 0 4px 8px rgba(0,0,0,0.05);
    user-select: none;
  }}
  /* Livre (verde menta) */
  .ticket[data-status="free"] {{
    background: linear-gradient(135deg, #ecfdf5, #d1fae5);
    border: 1px solid rgba(16, 185, 129, 0.3);
    color: #065f46;
  }}
  .ticket[data-status="free"]:hover {{
    transform: translateY(-3px);
    border-color: rgba(16, 185, 129, 0.6);
    box-shadow: 0 6px 12px rgba(16, 185, 129, 0.25);
  }}
  /* Vendido (vermelho rose suave) */
  .ticket[data-status="sold"] {{
    background: linear-gradient(135deg, rgba(251, 113, 133, 0.95), rgba(244, 63, 94, 0.95));
    border: 1px solid rgba(244, 63, 94, 0.4);
    color: #fff1f2;
    box-shadow: 0 8px 16px rgba(244, 63, 94, 0.25);
  }}
  .ticket[data-status="sold"]:hover {{
    transform: translateY(-3px);
    box-shadow: 0 12px 24px rgba(244, 63, 94, 0.35);
  }}
  .buyers-wrapper.hide-contacts .buyer-contact {{
    display: none;
  }}
  .buyers-wrapper.hide-contacts .toggle-hint-show {{
    display: inline;
  }}
  .buyers-wrapper.hide-contacts .toggle-hint-hide {{
    display: none;
  }}
  .buyers-wrapper:not(.hide-contacts) .toggle-hint-show {{
    display: none;
  }}
  .buyers-wrapper:not(.hide-contacts) .toggle-hint-hide {{
    display: inline;
  }}
  .toggle-pill {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.65rem;
    padding: 0.45rem 0.95rem;
    border-radius: 9999px;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 160ms ease;
  }}
  .toggle-pill.is-unchecked {{
    border: 1px solid rgba(148, 163, 184, 0.45);
    background: rgba(248, 250, 252, 0.9);
    color: #475569;
  }}
  .toggle-pill.is-unchecked:hover {{
    border-color: rgba(100, 116, 139, 0.6);
  }}
  .toggle-pill.is-checked {{
    border: 1px solid rgba(16, 185, 129, 0.45);
    background: rgba(236, 253, 245, 0.9);
    color: #0f766e;
  }}
  .toggle-pill.is-checked:hover {{
    border-color: rgba(16, 185, 129, 0.6);
  }}
  .toggle-track {{
    position: relative;
    display: inline-flex;
    width: 2.4rem;
    height: 1.2rem;
    border-radius: 9999px;
    padding: 0.15rem;
    transition: background 160ms ease;
  }}
  .toggle-thumb {{
    position: absolute;
    top: 0.15rem;
    left: 0.15rem;
    width: 0.9rem;
    height: 0.9rem;
    border-radius: 9999px;
    background: #ffffff;
    box-shadow: 0 1px 2px rgba(15, 118, 110, 0.35);
    transition: transform 160ms ease;
  }}
  .toggle-pill.is-unchecked .toggle-track {{
    background: rgba(148, 163, 184, 0.35);
  }}
  .toggle-pill.is-unchecked .toggle-thumb {{
    transform: translateX(0);
  }}
  .toggle-pill.is-unchecked .toggle-text {{
    color: #475569;
  }}
  .toggle-pill.is-checked .toggle-track {{
    background: rgba(21, 128, 61, 0.8);
  }}
  .toggle-pill.is-checked .toggle-thumb {{
    transform: translateX(1.2rem);
  }}
  .toggle-pill.is-checked .toggle-text {{
    color: #047857;
  }}
  /* --- Títulos e layout --- */
  header h1 {{
    color: #be123c;
    font-weight: 700;
    letter-spacing: -0.01em;
  }}
  header span {{
    background: rgba(255, 255, 255, 0.7);
    border: 1px solid rgba(244, 63, 94, 0.3);
  }}
  footer {{
    color: #9ca3af;
  }}
</style>
<script>
document.addEventListener('DOMContentLoaded', function () {{
  var whatsappInput = document.querySelector('[data-whatsapp-mask]');
  if (whatsappInput) {{
    whatsappInput.addEventListener('input', function (event) {{
      var digits = event.target.value.replace(/\\D/g, '').slice(0, 11);
      var formatted = '';
      if (digits.length > 0) {{
        formatted += '(' + digits.slice(0, Math.min(2, digits.length));
        if (digits.length >= 2) {{
          formatted += ') ';
        }}
      }}
      if (digits.length > 2) {{
        var middleLength = digits.length > 7 ? 5 : digits.length - 2;
        formatted += digits.slice(2, 2 + middleLength);
        if (digits.length > 7) {{
          formatted += '-' + digits.slice(7);
        }}
      }}
      event.target.value = formatted;
    }});
  }}

  document.querySelectorAll('[data-toggle-target]').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      var selector = btn.getAttribute('data-toggle-target');
      var target = document.querySelector(selector);
      if (target) {{
        target.classList.toggle('hide-contacts');
      }}
    }});
  }});
}});
</script>
</head>
<body class="min-h-screen bg-white text-slate-900">
<div class="max-w-4xl mx-auto p-4 sm:p-8">
  <header class="mb-8 text-center">
      <span class="inline-flex items-center gap-2 rounded-full bg-white/80 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-rose-500 shadow-sm">💖 Rifa Solidária 💖</span>
      <h1 class="mt-4 text-2xl sm:text-3xl font-bold leading-tight">{RAFFLE_TITLE}</h1>
      <div class="mt-6 bg-gradient-to-br from-rose-50 via-white to-emerald-50 border border-rose-100 shadow-inner rounded-3xl p-5 sm:p-7 space-y-4 text-center">
  <h2 class="text-xl sm:text-2xl font-bold text-rose-600 mb-2">🎁 Prêmios do Sorteio 🎁</h2>
  
<ul class="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2 text-slate-700 text-sm sm:text-base font-medium leading-relaxed text-left max-w-2xl mx-auto">
  <li>💄 1 Kit de Maquiagem</li>
  <li>🛏️ 1 Lençol</li>
  <li>🧴 1 Hidratante Lily</li>
  <li>🌸 1 Perfume O Boticário</li>
  <li>⌚ 1 Relógio de Pulso</li>
  <li>🍮 1 Pudim</li>
  <li>🛌 1 Lençol</li>
  <li>💧 1 Edge Blue (O Boticário)</li>
  <li>🧴 1 Hidratante Corporal + Íntimo</li>
</ul>


  <div class="mt-5 flex flex-col sm:flex-row items-center justify-center gap-4">
    <span class="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-5 py-2 text-emerald-600 font-semibold border border-emerald-300 shadow-sm text-base sm:text-lg">
      💰 Valor: <strong class="text-emerald-700 font-bold">R$ 5,00</strong>
    </span>
    <span class="inline-flex items-center gap-2 rounded-full bg-rose-500/10 px-5 py-2 text-rose-600 font-semibold border border-rose-300 shadow-sm text-base sm:text-lg">
      📅 Sorteio: <strong class="text-rose-700 font-bold">30 / 11 / 2025</strong>
    </span>
  </div>

  <p class="mt-4 text-slate-600 text-sm sm:text-base max-w-xl mx-auto leading-relaxed">
    Escolha seus números da sorte! ABAIXO!
  </p>
</div>

  </header>
"""

FOOTER = """
    <footer class="mt-10 text-center text-xs text-slate-400">
        <p>&copy; Love — Rifa Solidária</p>
    </footer>
</div>
</body>
</html>
"""

INDEX_TMPL = BASE_HEAD + """
<div class="raffle-card rounded-3xl bg-white/70 shadow-2xl shadow-rose-100 p-5 sm:p-8 space-y-6 border border-white/40">
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div>
      <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Status geral</p>
      <div class="mt-1 text-sm sm:text-base text-slate-700">Total: {{ total }} · Livres: {{ free_count }} · Vendidos: {{ sold_count }}</div>
    </div>
  <div class="flex items-center gap-3 text-xs sm:text-sm">
    <span class="inline-flex items-center gap-2 rounded-full border border-emerald-300 px-5 py-2 bg-white text-emerald-600 shadow-sm">
      <span class="h-2.5 w-2.5 rounded-full bg-emerald-400"></span> Livre
    </span>
    <span class="inline-flex items-center gap-2 rounded-full border border-rose-300 px-5 py-2 bg-rose-50 text-rose-500 shadow-sm">
      <span class="h-2.5 w-2.5 rounded-full bg-rose-500"></span> Vendido
    </span>

    <a href="https://wa.me/5592982583934?text=Ol%C3%A1.%20gostaria%20de%20comprar%20sua%20rifa!" target="_blank"
   class="inline-flex items-center gap-2 rounded-full bg-emerald-50 border border-emerald-400 px-5 py-2 text-emerald-700 font-semibold shadow-sm hover:bg-emerald-100 hover:border-emerald-500 transition-all duration-200">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" class="h-5 w-5 fill-emerald-600">
    <path d="M16.003 3.003A12.99 12.99 0 0 0 3 16.002a12.93 12.93 0 0 0 1.844 6.669L3 29l6.518-1.82A12.95 12.95 0 0 0 16.003 29c7.168 0 12.997-5.83 12.997-12.998 0-7.167-5.83-12.998-12.997-12.998zm0 23.404a10.37 10.37 0 0 1-5.269-1.448l-.377-.223-3.87 1.083 1.035-3.951-.244-.405a10.37 10.37 0 0 1-1.565-5.46c0-5.735 4.666-10.401 10.39-10.401a10.3 10.3 0 0 1 10.388 10.401c0 5.733-4.654 10.404-10.388 10.404zm5.703-7.787c-.311-.155-1.839-.905-2.125-1.009-.285-.104-.492-.155-.698.156-.205.311-.8 1.008-.98 1.214-.18.205-.36.232-.67.078-.312-.155-1.318-.485-2.51-1.545-.928-.827-1.554-1.846-1.737-2.157-.18-.312-.02-.48.136-.635.139-.138.312-.36.467-.54.156-.18.207-.312.311-.518.104-.205.052-.389-.026-.544-.078-.155-.698-1.676-.958-2.296-.25-.6-.506-.518-.698-.528l-.597-.011a1.15 1.15 0 0 0-.83.389c-.285.312-1.09 1.064-1.09 2.595s1.117 3.011 1.272 3.222c.155.207 2.196 3.354 5.32 4.703.744.322 1.324.514 1.775.659.745.237 1.424.204 1.96.123.598-.089 1.838-.75 2.098-1.477.26-.728.26-1.35.182-1.477-.077-.128-.285-.206-.596-.361z"/>
  </svg>
  <span>Comprar</span>
</a>


    {% if admin %}
    <a href="{{ url_for('admin') }}?key={{ key }}" class="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-2 text-white shadow-lg shadow-slate-400/30 hover:-translate-y-0.5 transition-transform">Painel</a>
    {% endif %}
  </div>
  </div>

  <div class="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-2 sm:gap-3">
    {% for ticket in tickets %}
      <div class="ticket select-none" data-status="{{ ticket['status']|trim }}">
          {{ '%03d' % ticket['number'] }}
      </div>
    {% endfor %}
  </div>

  <div class="rounded-2xl border border-dashed border-slate-200 bg-white/60 p-4 text-center text-sm text-slate-600">
    <p>Quer garantir um número? Envie uma mensagem para os noivos com o(s) número(s) desejado(s). Assim que a confirmação acontecer, o card fica vermelho automaticamente.</p>
  </div>
</div>

""" + FOOTER

ADMIN_TMPL = BASE_HEAD + """
<div class="raffle-card rounded-3xl bg-white/80 shadow-2xl shadow-slate-200 p-6 sm:p-8 border border-white/50 space-y-6">
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div>
      <h2 class="text-2xl font-bold text-slate-900">Painel do Organizador</h2>
      <p class="text-sm text-slate-500">Marque números como vendidos ou libere novamente quando necessário.</p>
    </div>
    <div class="flex gap-3 text-sm flex-wrap">
      <a class="inline-flex items-center gap-2 rounded-full bg-rose-500 px-4 py-2 text-white font-semibold shadow-lg shadow-rose-200/40 hover:bg-rose-400 transition" href="{{ url_for('buyers') }}?key={{ key }}">Lista de compradores</a>
      <a class="inline-flex items-center gap-2 rounded-full border border-slate-300 px-4 py-2 text-slate-700 font-semibold hover:border-slate-400 hover:bg-white transition" href="{{ url_for('index') }}?key={{ key }}">Ver grade</a>
    </div>
  </div>

  <form method="post" action="{{ url_for('sell') }}" class="bg-white/70 border border-slate-200 rounded-2xl p-5 shadow-sm space-y-4">
    <input type="hidden" name="key" value="{{ key }}" />
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <input name="number" type="number" min="1" max="{{ total }}" required placeholder="Número" class="rounded-xl border border-slate-200 px-4 py-3 text-base focus:border-rose-400 focus:ring-2 focus:ring-rose-200 transition" />
      <input name="buyer_name" required placeholder="Nome do comprador" class="rounded-xl border border-slate-200 px-4 py-3 text-base focus:border-rose-400 focus:ring-2 focus:ring-rose-200 transition" />
      <input name="buyer_contact" placeholder="Contato (WhatsApp)" data-whatsapp-mask class="rounded-xl border border-slate-200 px-4 py-3 text-base focus:border-rose-400 focus:ring-2 focus:ring-rose-200 transition" />
    </div>
    <label class="inline-flex items-center gap-2 text-sm text-slate-600">
      <input type="checkbox" name="paid" value="1" class="h-4 w-4 rounded border-slate-300 text-rose-500 focus:ring-rose-200">
      <span>Pagamento recebido</span>
    </label>
    <button class="w-full rounded-2xl px-6 py-4 bg-gradient-to-r from-rose-500 to-amber-400 text-white text-lg font-semibold tracking-wide shadow-xl shadow-rose-200/40 hover:from-rose-400 hover:to-amber-300 transition" type="submit">Marcar como vendido</button>
  </form>
  <form method="post" action="{{ url_for('unlock') }}" class="grid grid-cols-1 sm:grid-cols-2 gap-3 bg-white/70 border border-slate-200 rounded-2xl p-4 shadow-sm">
    <input type="hidden" name="key" value="{{ key }}" />
    <input name="number" type="number" min="1" max="{{ total }}" required placeholder="Número" class="rounded-xl border border-slate-200 px-4 py-3 text-base focus:border-slate-400 focus:ring-2 focus:ring-slate-200 transition" />
    <button class="rounded-2xl px-6 py-4 bg-slate-900 text-white text-base font-semibold shadow-lg shadow-slate-400/40 hover:bg-slate-800 transition" type="submit">Liberar número</button>
  </form>
</div>
""" + FOOTER

BUYERS_TMPL = BASE_HEAD + """
<div class="raffle-card rounded-3xl bg-white/80 shadow-2xl shadow-slate-200 p-6 sm:p-8 border border-white/50 buyers-wrapper">
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div>
      <h2 class="text-2xl font-bold text-slate-900">Compradores</h2>
      <p class="text-sm text-slate-500">Histórico em tempo real de quem já garantiu seu número.</p>
    </div>
    <div class="flex items-center gap-3 flex-wrap">
      <button type="button" class="inline-flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm text-slate-700 border border-slate-300 shadow-sm hover:border-rose-300 transition" data-toggle-target=".buyers-wrapper">
        <span class="toggle-hint-hide">Ocultar contatos</span>
        <span class="toggle-hint-show">Mostrar contatos</span>
      </button>
      <a class="inline-flex items-center gap-2 rounded-full border border-slate-300 px-4 py-2 text-sm text-slate-600 hover:border-slate-400 transition" href="{{ url_for('index') }}?key={{ key }}">Ver grade</a>
      <a class="inline-flex items-center gap-2 rounded-full bg-emerald-500 px-4 py-2 text-white text-sm font-semibold shadow-lg shadow-emerald-200/40 hover:bg-emerald-400 transition" href="{{ url_for('buyers_pdf') }}?key={{ key }}">Baixar PDF</a>
    </div>
  </div>
  <div class="mt-6 divide-y divide-slate-200">
    {% for row in buyers %}
      <div class="py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div class="font-mono text-lg sm:text-xl text-slate-900 font-semibold">#{{ '%03d' % row['number'] }}</div>
        <div class="flex-1 grid grid-cols-1 sm:grid-cols-4 gap-3 text-base text-slate-600 items-center">
          <span class="font-semibold text-slate-800">{{ row['buyer_name'] or '-' }}</span>
          <span class="buyer-contact text-slate-500">{{ row['buyer_contact'] or '-' }}</span>
          <span class="text-sm text-slate-400">{{ row['updated_at']|format_datetime }}</span>
          <form method="post" action="{{ url_for('toggle_paid') }}" class="justify-self-start sm:justify-self-end">
            <input type="hidden" name="key" value="{{ key }}">
            <input type="hidden" name="number" value="{{ row['number'] }}">
            <input type="hidden" name="paid" value="{{ 0 if row['paid'] else 1 }}">
            <button type="submit" class="toggle-pill {{ 'is-checked' if row['paid'] else 'is-unchecked' }}">
              <span class="toggle-track">
                <span class="toggle-thumb"></span>
              </span>
              <span class="toggle-text">{{ 'Pago' if row['paid'] else 'Não pago' }}</span>
            </button>
          </form>
        </div>
      </div>
    {% else %}
      <p class="py-6 text-sm text-slate-500 text-center">Nenhuma venda registrada por enquanto. Assim que alguém comprar, aparece aqui.</p>
    {% endfor %}
  </div>
</div>
""" + FOOTER

# ============================
# Rotas públicas
# ============================
@app.route("/")
def index():
    admin_mode = request.args.get("key") == ADMIN_KEY
    with closing(get_conn()) as conn:
        rows = conn.execute("SELECT number, status FROM tickets ORDER BY number").fetchall()
        sold_count = sum(1 for r in rows if r[1] == 'sold')
        free_count = len(rows) - sold_count
    return render_template_string(
        INDEX_TMPL,
        tickets=rows,
        total=len(rows),
        sold_count=sold_count,
        free_count=free_count,
        admin=admin_mode,
        key=request.args.get("key") or "",
        year=datetime.utcnow().year,
    )


# ============================
# Painel admin
# ============================

def _require_key():
    key = request.args.get("key") or request.form.get("key")
    if key != ADMIN_KEY:
        abort(403)
    return key


@app.route("/admin")
def admin():
    key = _require_key()
    return render_template_string(
        ADMIN_TMPL,
        key=key,
        total=TOTAL_NUMBERS,
        year=datetime.utcnow().year,
    )


@app.route("/admin/sell", methods=["POST"])
def sell():
    _require_key()
    number = int(request.form.get("number", 0))
    buyer_name = (request.form.get("buyer_name") or "").strip()
    buyer_contact = (request.form.get("buyer_contact") or "").strip()
    paid = 1 if request.form.get("paid") == "1" else 0
    if number < 1 or number > TOTAL_NUMBERS or not buyer_name:
        abort(400)
    now = datetime.utcnow().isoformat()
    with closing(get_conn()) as conn, conn:
        conn.execute(
            "UPDATE tickets SET status='sold', buyer_name=?, buyer_contact=?, paid=?, updated_at=? WHERE number=?",
            (buyer_name, buyer_contact, paid, now, number)
        )
    return redirect(url_for('index', key=ADMIN_KEY))


@app.route("/admin/unlock", methods=["POST"])
def unlock():
    _require_key()
    number = int(request.form.get("number", 0))
    if number < 1 or number > TOTAL_NUMBERS:
        abort(400)
    now = datetime.utcnow().isoformat()
    with closing(get_conn()) as conn, conn:
        conn.execute(
            "UPDATE tickets SET status='free', buyer_name=NULL, buyer_contact=NULL, paid=0, updated_at=? WHERE number=?",
            (now, number)
        )
    return redirect(url_for('index', key=ADMIN_KEY))


@app.route("/admin/toggle-paid", methods=["POST"])
def toggle_paid():
    key = _require_key()
    number = int(request.form.get("number", 0))
    new_paid = 1 if request.form.get("paid") == "1" else 0
    if number < 1 or number > TOTAL_NUMBERS:
        abort(400)
    now = datetime.utcnow().isoformat()
    with closing(get_conn()) as conn, conn:
        conn.execute(
            "UPDATE tickets SET paid=?, updated_at=? WHERE number=?",
            (new_paid, now, number)
        )
    return redirect(url_for('buyers', key=key))


@app.route("/buyers")
def buyers():
    key = _require_key()
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT number, buyer_name, buyer_contact, paid, updated_at FROM tickets WHERE status='sold' ORDER BY updated_at DESC"
        ).fetchall()
    return render_template_string(
        BUYERS_TMPL,
        buyers=rows,
        key=key,
        year=datetime.utcnow().year,
    )


@app.route("/buyers.pdf")
def buyers_pdf():
    _require_key()
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT number, buyer_name, buyer_contact, paid, updated_at FROM tickets WHERE status='sold' ORDER BY updated_at DESC"
        ).fetchall()
    pdf_bytes = build_buyers_pdf(rows)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=buyers.pdf"},
    )


# ============================
# Exec
# ============================
if __name__ == "__main__":
    # Initialize database before handling requests when running as script.
    init_db()
    app.run(host=HOST, port=PORT)
