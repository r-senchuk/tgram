import re
import gradio as gr

from tgram.adapters.llm_litellm import LiteLLMAdapter
from tgram.adapters.llm_ollama import OllamaAdapter
from tgram.adapters.repo_embeddings import EmbeddingRepo
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.repo_topics import TopicRepo
from tgram.adapters.search_fts import FTSSearch, SearchHit
from tgram.config import Config
from tgram.services.ai import AIService


def _linkify(text: str) -> str:
    """Convert [msg:N] and [msg:N, msg:M, ...] citations to clickable anchor links."""
    def expand(m):
        ids = re.findall(r'\d+', m.group(0))
        return ' '.join(f'[↗ msg:{i}](#msg-{i})' for i in ids)
    return re.sub(r'\[(?:msg:\d+)(?:,\s*msg:\d+)*\]', expand, text)


def _text(content) -> str:
    """Gradio 6 may store message content as a list of blocks; extract plain text."""
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
        )
    return content or ""

MODEL_CHOICES = [
    ("Gemini 2.5 Flash Lite ⚡", "gemini/gemini-2.5-flash-lite"),
    ("Gemma 4 26B (local)",      "local"),
]

# ── Theme CSS ────────────────────────────────────────────────────────────────
# CSS custom properties drive both themes; data-theme="dark" on <html> switches.
_CSS = """
/* ── Variables ─────────────────────────────────────── */
:root, :root[data-theme="light"] {
    --tg-gradient    : linear-gradient(135deg, #dff0f8 0%, #ece8f8 50%, #f8ece8 100%);
    --tg-glass       : rgba(255, 255, 255, 0.82);
    --tg-glass-bdr   : rgba(255, 255, 255, 0.55);
    --tg-controls-bg : rgba(255, 255, 255, 0.92);
    --tg-surface     : #ffffff;
    --tg-surface-2   : #f8fafc;
    --tg-text        : #1a1a1a;
    --tg-text-2      : #374151;
    --tg-chatbot     : rgba(255, 255, 255, 0.88);
    --tg-shadow      : rgba(0, 0, 0, 0.06);
    --tg-input-bg    : #ffffff;
    --tg-accent      : #6366f1;
    --tg-border      : rgba(0, 0, 0, 0.08);
}

:root[data-theme="dark"] {
    --tg-gradient    : linear-gradient(135deg, #0c1022 0%, #17123a 50%, #0c1022 100%);
    --tg-glass       : rgba(255, 255, 255, 0.07);
    --tg-glass-bdr   : rgba(255, 255, 255, 0.13);
    --tg-controls-bg : rgba(30, 35, 60, 0.85);
    --tg-surface     : #1e293b;
    --tg-surface-2   : #0f172a;
    --tg-text        : #e2e8f0;
    --tg-text-2      : #94a3b8;
    --tg-chatbot     : rgba(15, 23, 42, 0.90);
    --tg-shadow      : rgba(0, 0, 0, 0.35);
    --tg-input-bg    : #1e293b;
    --tg-accent      : #818cf8;
    --tg-border      : rgba(255, 255, 255, 0.08);
}

/* ── Override Gradio's own CSS variables per theme ──── */
:root[data-theme="light"] {
    --body-background-fill       : white;
    --background-fill-primary    : white;
    --background-fill-secondary  : #f8fafc;
    --block-background-fill      : white;
    --input-background-fill      : white;
    --body-text-color            : #1a1a1a;
    --block-label-text-color     : #374151;
    --border-color-primary       : rgba(0,0,0,0.08);
    --color-accent               : #6366f1;
}

:root[data-theme="dark"] {
    --body-background-fill       : #0c1022;
    --background-fill-primary    : #1e293b;
    --background-fill-secondary  : #0f172a;
    --block-background-fill      : #1e293b;
    --input-background-fill      : #1e293b;
    --body-text-color            : #e2e8f0;
    --block-label-text-color     : #94a3b8;
    --border-color-primary       : rgba(255,255,255,0.08);
    --color-accent               : #818cf8;
    --checkbox-background-color  : #1e293b;
    --checkbox-background-color-focus: #2d3f55;
}

/* ── Layout ─────────────────────────────────────────── */
.gradio-container {
    background: var(--tg-gradient) !important;
    min-height: 100vh;
}

/* Dark: all blocks transparent so gradient shows through */
:root[data-theme="dark"] .block,
:root[data-theme="dark"] .form,
:root[data-theme="dark"] .gap,
:root[data-theme="dark"] .panel,
:root[data-theme="dark"] footer {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* Light: spacer/footer transparent; content blocks white */
:root[data-theme="light"] .gap,
:root[data-theme="light"] footer {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
:root[data-theme="light"] .block,
:root[data-theme="light"] .form,
:root[data-theme="light"] .panel {
    background: white !important;
    color: #1a1a1a !important;
    border-color: rgba(0, 0, 0, 0.06) !important;
    box-shadow: none !important;
}

/* Light mode header text */
:root[data-theme="light"] .glass-header,
:root[data-theme="light"] .glass-header * {
    color: #1a1a1a !important;
}

/* ── Glass header ────────────────────────────────────── */
.glass-header {
    background    : var(--tg-glass) !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    border        : 1px solid var(--tg-glass-bdr) !important;
    border-radius : 12px !important;
    box-shadow    : 0 2px 12px var(--tg-shadow) !important;
    padding       : 16px 20px !important;
    margin-bottom : 6px !important;
    color         : var(--tg-text) !important;
}

/* ── Controls bar (no backdrop-filter — it traps dropdown z-index) ── */
#controls-bar {
    background    : var(--tg-controls-bg) !important;
    border        : 1px solid var(--tg-glass-bdr) !important;
    border-radius : 12px !important;
    box-shadow    : 0 2px 12px var(--tg-shadow),
                    inset 0 1px 0 rgba(255, 255, 255, 0.15) !important;
    padding       : 12px 16px !important;
    margin-bottom : 8px !important;
}

/* Control labels */
#controls-bar label span, #controls-bar .label-wrap span {
    color: var(--tg-text) !important;
}

/* ── Chatbot ─────────────────────────────────────────── */
:root[data-theme="light"] div[data-testid="chatbot"],
:root[data-theme="light"] div[data-testid="chatbot"] > div {
    background    : rgba(255, 255, 255, 0.88) !important;
    border-radius : 12px !important;
}
:root[data-theme="dark"] div[data-testid="chatbot"],
:root[data-theme="dark"] div[data-testid="chatbot"] > div {
    background    : rgba(15, 23, 42, 0.90) !important;
    border-radius : 12px !important;
}

div[data-testid="chatbot"] .message,
div[data-testid="chatbot"] p,
div[data-testid="chatbot"] span {
    color: var(--tg-text) !important;
}

/* ── Form controls ───────────────────────────────────── */
textarea, input[type="text"], input[type="search"] {
    background : var(--tg-input-bg) !important;
    color      : var(--tg-text) !important;
    border     : 1px solid var(--tg-border) !important;
}

ul.options li, .options {
    background : var(--tg-surface) !important;
    color      : var(--tg-text) !important;
}

/* ── Theme toggle button ─────────────────────────────── */
#theme-toggle button {
    padding       : 6px 10px !important;
    border-radius : 8px !important;
    min-width     : 38px !important;
    font-size     : 16px !important;
    background    : var(--tg-glass) !important;
    border        : 1px solid var(--tg-glass-bdr) !important;
    cursor        : pointer !important;
}

/* ── Mobile ──────────────────────────────────────────── */
/* ── Citation badge links ────────────────────────────── */
.chatbot a[href^="#msg-"] {
    font-size      : 0.78em;
    font-family    : monospace;
    background     : var(--tg-accent);
    color          : white !important;
    padding        : 1px 6px;
    border-radius  : 4px;
    text-decoration: none;
    opacity        : 0.9;
}
.chatbot a[href^="#msg-"]:hover { opacity: 1; }

/* ── Context panel ───────────────────────────────────── */
.ctx-panel {
    background    : var(--tg-chatbot) !important;
    border        : 1px solid var(--tg-glass-bdr) !important;
    border-radius : 10px !important;
    padding       : 12px 16px !important;
    font-size     : 0.88em !important;
    margin-top    : 4px !important;
}

@media (max-width: 768px) {
    .glass-header {
        backdrop-filter: blur(10px) !important;
        -webkit-backdrop-filter: blur(10px) !important;
    }
}
"""

# On page load: restore saved theme or follow OS preference; wire citation clicks
_JS_INIT = """
() => {
    const saved = localStorage.getItem('tgram-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved ?? (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);

    // Citation click → update hidden textbox via native setter so Svelte picks it up
    document.addEventListener('click', function(e) {
        const a = e.target.closest('a[href^="#msg-"]');
        if (!a) return;
        e.preventDefault();
        const msgId = a.getAttribute('href').slice(5); // "#msg-N" → "N"
        const tb = document.querySelector('#msg-lookup-input textarea, #msg-lookup-input input');
        if (!tb) return;
        // Svelte's bind:value listens for 'input' events; use native setter so the
        // value change is visible to the framework before the event fires.
        const setter = Object.getOwnPropertyDescriptor(
            Object.getPrototypeOf(tb), 'value'
        ).set;
        setter.call(tb, msgId);
        tb.dispatchEvent(new Event('input', { bubbles: true }));
    });
}
"""

# Toggle click: flip theme and update button emoji
_JS_TOGGLE = """
() => {
    const html   = document.documentElement;
    const isDark = html.getAttribute('data-theme') === 'dark';
    const next   = isDark ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('tgram-theme', next);
    const btn = document.querySelector('#theme-toggle button');
    if (btn) btn.textContent = next === 'dark' ? '☀️' : '🌙';
}
"""

_THEME = gr.themes.Soft(
    primary_hue=gr.themes.colors.indigo,
    neutral_hue=gr.themes.colors.slate,
)


def _make_llm(model_str: str):
    if model_str.startswith("ollama/") or model_str == "local":
        return OllamaAdapter()
    return LiteLLMAdapter(default_model=model_str)


def launch(cfg: Config, chat_id: int | None = None,
           think: bool = False, port: int = 7860) -> None:
    repo       = MessageRepo(cfg.db_path)
    repo_embed = EmbeddingRepo(cfg.db_path)
    fts        = FTSSearch(cfg.db_path, embedding_repo=repo_embed)

    target_chat  = chat_id or cfg.default_chat_id
    repo_topics  = TopicRepo(cfg.db_path)
    topic_rows   = repo_topics.stats_for_chat(target_chat)
    topic_choices = [("All topics", None)] + [
        (f"{r['title']}  ({r['msg_count']} msgs)", r["topic_id"])
        for r in topic_rows
    ]
    scope_label = str(target_chat) if target_chat else "all chats"

    last_hits: list = []  # stores hits from the most recent respond() call
    last_context_index: dict[int, tuple[int, int]] = {}

    def respond(message, history, model_choice, topic_choice, think_toggle):
        nonlocal last_hits, last_context_index
        try:
            llm = _make_llm(model_choice)
            ai  = AIService(fts, llm, embedder=OllamaAdapter())

            pairs: list[tuple[str, str]] = []
            it = iter(history)
            for turn in it:
                if turn["role"] == "user":
                    user_msg = _text(turn["content"])
                    try:
                        asst = next(it)
                        pairs.append((user_msg, _text(asst["content"])))
                    except StopIteration:
                        pass

            response, hits, ctx_idx = ai.ask_with_history(
                message, pairs,
                chat_id=chat_id,
                topic_id=topic_choice,
                stream=True,
                think=think_toggle,
            )
            last_hits = hits
            last_context_index = ctx_idx

            prefix = f"*↗ {len(hits)} messages retrieved*\n\n"
            partial = ""
            yield prefix
            for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta:
                    partial += delta
                    yield prefix + partial
            yield _linkify(prefix + partial)
        except Exception as exc:
            yield f"⚠️ {exc}"

    def lookup_context(msg_id_str: str):
        try:
            mid = int(msg_id_str.strip())
            resolved_pair = last_context_index.get(mid)
            resolved_chat_id = resolved_pair[0] if resolved_pair else None

            row = None
            if resolved_chat_id is not None:
                row = repo.get_by_id(mid, resolved_chat_id)
            if not row:
                row = repo.get_by_id(mid, chat_id)
            if not row:
                row = repo.get_by_id(mid, None)
            if not row:
                return (gr.update(value=f"Message `{mid}` not found.", visible=True),
                        gr.update(visible=True))

            hit = SearchHit(
                chat_id=row["chat_id"],
                message_id=row["id"],
                date=row["date"],
                text=row["text"] or "",
                username=row.get("username"),
                from_user_id=row.get("from_user_id"),
                topic_id=row.get("reply_to_top_message_id"),
                topic_title=None,
                snippet="",
                virtual_topic_id=row.get("virtual_topic_id"),
                reply_to_message_id=row.get("reply_to_message_id"),
            )
            ctx_msgs = fts.get_conversation(hit, max_thread_msgs=12, window=2)
            lines = [f"**Conversation around msg:{mid}**\n"]
            disp_ids = {m.message_id for m in ctx_msgs}
            for m in ctx_msgs:
                if getattr(m, "skipped_before", 0) > 0:
                    lines.append(f"*(… {m.skipped_before} messages skipped …)*")
                who    = f"@{m.username}" if m.username else f"user:{m.from_user_id}"
                d      = m.date[:16].replace("T", " ") if m.date and len(m.date) >= 16 else (m.date or "")
                reply_to = getattr(m, "reply_to_message_id", None)
                reply_prefix = f"↳ [reply to msg:{reply_to}] " if (reply_to and reply_to in disp_ids) else ""
                txt    = (m.text or "").replace("\n", " ")[:300]
                marker = "**→**" if getattr(m, "is_hit", False) else "·"
                lines.append(f"{marker} `{d}` **{who}**: {reply_prefix}{txt}")
            return (gr.update(value="\n\n".join(lines), visible=True),
                    gr.update(visible=True))
        except Exception as exc:
            return gr.update(value=f"⚠️ {exc}", visible=True), gr.update(visible=True)

    default_model = MODEL_CHOICES[0][1]

    with gr.Blocks(title="tgram") as app:
        with gr.Row(elem_classes=["glass-header"]):
            with gr.Column(scale=10):
                gr.Markdown(
                    f"## tgram — Chat with your Telegram archive\n"
                    f"*{scope_label} · {len(topic_rows)} topics*",
                )
            with gr.Column(scale=0, min_width=48):
                theme_btn = gr.Button("🌙", elem_id="theme-toggle", size="sm")

        with gr.Group(elem_id="controls-bar"):
            with gr.Row():
                model_dd = gr.Dropdown(
                    choices=MODEL_CHOICES, value=default_model,
                    label="Model", interactive=True, scale=2,
                )
                topic_dd = gr.Dropdown(
                    choices=topic_choices, value=None,
                    label="Filter by topic", interactive=True, scale=3,
                )
                think_cb = gr.Checkbox(
                    value=think, label="Think", scale=1,
                    info="Qwen chain-of-thought (ignored for cloud models)",
                )

        gr.ChatInterface(
            fn=respond,
            additional_inputs=[model_dd, topic_dd, think_cb],
        )

        sources_btn = gr.Button("📋 Sources", size="sm", variant="secondary")

        # Hidden textbox — JS writes message ID here; .input() fires lookup_context
        msg_id_box = gr.Textbox(visible=False, elem_id="msg-lookup-input")

        # Context / sources panel
        ctx_md    = gr.Markdown("", visible=False, elem_classes=["ctx-panel"])
        ctx_close = gr.Button("✕  Close", visible=False, size="sm")

        def show_sources():
            if not last_hits:
                return gr.update(value="*(no sources yet — ask a question first)*",
                                 visible=True), gr.update(visible=True)
            lines = [f"**{len(last_hits)} messages retrieved for last query**\n"]
            for h in last_hits:
                who = f"@{h.username}" if h.username else f"user:{h.from_user_id}"
                d   = h.date[:16].replace("T", " ")
                txt = (h.text or "").replace("\n", " ")[:200]
                lines.append(
                    f"[↗ msg:{h.message_id}](#msg-{h.message_id}) "
                    f"`{d}` **{who}**: {txt}"
                )
            return gr.update(value="\n\n".join(lines), visible=True), gr.update(visible=True)

        sources_btn.click(fn=show_sources, outputs=[ctx_md, ctx_close])
        msg_id_box.input(fn=lookup_context, inputs=[msg_id_box],
                         outputs=[ctx_md, ctx_close])
        ctx_close.click(fn=lambda: (gr.update(visible=False), gr.update(visible=False)),
                        outputs=[ctx_md, ctx_close])
        theme_btn.click(fn=None, js=_JS_TOGGLE)

    print(f"Opening at http://localhost:{port}")
    app.launch(server_name="0.0.0.0", server_port=port, share=False,
               theme=_THEME, css=_CSS, js=_JS_INIT)
