import argparse
import asyncio
import json
import logging

from tgram.adapters.repo_channels import ChannelRepo
from tgram.adapters.repo_embeddings import EmbeddingRepo
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.repo_topics import TopicRepo
from tgram.adapters.telegram import TelegramClientAdapter
from tgram.config import Config
from tgram.services.ingest import IngestService


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tgram")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list_chan", help="List all Telegram dialogs you have access to")

    peek = sub.add_parser("peek", help="Fetch a few raw messages and print their structure")
    peek.add_argument("--chat", type=int, default=None)
    peek.add_argument("--n", type=int, default=3, help="Number of messages to fetch")

    fn = sub.add_parser("fetch_new", help="Fetch messages newer than the highest stored ID")
    fn.add_argument("--chat", type=int, default=None)

    fo = sub.add_parser("fetch_old", help="Fetch messages older than the lowest stored ID")
    fo.add_argument("--chat", type=int, default=None)
    fo.add_argument("--limit", type=int, default=None)
    fo.add_argument("--loop", action="store_true", help="Keep fetching until channel beginning")

    fg = sub.add_parser("fetch_gap", help="Fetch a specific message ID range")
    fg.add_argument("start", type=int)
    fg.add_argument("end", type=int)
    fg.add_argument("--chat", type=int, default=None)

    fs = sub.add_parser("fetch_scan", help="Show gaps in stored messages")
    fs.add_argument("--chat", type=int, default=None)

    st = sub.add_parser("status", help="Show storage stats for a chat")
    st.add_argument("--chat", type=int, default=None)

    sy = sub.add_parser("sync_topics", help="Fetch topic names from Telegram and store them")
    sy.add_argument("--chat", type=int, default=None)

    lt = sub.add_parser("list_topics", help="List all known topics with message counts")
    lt.add_argument("--chat", type=int, default=None)

    # ── search ────────────────────────────────────────────────────────────────
    sr = sub.add_parser("search", help="Full-text search the message archive")
    sr.add_argument("query", help='Search query (use "phrase" for phrase, term* for prefix)')
    sr.add_argument("--chat",    type=int, default=None)
    sr.add_argument("--topic",   type=int, default=None, help="Filter by topic_id")
    sr.add_argument("--since",   default=None, help="From date YYYY-MM-DD")
    sr.add_argument("--until",   default=None, help="To date YYYY-MM-DD")
    sr.add_argument("--limit",   type=int, default=20)
    sr.add_argument("--context", type=int, default=0, metavar="N",
                    help="Show N messages before and after each hit")

    sub.add_parser("rebuild_fts", help="Rebuild the full-text search index from scratch")

    ea = sub.add_parser("embed_all", help="Generate semantic embeddings for all stored messages")
    ea.add_argument("--chat",  type=int, default=None)
    ea.add_argument("--batch", type=int, default=100, help="Messages per embedding batch")

    # ── AI Q&A ────────────────────────────────────────────────────────────────
    wb = sub.add_parser("web", help="Launch Gradio chat UI in browser")
    wb.add_argument("--chat",   type=int, default=None)
    wb.add_argument("--port",   type=int, default=7860)
    wb.add_argument("--think",  action="store_true", help="Enable Qwen chain-of-thought")

    ak = sub.add_parser("ask", help="Ask a question answered from the archive using Ollama")
    ak.add_argument("question")
    ak.add_argument("--chat",      type=int, default=None)
    ak.add_argument("--topic",     type=int, default=None)
    ak.add_argument("--limit",     type=int, default=30,
                    help="Number of messages to retrieve as context")
    ak.add_argument("--no-think",  action="store_true",
                    help="Disable Qwen3 chain-of-thought (faster, less verbose)")
    ak.add_argument("--no-stream", action="store_true",
                    help="Print full answer at once instead of streaming")

    # ── multi-channel commands ─────────────────────────────────────────────────
    ch_p = sub.add_parser("channels", help="Manage tracked channels")
    ch_sub = ch_p.add_subparsers(dest="ch_cmd", required=True)
    ch_sub.add_parser("list", help="List all known channels")
    ch_sub.add_parser("refresh", help="Sync channel list from Telegram dialogs")
    ch_en = ch_sub.add_parser("enable",  help="Enable channels for fetch_all")
    ch_en.add_argument("chat_ids", nargs="+", type=int)
    ch_dis = ch_sub.add_parser("disable", help="Disable channels from fetch_all")
    ch_dis.add_argument("chat_ids", nargs="+", type=int)

    sub.add_parser("fetch_all", help="Fetch new messages for all enabled channels")
    sub.add_parser("daemon",    help="Start background polling daemon")

    return p


async def run(args) -> int:
    cfg = Config.load()
    chat_id = getattr(args, "chat", None) or cfg.default_chat_id

    # ── commands that don't need storage ──────────────────────────────────────

    if args.cmd == "list_chan":
        async with TelegramClientAdapter(cfg.api_id, cfg.api_hash, cfg.sessions_dir) as tg:
            dialogs = await tg.list_dialogs()
        for d in dialogs:
            forum = " [forum]" if d["is_forum"] else ""
            print(f"{d['chat_id']:>15}  {d['type']:<10}  {d['title']}{forum}")
        return 0

    if args.cmd == "peek":
        async with TelegramClientAdapter(cfg.api_id, cfg.api_hash, cfg.sessions_dir) as tg:
            count = 0
            async for msg in tg.iter_history(chat_id, limit=args.n):
                raw = json.loads(msg.raw_json)
                print(f"\n{'='*60}")
                print(f"  id={msg.id}  date={msg.date}  from=@{msg.username}")
                print(f"  text={repr(msg.text)}")
                print(f"  media_type={msg.media_type}")
                print(f"  reply_to_message_id={msg.reply_to_message_id}")
                print(f"  reply_to_top_message_id={msg.reply_to_top_message_id}")
                print(f"  virtual_topic_id={msg.virtual_topic_id}")
                print(f"\n--- raw_json (trimmed) ---")
                interesting = {k: raw.get(k) for k in (
                    "_", "id", "date", "message", "from_id", "peer_id",
                    "reply_to", "media", "entities", "views", "replies", "reactions",
                ) if k in raw}
                print(json.dumps(interesting, indent=2, ensure_ascii=False, default=str))
                count += 1
        print(f"\n{'='*60}")
        print(f"Fetched {count} message(s) from chat {chat_id}")
        return 0

    # ── commands that need storage ─────────────────────────────────────────────

    repo        = MessageRepo(cfg.db_path)
    repo_topics = TopicRepo(cfg.db_path)
    repo_chan   = ChannelRepo(cfg.db_path)
    repo_embed  = EmbeddingRepo(cfg.db_path)

    if args.cmd == "embed_all":
        from tgram.adapters.llm_ollama import OllamaAdapter
        from tgram.services.embed import EmbedService
        svc_embed = EmbedService(OllamaAdapter(), repo_embed)
        svc_embed.backfill(chat_id=args.chat, batch_size=args.batch)
        return 0

    if args.cmd == "search":
        from tgram.adapters.search_fts import FTSSearch
        from tgram.services.search import SearchService
        fts = FTSSearch(cfg.db_path)
        svc_search = SearchService(fts)
        hits = svc_search.search(
            args.query,
            chat_id=args.chat,
            topic_id=args.topic,
            since=args.since,
            until=args.until,
            limit=args.limit,
        )
        if not hits:
            print("(no results)")
            return 0

        def fmt_who(username, from_user_id):
            if username:
                return f"@{username}"
            if from_user_id:
                return f"user:{from_user_id}"
            return "unknown"

        for h in hits:
            date  = h.date[:16].replace("T", " ")
            who   = fmt_who(h.username, h.from_user_id)
            topic = f" in {h.topic_title}" if h.topic_title else ""
            print(f"── [{date}] {who}{topic}  (chat {h.chat_id} / msg {h.message_id})")

            if args.context > 0:
                ctx = fts.get_context(h, before=args.context, after=args.context)
                for msg in ctx:
                    marker = ">>>" if msg.is_hit else "   "
                    d = msg.date[:16].replace("T", " ")
                    w = fmt_who(msg.username, msg.from_user_id)
                    t = (msg.text or "").replace("\n", " ")[:120]
                    print(f"   {marker} [{d}] {w}: {t}")
            else:
                print(f"   {h.snippet}")
            print()
        return 0

    if args.cmd == "rebuild_fts":
        from tgram.adapters.search_fts import FTSSearch
        print("Rebuilding FTS index… ", end="", flush=True)
        count = FTSSearch(cfg.db_path).rebuild()
        print(f"{count:,} rows indexed.")
        return 0

    if args.cmd == "web":
        from tgram.interfaces.web import launch
        launch(cfg, chat_id=args.chat,
               think=args.think, port=args.port)
        return 0

    if args.cmd == "ask":
        from tgram.adapters.llm_ollama import OllamaAdapter
        from tgram.adapters.search_fts import FTSSearch
        from tgram.services.ai import AIService

        ollama = OllamaAdapter()
        fts_ask = FTSSearch(cfg.db_path, embedding_repo=repo_embed)
        ai = AIService(fts_ask, ollama)
        stream = not getattr(args, "no_stream", False)
        think  = not getattr(args, "no_think",  False)

        response, hits = ai.ask(
            args.question,
            chat_id=args.chat,
            topic_id=args.topic,
            limit=args.limit,
            stream=stream,
            think=think,
        )
        print(f"(retrieved {len(hits)} messages as context)\n")
        if stream:
            for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta:
                    print(delta, end="", flush=True)
            print()
        else:
            print(response)
        return 0

    if args.cmd == "fetch_scan":
        gaps = repo.find_gaps(chat_id)
        if not gaps:
            print(f"No gaps in chat {chat_id}.")
        else:
            print(f"{len(gaps)} gap(s) in chat {chat_id}:")
            for s, e in gaps:
                print(f"  {s}–{e}  ({e - s + 1} message(s))")
        return 0

    if args.cmd == "status":
        mn = repo.min_id(chat_id)
        mx = repo.max_id(chat_id)
        total = repo.count(chat_id)
        gaps = repo.find_gaps(chat_id)
        known = len(repo_topics.list_for_chat(chat_id))
        unknown = len(repo_topics.unknown_topic_ids(chat_id))
        print(f"chat {chat_id}")
        print(f"  stored : {total:,} messages")
        print(f"  id range: {mn} – {mx}")
        print(f"  gaps   : {len(gaps)}")
        print(f"  topics : {known} known, {unknown} unknown (run sync_topics to resolve)")
        return 0

    if args.cmd == "list_topics":
        rows = repo_topics.stats_for_chat(chat_id)
        if not rows:
            print("No topics found. Run sync_topics first.")
            return 0
        print(f"{'topic_id':>10}  {'messages':>8}  {'last active':<20}  title")
        print("-" * 70)
        for r in rows:
            last = (r["last_active"] or "")[:10]
            print(f"{r['topic_id']:>10}  {r['msg_count']:>8}  {last:<20}  {r['title']}")
        return 0

    # ── DB-only channel management (no Telegram needed) ───────────────────────

    if args.cmd == "channels" and args.ch_cmd == "list":
        for ch in repo_chan.list_all():
            mark  = "✓" if ch.enabled else "·"
            last  = ch.last_fetch_at.strftime("%Y-%m-%d %H:%M") if ch.last_fetch_at else "never"
            forum = " [forum]" if ch.is_forum else ""
            print(f"{mark} {ch.chat_id:>15}  {ch.type:<10}  {last:<16}  {ch.title or ''}{forum}")
        return 0

    if args.cmd == "channels" and args.ch_cmd == "enable":
        for cid in args.chat_ids:
            repo_chan.set_enabled(cid, True)
        print(f"Enabled {len(args.chat_ids)} channel(s).")
        return 0

    if args.cmd == "channels" and args.ch_cmd == "disable":
        for cid in args.chat_ids:
            repo_chan.set_enabled(cid, False)
        print(f"Disabled {len(args.chat_ids)} channel(s).")
        return 0

    # ── daemon: manages its own Telegram connection ───────────────────────────

    if args.cmd == "daemon":
        from tgram.interfaces.daemon import run_daemon
        await run_daemon()
        return 0

    # ── commands that need Telegram + storage ─────────────────────────────────

    async with TelegramClientAdapter(cfg.api_id, cfg.api_hash, cfg.sessions_dir) as tg:
        svc = IngestService(tg, repo)

        if args.cmd == "fetch_new":
            n = await svc.fetch_new(chat_id)
            print(f"Saved {n} new message(s).")

        elif args.cmd == "fetch_old":
            if getattr(args, "loop", False):
                n = await svc.fetch_old_loop(chat_id)
                print(f"Done. Saved {n} message(s) total.")
            else:
                n = await svc.fetch_old(chat_id, limit=args.limit)
                print(f"Saved {n} older message(s).")

        elif args.cmd == "fetch_gap":
            n = await svc.fetch_gap(chat_id, args.start, args.end)
            print(f"Saved {n} message(s) in range {args.start}–{args.end}.")

        elif args.cmd == "sync_topics":
            n = await svc.sync_topics(chat_id, repo_topics)
            if n == 0:
                print("All topic names already up to date.")
            else:
                print(f"Synced {n} topic name(s).")

        elif args.cmd == "channels" and args.ch_cmd == "refresh":
            n = await svc.refresh_dialogs(repo_chan)
            print(f"Synced {n} dialog(s) to channels table.")

        elif args.cmd == "fetch_all":
            results = await svc.fetch_all_new(repo_chan, repo_topics)
            total  = sum(n for n in results.values() if n > 0)
            failed = [cid for cid, n in results.items() if n < 0]
            print(f"Fetched {total} new message(s) across {len(results)} channel(s).", end="")
            if failed:
                print(f" {len(failed)} failed — check logs.")
            else:
                print()

    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Silence Telethon's connection-level chatter; keep WARNING+ visible
    logging.getLogger("telethon.network.mtprotosender").setLevel(logging.WARNING)
    logging.getLogger("telethon.extensions.messagepacker").setLevel(logging.WARNING)
    args = build_parser().parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
