PY           := .venv/bin/python
TGRAM        := $(PY) -m tgram
DEFAULT_CHAT := $(shell grep ^CHAT_ID .env | cut -d= -f2)
# CHAT is command-line only — no default.
# ask/search/web/embed: omit --chat when CHAT unset → searches all chats.
# fetch/status/topics: fall back to DEFAULT_CHAT from .env when CHAT unset.
_CHAT        = $(if $(CHAT),--chat $(CHAT),)
_FETCH_CHAT  = --chat $(or $(CHAT),$(DEFAULT_CHAT))

# ── Auth & discovery ──────────────────────────────────────────────────────────
list-chan:
	$(TGRAM) list_chan

channels:
	$(TGRAM) channels list

channels-refresh:
	$(TGRAM) channels refresh

channels-enable:
	$(TGRAM) channels enable -- $(or $(CHAT),$(DEFAULT_CHAT))

channels-disable:
	$(TGRAM) channels disable -- $(or $(CHAT),$(DEFAULT_CHAT))

# ── Fetching ──────────────────────────────────────────────────────────────────
fetch-new:
	$(TGRAM) fetch_new $(_FETCH_CHAT)

fetch-old:
	$(TGRAM) fetch_old $(_FETCH_CHAT)

fetch-old-loop:
	$(TGRAM) fetch_old $(_FETCH_CHAT) --loop

fetch-all:
	$(TGRAM) fetch_all

fetch-scan:
	$(TGRAM) fetch_scan $(_FETCH_CHAT)

status:
	$(TGRAM) status $(_FETCH_CHAT)

daemon:
	$(TGRAM) daemon

# ── Topics ────────────────────────────────────────────────────────────────────
sync-topics:
	$(TGRAM) sync_topics $(_FETCH_CHAT)

list-topics:
	$(TGRAM) list_topics $(_FETCH_CHAT)

# ── Search ────────────────────────────────────────────────────────────────────
rebuild-fts:
	$(TGRAM) rebuild_fts

search:
	$(TGRAM) search "$(Q)" $(_CHAT)

# ── Embeddings ────────────────────────────────────────────────────────────────
embed:
	$(TGRAM) embed_all $(_CHAT)

# ── AI Q&A ────────────────────────────────────────────────────────────────────
ask:
	$(TGRAM) ask "$(Q)" $(_CHAT)

web:
	$(TGRAM) web $(_CHAT)

.PHONY: list-chan channels channels-refresh channels-enable channels-disable \
        fetch-new fetch-old fetch-old-loop fetch-all fetch-scan status daemon \
        sync-topics list-topics rebuild-fts search embed ask web
