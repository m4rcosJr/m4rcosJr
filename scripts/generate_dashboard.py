#!/usr/bin/env python3
"""
Gera os SVGs do dashboard do perfil a partir da API GraphQL do GitHub.

Saídas (pasta assets/):
  - stats.svg      -> cards com os números principais
  - commits.svg    -> gráfico de commits por mês (últimos 12 meses)
  - languages.svg  -> linguagens mais usadas nos seus repositórios públicos
  - heatmap.svg    -> mapa de contribuições do último ano

Usa apenas a biblioteca padrão do Python (não precisa de pip install).
Variáveis de ambiente:
  GITHUB_TOKEN  (obrigatória) token para consultar a API
  GH_LOGIN      (opcional)    usuário; padrão: m4rcosJr
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from html import escape

LOGIN = os.environ.get("GH_LOGIN", "m4rcosJr")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
API = "https://api.github.com/graphql"
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")

# ---------- Tema (preto / cinza-escuro / ciano e azul) ----------
BG = "#0d1117"
CARD = "#161b22"
BORDER = "#30363d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
CYAN = "#39c5cf"
BLUE = "#58a6ff"
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
WIDTH = 836

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
         "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


# ---------- Acesso à API ----------
def gql(query, variables=None):
    """Executa uma consulta GraphQL e devolve o campo 'data'."""
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "profile-dashboard-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def last_12_months(now):
    """Lista [(ano, mês)] dos últimos 12 meses, do mais antigo ao atual."""
    result = []
    y, m = now.year, now.month
    for _ in range(12):
        result.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(result))


QUERY_PROFILE = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    owned: repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def build_commits_query(created_year, now, months):
    """Monta uma consulta com um alias por mês (m0..m11) e um por ano (y2024...)."""
    parts = []
    for i, (y, m) in enumerate(months):
        start = datetime(y, m, 1, tzinfo=timezone.utc)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = min(datetime(ny, nm, 1, tzinfo=timezone.utc), now)
        parts.append(
            f'm{i}: contributionsCollection(from: "{iso(start)}", to: "{iso(end)}") '
            f"{{ totalCommitContributions }}"
        )
    for y in range(created_year, now.year + 1):
        start = datetime(y, 1, 1, tzinfo=timezone.utc)
        end = min(datetime(y + 1, 1, 1, tzinfo=timezone.utc), now)
        parts.append(
            f'y{y}: contributionsCollection(from: "{iso(start)}", to: "{iso(end)}") '
            f"{{ totalCommitContributions }}"
        )
    return "query($login: String!) { user(login: $login) { " + " ".join(parts) + " } }"


def fetch_data():
    now = datetime.now(timezone.utc)
    prof = gql(QUERY_PROFILE, {"login": LOGIN})["user"]
    created_year = int(prof["createdAt"][:4])

    months = last_12_months(now)
    commits = gql(build_commits_query(created_year, now, months), {"login": LOGIN})["user"]

    monthly = [commits[f"m{i}"]["totalCommitContributions"] for i in range(12)]
    total_commits = sum(
        commits[f"y{y}"]["totalCommitContributions"]
        for y in range(created_year, now.year + 1)
    )

    # Estrelas e linguagens (somando bytes de código dos repositórios públicos)
    stars = 0
    langs = {}
    for repo in prof["owned"]["nodes"]:
        stars += repo["stargazerCount"]
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            color = edge["node"]["color"] or CYAN
            size = langs.get(name, (0, color))[0] + edge["size"]
            langs[name] = (size, color)
    top_langs = sorted(langs.items(), key=lambda kv: kv[1][0], reverse=True)[:6]

    calendar = prof["contributionsCollection"]["contributionCalendar"]
    return {
        "now": now,
        "created_year": created_year,
        "months": months,
        "monthly": monthly,
        "total_commits": total_commits,
        "contributions_12m": calendar["totalContributions"],
        "weeks": calendar["weeks"],
        "repos": prof["repositories"]["totalCount"],
        "followers": prof["followers"]["totalCount"],
        "stars": stars,
        "langs": top_langs,
    }


# ---------- Utilidades de SVG ----------
def fmt(n):
    return f"{n:,}".replace(",", ".")


def svg_open(width, height):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT}">\n'
    )


def write(name, content):
    os.makedirs(ASSETS, exist_ok=True)
    path = os.path.join(ASSETS, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"gerado: {path}")


# ---------- 1) Cards de estatísticas ----------
def render_stats(d):
    active_months = sum(1 for v in d["monthly"] if v > 0)
    cards = [
        ("Commits este mês", d["monthly"][-1]),
        ("Commits (12 meses)", sum(d["monthly"])),
        (f"Commits desde {d['created_year']}", d["total_commits"]),
        ("Contribuições (12 meses)", d["contributions_12m"]),
        ("Repositórios públicos", d["repos"]),
        ("Estrelas recebidas", d["stars"]),
        ("Seguidores", d["followers"]),
        ("Meses ativos (de 12)", active_months),
    ]
    card_w, card_h, gap = 200, 84, 12
    height = 2 * card_h + gap
    out = svg_open(WIDTH, height)
    for i, (label, value) in enumerate(cards):
        x = (i % 4) * (card_w + gap)
        y = (i // 4) * (card_h + gap)
        out += (
            f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{card_w - 1}" height="{card_h - 1}" '
            f'rx="10" fill="{CARD}" stroke="{BORDER}"/>\n'
            f'<rect x="{x + 16}" y="{y + 16}" width="24" height="3" rx="1.5" fill="{CYAN}"/>\n'
            f'<text x="{x + 16}" y="{y + 50}" font-size="28" font-weight="700" fill="{TEXT}">'
            f"{fmt(value)}</text>\n"
            f'<text x="{x + 16}" y="{y + 70}" font-size="12" fill="{MUTED}">{escape(label)}</text>\n'
        )
    return out + "</svg>\n"


# ---------- 2) Gráfico mensal de commits ----------
def render_commits(d):
    height = 270
    left, right, top, bottom = 44, 20, 62, 44
    plot_w = WIDTH - left - right
    plot_h = height - top - bottom
    values = d["monthly"]
    max_v = max(max(values), 1)
    # Escala "redonda" para o eixo Y
    step = max(1, -(-max_v // 4))
    scale_max = step * 4

    out = svg_open(WIDTH, height)
    out += (
        f'<defs><linearGradient id="bar" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{CYAN}"/><stop offset="1" stop-color="{BLUE}"/>'
        f"</linearGradient></defs>\n"
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="12" '
        f'fill="{CARD}" stroke="{BORDER}"/>\n'
        f'<text x="24" y="32" font-size="15" font-weight="600" fill="{TEXT}">'
        f"Commits por mês</text>\n"
        f'<text x="24" y="50" font-size="12" fill="{MUTED}">Últimos 12 meses · '
        f"total: {fmt(sum(values))}</text>\n"
    )
    # Linhas de grade e rótulos do eixo Y
    for i in range(5):
        v = step * i
        y = top + plot_h - (v / scale_max) * plot_h
        out += (
            f'<line x1="{left}" y1="{y:.1f}" x2="{WIDTH - right}" y2="{y:.1f}" '
            f'stroke="{BORDER}" stroke-width="1" stroke-dasharray="3 4"/>\n'
            f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" fill="{MUTED}" '
            f'text-anchor="end">{v}</text>\n'
        )
    # Barras
    slot = plot_w / 12
    bar_w = min(36, slot * 0.6)
    for i, ((y_, m_), v) in enumerate(zip(d["months"], values)):
        cx = left + slot * i + slot / 2
        bar_h = (v / scale_max) * plot_h
        by = top + plot_h - bar_h
        if v > 0:
            opacity = ' opacity="0.65"' if i < 11 else ""
            out += (
                f'<rect x="{cx - bar_w / 2:.1f}" y="{by:.1f}" width="{bar_w:.1f}" '
                f'height="{bar_h:.1f}" rx="4" fill="url(#bar)"{opacity}/>\n'
            )
        out += (
            f'<text x="{cx:.1f}" y="{by - 6:.1f}" font-size="11" font-weight="600" '
            f'fill="{TEXT}" text-anchor="middle">{v}</text>\n'
            f'<text x="{cx:.1f}" y="{height - 22}" font-size="11" fill="{MUTED}" '
            f'text-anchor="middle">{MESES[m_ - 1]}</text>\n'
        )
    stamp = d["now"].strftime("%d/%m/%Y")
    out += (
        f'<text x="{WIDTH - 24}" y="32" font-size="11" fill="{MUTED}" text-anchor="end">'
        f"Atualizado em {stamp} (UTC)</text>\n"
    )
    return out + "</svg>\n"


# ---------- 3) Linguagens ----------
def render_languages(d):
    height = 150
    out = svg_open(WIDTH, height)
    out += (
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="12" '
        f'fill="{CARD}" stroke="{BORDER}"/>\n'
        f'<text x="24" y="32" font-size="15" font-weight="600" fill="{TEXT}">'
        f"Linguagens mais usadas</text>\n"
        f'<text x="24" y="50" font-size="12" fill="{MUTED}">'
        f"Proporção de código nos repositórios públicos próprios</text>\n"
    )
    langs = d["langs"]
    total = sum(size for _, (size, _) in langs) or 1
    bar_x, bar_w = 24, WIDTH - 48
    out += (
        f'<clipPath id="lc"><rect x="{bar_x}" y="66" width="{bar_w}" height="10" rx="5"/></clipPath>\n'
        f'<g clip-path="url(#lc)">\n'
    )
    x = bar_x
    for name, (size, color) in langs:
        w = bar_w * size / total
        out += f'<rect x="{x:.1f}" y="66" width="{w:.1f}" height="10" fill="{color}"/>\n'
        x += w
    out += "</g>\n"
    # Legenda em 3 colunas
    col_w = bar_w / 3
    for i, (name, (size, color)) in enumerate(langs):
        lx = bar_x + (i % 3) * col_w
        ly = 104 + (i // 3) * 24
        pct = 100 * size / total
        out += (
            f'<circle cx="{lx + 5:.1f}" cy="{ly - 4}" r="5" fill="{color}"/>\n'
            f'<text x="{lx + 18:.1f}" y="{ly}" font-size="12" fill="{TEXT}">{escape(name)} '
            f'<tspan fill="{MUTED}">{pct:.1f}%</tspan></text>\n'
        )
    if not langs:
        out += f'<text x="24" y="104" font-size="12" fill="{MUTED}">Sem dados ainda.</text>\n'
    return out + "</svg>\n"


# ---------- 4) Mapa de contribuições ----------
def render_heatmap(d):
    height = 196
    cell, gap = 12, 3
    palette = ["#161b22", "#0c3b4a", "#0e6177", "#1a8fa3", CYAN]
    weeks = d["weeks"]
    max_c = max((day["contributionCount"] for w in weeks for day in w["contributionDays"]), default=1) or 1

    out = svg_open(WIDTH, height)
    out += (
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="12" '
        f'fill="{CARD}" stroke="{BORDER}"/>\n'
        f'<text x="24" y="32" font-size="15" font-weight="600" fill="{TEXT}">'
        f"Histórico de contribuições</text>\n"
        f'<text x="{WIDTH - 24}" y="32" font-size="12" fill="{MUTED}" text-anchor="end">'
        f"{fmt(d['contributions_12m'])} contribuições no último ano</text>\n"
    )
    x0, y0 = 24, 52
    for wi, week in enumerate(weeks):
        for day in week["contributionDays"]:
            # GitHub começa a semana no domingo
            weekday = (datetime.strptime(day["date"], "%Y-%m-%d").weekday() + 1) % 7
            c = day["contributionCount"]
            if c == 0:
                lvl = 0
            else:
                r = c / max_c
                lvl = 1 if r <= 0.25 else 2 if r <= 0.5 else 3 if r <= 0.75 else 4
            out += (
                f'<rect x="{x0 + wi * (cell + gap)}" y="{y0 + weekday * (cell + gap)}" '
                f'width="{cell}" height="{cell}" rx="2" fill="{palette[lvl]}"/>\n'
            )
    # Legenda
    ly = y0 + 7 * (cell + gap) + 16
    out += f'<text x="{WIDTH - 24 - 5 * 16 - 60}" y="{ly + 10}" font-size="11" fill="{MUTED}">Menos</text>\n'
    for i, color in enumerate(palette):
        out += (
            f'<rect x="{WIDTH - 24 - 5 * 16 - 20 + i * 16}" y="{ly}" width="12" height="12" '
            f'rx="2" fill="{color}"/>\n'
        )
    out += f'<text x="{WIDTH - 24 - 16}" y="{ly + 10}" font-size="11" fill="{MUTED}">Mais</text>\n'
    return out + "</svg>\n"


def main():
    if not TOKEN:
        sys.exit("Defina a variável de ambiente GITHUB_TOKEN antes de executar.")
    data = fetch_data()
    write("stats.svg", render_stats(data))
    write("commits.svg", render_commits(data))
    write("languages.svg", render_languages(data))
    write("heatmap.svg", render_heatmap(data))


if __name__ == "__main__":
    main()
