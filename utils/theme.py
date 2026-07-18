"""The CRM's look: one stylesheet, injected once, applied to every portal.

Streamlit reruns the whole script on every interaction, so this is written to be
cheap and idempotent -- a <style> block is re-emitted each run and the browser
just re-applies it. Nothing here holds state.

Scope note: the palette, radii, borders, sidebar and dataframe colours live in
.streamlit/config.toml, which is a supported API. This file only holds what
config.toml cannot express -- the nav pills, the KPI cards, the masthead. CSS
here leans on Streamlit's internal data-testid names, which are NOT a public
API: they can be renamed by an upgrade, and when they are, the rule stops
applying silently. Anything config.toml can do belongs there instead.

Colours are declared once as CSS variables and mirror the config.toml values.
The accent (#0ea5e9) and the status palette already existed in client_portal.py
and app.py's login panel; this adopts them rather than introducing a second,
competing set.
"""
import html

import streamlit as st

# The palette, in Python, for the few places that build inline styles.
ACCENT = "#0ea5e9"
SURFACE = "#171a23"
BORDER = "#262b38"
TEXT_MUTED = "#94a3b8"

_CSS = """
<style>
:root {
    --crm-surface: #171a23;
    --crm-surface-hi: #1d2130;
    --crm-border: #262b38;
    --crm-border-hi: #333a4d;
    --crm-accent: #0ea5e9;
    --crm-accent-dim: rgba(14, 165, 233, 0.15);
    --crm-text: #e6edf6;
    --crm-text-muted: #94a3b8;
    --crm-radius: 14px;
}

/* ---------- canvas ---------- */
.stApp {
    background:
        radial-gradient(1200px 600px at 15% -10%, rgba(14, 165, 233, 0.07), transparent 60%),
        #0f1117;
}
.block-container { padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1400px; }
h1, h2, h3, h4 { letter-spacing: -0.02em; }

/* ---------- sidebar profile card ---------- */
[data-testid="stSidebar"] .block-container { padding-top: 2rem; }
.sidebar-profile {
    text-align: center;
    padding-bottom: 1.5rem;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid var(--crm-border);
}
.sidebar-profile img {
    width: 84px; height: 84px; border-radius: 50%;
    margin-bottom: 0.9rem;
    border: 2px solid var(--crm-border-hi);
    box-shadow: 0 0 0 4px rgba(14, 165, 233, 0.08);
}
.sidebar-name { font-size: 1.1rem; font-weight: 700; color: var(--crm-text); }
.sidebar-role {
    font-size: 0.68rem; font-weight: 700;
    color: var(--crm-accent);
    background: var(--crm-accent-dim);
    border: 1px solid rgba(14, 165, 233, 0.3);
    padding: 0.2rem 0.7rem; border-radius: 9999px;
    display: inline-block; margin-top: 0.5rem;
    text-transform: uppercase; letter-spacing: 0.06em;
}

/* ---------- page masthead ---------- */
.crm-header {
    display: flex; align-items: center; gap: 1rem;
    padding-bottom: 1.25rem; margin-bottom: 0.5rem;
    border-bottom: 1px solid var(--crm-border);
}
.crm-header-icon {
    width: 52px; height: 52px; flex: 0 0 52px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.6rem; border-radius: var(--crm-radius);
    background: var(--crm-accent-dim);
    border: 1px solid rgba(14, 165, 233, 0.25);
}
.crm-header-title { font-size: 1.7rem; font-weight: 800; color: var(--crm-text); line-height: 1.2; }
.crm-header-sub { font-size: 0.9rem; color: var(--crm-text-muted); margin-top: 0.15rem; }

/* ---------- section heading ---------- */
.crm-section { margin: 0.5rem 0 0.9rem; }
.crm-section-title {
    display: flex; align-items: center; gap: 0.5rem;
    font-size: 1.05rem; font-weight: 700; color: var(--crm-text);
}
.crm-section-title::after {
    content: ""; flex: 1; height: 1px;
    background: linear-gradient(90deg, var(--crm-border), transparent);
}
.crm-section-caption {
    font-size: 0.82rem; color: var(--crm-text-muted); margin-top: 0.2rem;
}

/* ---------- entity card (a person, a department, a record) ---------- */
.crm-card {
    display: flex; align-items: center; gap: 0.85rem;
    background: var(--crm-surface);
    border: 1px solid var(--crm-border);
    border-left: 3px solid var(--crm-accent);
    border-radius: 10px;
    padding: 0.7rem 0.9rem;
    margin-bottom: 0.5rem;
    transition: border-color 0.15s, transform 0.15s, background 0.15s;
}
.crm-card:hover {
    background: var(--crm-surface-hi);
    border-color: var(--crm-border-hi);
    border-left-color: var(--crm-accent);
    transform: translateX(2px);
}
.crm-card-avatar {
    width: 36px; height: 36px; flex: 0 0 36px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 9px; font-size: 0.95rem; font-weight: 700;
    background: var(--crm-accent-dim);
    border: 1px solid rgba(14, 165, 233, 0.25);
    color: var(--crm-accent);
}
.crm-card-body { flex: 1; min-width: 0; }
.crm-card-title {
    font-size: 0.92rem; font-weight: 600; color: var(--crm-text);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.crm-card-sub { font-size: 0.78rem; color: var(--crm-text-muted); margin-top: 0.1rem; }
.crm-card-meta {
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em;
    color: var(--crm-text-muted);
    background: rgba(148, 163, 184, 0.12);
    border: 1px solid rgba(148, 163, 184, 0.2);
    padding: 0.15rem 0.55rem; border-radius: 9999px;
    white-space: nowrap;
}

/* ---------- empty state ---------- */
.crm-empty {
    text-align: center;
    padding: 2rem 1rem;
    border: 1px dashed var(--crm-border-hi);
    border-radius: var(--crm-radius);
    background: rgba(23, 26, 35, 0.5);
}
.crm-empty-icon { font-size: 1.8rem; opacity: 0.65; }
.crm-empty-title {
    font-size: 0.95rem; font-weight: 600; color: var(--crm-text);
    margin-top: 0.5rem;
}
.crm-empty-hint {
    font-size: 0.8rem; color: var(--crm-text-muted); margin-top: 0.25rem;
}

/* ---------- nav: horizontal radio -> segmented control ---------- */
[data-testid="stRadio"] [role="radiogroup"] { gap: 0.4rem; flex-wrap: wrap; }
[data-testid="stRadio"] [role="radiogroup"] label {
    background: var(--crm-surface);
    border: 1px solid var(--crm-border);
    border-radius: 10px;
    padding: 0.5rem 0.95rem;
    margin: 0;
    transition: background 0.15s, border-color 0.15s, transform 0.15s;
}
[data-testid="stRadio"] [role="radiogroup"] label:hover {
    background: var(--crm-surface-hi);
    border-color: var(--crm-border-hi);
    transform: translateY(-1px);
}
/* Hide the radio dot -- these read as buttons, not options. */
[data-testid="stRadio"] [role="radiogroup"] label > div:first-child { display: none; }
[data-testid="stRadio"] [role="radiogroup"] label p {
    font-size: 0.88rem; font-weight: 600; color: var(--crm-text-muted);
}
/* :has() carries the selected state -- Streamlit exposes it only on the input. */
[data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
    background: var(--crm-accent-dim);
    border-color: rgba(14, 165, 233, 0.45);
    box-shadow: 0 0 0 1px rgba(14, 165, 233, 0.15), 0 4px 12px -4px rgba(14, 165, 233, 0.4);
}
[data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) p { color: var(--crm-accent); }

/* ---------- metrics -> KPI cards ---------- */
[data-testid="stMetric"] {
    background: linear-gradient(180deg, var(--crm-surface-hi) 0%, var(--crm-surface) 100%);
    border: 1px solid var(--crm-border);
    border-radius: var(--crm-radius);
    padding: 1rem 1.1rem;
    transition: border-color 0.15s, transform 0.15s;
}
[data-testid="stMetric"]:hover { border-color: var(--crm-border-hi); transform: translateY(-2px); }
[data-testid="stMetricLabel"] p {
    font-size: 0.72rem !important;
    font-weight: 700;
    color: var(--crm-text-muted) !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

/* ---------- expanders & forms ---------- */
[data-testid="stExpander"] {
    background: var(--crm-surface);
    border-color: var(--crm-border);
    overflow: hidden;
}
[data-testid="stExpander"] summary { padding: 0.75rem 1rem; font-weight: 600; }
[data-testid="stExpander"] summary:hover { background: var(--crm-surface-hi); color: var(--crm-accent); }

[data-testid="stForm"] {
    background: var(--crm-surface);
    border-color: var(--crm-border);
    padding: 1.25rem;
}

/* ---------- tabs ---------- */
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 0.25rem; border-bottom: 1px solid var(--crm-border); }
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent;
    border-radius: 8px 8px 0 0;
    padding: 0.5rem 1rem;
    font-weight: 600;
    color: var(--crm-text-muted);
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover { background: var(--crm-surface); color: var(--crm-text); }
[data-testid="stTabs"] [aria-selected="true"] { color: var(--crm-accent) !important; }

/* ---------- inputs (colour/radius come from config.toml) ---------- */
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: var(--crm-accent) !important;
    box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15) !important;
}
[data-testid="stWidgetLabel"] p { font-size: 0.82rem; font-weight: 600; color: var(--crm-text-muted); }

/* ---------- buttons (radius comes from config.toml) ---------- */
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondaryFormSubmit"] {
    background: var(--crm-surface-hi);
    border: 1px solid var(--crm-border-hi);
    color: var(--crm-text);
    font-weight: 600;
    transition: border-color 0.15s, color 0.15s, transform 0.15s;
}
[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
    border-color: var(--crm-accent);
    color: var(--crm-accent);
    transform: translateY(-1px);
}
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"] {
    background: linear-gradient(135deg, #0284c7 0%, #0ea5e9 100%);
    border: none;
    font-weight: 700;
    box-shadow: 0 6px 16px -6px rgba(14, 165, 233, 0.6);
    transition: transform 0.15s, box-shadow 0.15s;
}
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 10px 22px -6px rgba(14, 165, 233, 0.7);
}
</style>
"""


def inject_theme():
    """Apply the CRM stylesheet. Call once per run, right after set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)


def _esc(value):
    """Escape text bound for an unsafe_allow_html block.

    Everything these helpers render is user-supplied -- department names, client
    company names, people's names -- and it all comes back out of Postgres
    untouched. Without this, a department named "<img src=x onerror=alert(1)>"
    is stored happily and then executes in the admin's browser. Streamlit does
    not sanitise anything passed with unsafe_allow_html; that is the whole
    meaning of the flag.
    """
    return html.escape(str(value if value is not None else ""))


def _html(*parts):
    """Emit HTML to Streamlit as ONE line, with no indentation.

    st.markdown runs the markdown parser before it honours unsafe_allow_html, so
    pretty-printed HTML is actively dangerous here:

      - a whitespace-only line (which is what an omitted optional field leaves
        behind) reads as a blank line and TERMINATES the HTML block;
      - any line indented four spaces or more -- i.e. every closing tag in a
        template indented to match the Python around it -- then parses as a
        markdown code block and is printed literally.

    That combination is what put a bare "</div>" on the admin's screen whenever
    a caption was omitted. Joining the parts with no separator removes both
    triggers by construction, so an empty field cannot break the block.
    """
    st.markdown("".join(p for p in parts if p), unsafe_allow_html=True)


def page_header(title, subtitle=None):
    """The standard portal masthead: title, optional one-liner, hairline rule.

    Every portal opened differently before -- st.title here, st.header there --
    which is what made five screens of the same product look like five products.

    No icon slot on purpose. This carried an emoji, which renders as whatever
    glyph the viewer's OS ships, cannot be styled or tokenised, and reads as
    decoration rather than as part of the product.
    """
    _html(
        '<div class="crm-header">',
        "<div>",
        f'<div class="crm-header-title">{_esc(title)}</div>',
        f'<div class="crm-header-sub">{_esc(subtitle)}</div>' if subtitle else "",
        "</div>",
        "</div>",
    )


def section(title, caption=None):
    """A titled band with a hairline rule -- the unit portals are built from."""
    _html(
        '<div class="crm-section">',
        f'<div class="crm-section-title"><span>{_esc(title)}</span></div>',
        f'<div class="crm-section-caption">{_esc(caption)}</div>' if caption else "",
        "</div>",
    )


def entity_card(title, subtitle=None, meta=None, avatar=None):
    """One record as a card: a person, a department, a client.

    Replaces the "- **name**" markdown bullets these lists used to be. The
    avatar defaults to the first letter of the title, which is enough to make a
    long list scannable without fetching an image per row.
    """
    initial = avatar if avatar else (str(title).strip()[:1].upper() or "?")
    _html(
        '<div class="crm-card">',
        f'<div class="crm-card-avatar">{_esc(initial)}</div>',
        '<div class="crm-card-body">',
        f'<div class="crm-card-title">{_esc(title)}</div>',
        f'<div class="crm-card-sub">{_esc(subtitle)}</div>' if subtitle else "",
        "</div>",
        f'<div class="crm-card-meta">{_esc(meta)}</div>' if meta else "",
        "</div>",
    )


def badge(label, colors):
    """A small status pill, e.g. a meeting/task/proposal status.

    `colors` is a {status: (fg, bg)} map the caller owns -- what statuses exist
    and what they mean is domain data (proposal statuses, meeting statuses),
    not something this generic renderer should know about. Falls back to a
    neutral grey for any status not in the map, so an unexpected value renders
    instead of raising.
    """
    fg, bg = colors.get(str(label).lower(), ("#94a3b8", "rgba(148, 163, 184, 0.15)"))
    text = _esc(str(label).replace("_", " ").upper())
    _html(
        f'<span style="'
        f'font-size: 0.7rem; font-weight: 700; color: {fg};'
        f'background-color: {bg}; border: 1px solid {fg}55;'
        f'padding: 0.2rem 0.7rem; border-radius: 9999px;'
        f'display: inline-block; letter-spacing: 0.05em;'
        f'">{text}</span>'
    )


def empty_state(title, hint=None):
    """What an empty list should say.

    st.info() shouts a blue banner for the normal, expected case of "nothing
    here yet"; this states it calmly and says what would fill it.
    """
    _html(
        '<div class="crm-empty">',
        f'<div class="crm-empty-title">{_esc(title)}</div>',
        f'<div class="crm-empty-hint">{_esc(hint)}</div>' if hint else "",
        "</div>",
    )
