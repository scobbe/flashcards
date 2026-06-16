#!/usr/bin/env python3
"""Read personal (Teams For Life) chat history from the local new-Teams cache.

Microsoft Graph does not expose personal/consumer Teams chats, but the new Teams
(v2) desktop app caches them locally in a Chromium IndexedDB/LevelDB store. This
reads that cache read-only: it snapshots the leveldb (to avoid the live lock),
then extracts conversations + messages.

    python scripts/teams_personal.py list-chats
    python scripts/teams_personal.py messages --chat "Mum" --limit 30
    python scripts/teams_personal.py serve        # run as an MCP stdio server

Read-only. Only data the app has cached locally is available.

Dependency: ccl_chromium_reader
    pip install "ccl_chromium_reader @ git+https://github.com/cclgroupltd/ccl_chromium_reader"
"""
import argparse
import ast
import html
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TFL_LEVELDB = Path(
    "~/Library/Containers/com.microsoft.teams2/Data/Library/Application Support/"
    "Microsoft/MSTeams/EBWebView/WV2Profile_tfl/IndexedDB/"
    "https_teams.live.com_0.indexeddb.leveldb"
).expanduser()

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean_text(s):
    """Strip RichText HTML and fix bytes-repr mojibake from the serializer."""
    if isinstance(s, bytes):
        s = s.decode("utf-8", "replace")
    if not isinstance(s, str):
        return ""
    if s.startswith(("b'", 'b"')):
        try:
            s = ast.literal_eval(s).decode("utf-8", "replace")
        except Exception:
            pass
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    return _WS.sub(" ", s).strip()


def _snapshot():
    """Copy the leveldb to a temp dir (minus LOCK) so we can read it while Teams runs."""
    if not TFL_LEVELDB.exists():
        raise SystemExit(f"Personal Teams cache not found at:\n  {TFL_LEVELDB}\n"
                         "Is the new Teams app installed and signed into your personal account?")
    tmp = Path(tempfile.mkdtemp(prefix="tfl_snap_"))
    dst = tmp / TFL_LEVELDB.name
    shutil.copytree(TFL_LEVELDB, dst)
    (dst / "LOCK").unlink(missing_ok=True)
    return tmp, dst


def _open(dst):
    from ccl_chromium_reader.ccl_chromium_indexeddb import WrappedIndexDB
    return WrappedIndexDB(str(dst))


def _store(idb, store_name, exclude=None):
    for dbid in idb.database_ids:
        wdb = idb[dbid.dbid_no]
        if store_name in wdb.object_store_names and (not exclude or exclude not in (dbid.name or "")):
            return wdb.get_object_store_by_name(store_name)
    return None


def _records(store):
    if store is None:
        return
    for rec in store.iterate_records():
        v = rec.value
        if isinstance(v, dict):
            yield v


def load_profiles(idb):
    out = {}
    for v in _records(_store(idb, "profiles")):
        mri = v.get("mri")
        if mri:
            out[mri] = _clean_text(v.get("displayName") or v.get("userPrincipalName") or mri)
    return out


def load_conversations(idb):
    out = {}
    for v in _records(_store(idb, "conversations", exclude="internal")):
        cid = v.get("id")
        if not cid:
            continue
        topic = ((v.get("threadProperties") or {}).get("topic")) or ""
        out[cid] = {"topic": _clean_text(topic) if topic else "",
                    "last": v.get("lastMessageTimeUtc") or 0}
    return out


def load_messages(idb, profiles):
    msgs = []
    for chain in _records(_store(idb, "replychains", exclude="streams")):
        mmap = chain.get("messageMap") or {}
        for m in mmap.values():
            if not isinstance(m, dict):
                continue
            mt = m.get("messageType") or ""
            # messageType is "Text", "RichText", or "RichText/Html", "RichText/Media_Card", etc.
            if m.get("type") != "Message" or not (mt == "Text" or mt.startswith("RichText")):
                continue
            text = _clean_text(m.get("content"))
            if not text:
                continue
            sender = m.get("creator") or ""
            msgs.append({
                "conversationId": m.get("conversationId") or chain.get("conversationId"),
                "sender": profiles.get(sender, m.get("imDisplayName") or sender),
                "sender_id": sender,
                "time": m.get("clientArrivalTime") or m.get("originalArrivalTime") or 0,
                "text": text,
            })
    msgs.sort(key=lambda x: x["time"])
    return msgs


def _ts(ms):
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"


def chat_name(cid, conv, msgs_by_chat, me_id, profiles):
    """Group-chat name from topic, else the other participants' names (1:1/group)."""
    topic = conv.get(cid, {}).get("topic")
    if topic:
        return topic
    others = []
    for m in msgs_by_chat.get(cid, []):
        if m["sender_id"] and m["sender_id"] != me_id and m["sender"] not in others:
            others.append(m["sender"])
    return ", ".join(others) if others else (cid or "unknown")


def build():
    tmp, dst = _snapshot()
    try:
        idb = _open(dst)
        profiles = load_profiles(idb)
        me_id = next((mri for mri, n in profiles.items() if mri.startswith("8:") and ":live:" not in mri), None)
        conv = load_conversations(idb)
        msgs = load_messages(idb, profiles)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    by_chat = {}
    for m in msgs:
        by_chat.setdefault(m["conversationId"], []).append(m)
    chats = []
    for cid, ms in by_chat.items():
        chats.append({"id": cid, "name": chat_name(cid, conv, by_chat, me_id, profiles),
                      "count": len(ms), "last": ms[-1]["time"]})
    chats.sort(key=lambda c: c["last"], reverse=True)
    return {"chats": chats, "by_chat": by_chat, "profiles": profiles, "me": me_id}


# ----- CLI -----

def cmd_list_chats(data, args):
    for c in data["chats"]:
        if args.query and args.query.lower() not in c["name"].lower():
            continue
        print(f"{_ts(c['last'])}  {c['count']:>5} msgs  {c['name']}")


def cmd_messages(data, args):
    matches = [c for c in data["chats"] if args.chat.lower() in c["name"].lower()]
    if not matches:
        print(f"No chat matching {args.chat!r}. Try `list-chats`.")
        return
    target = matches[0]
    msgs = data["by_chat"][target["id"]][-args.limit:]
    print(f"=== {target['name']} ({len(data['by_chat'][target['id']])} msgs, showing {len(msgs)}) ===")
    for m in msgs:
        print(f"[{_ts(m['time'])}] {m['sender']}: {m['text']}")


def serve():
    """Minimal MCP stdio server (newline-delimited JSON-RPC 2.0)."""
    TOOLS = [
        {"name": "list_chats", "description": "List personal Teams chats (most recent first), optional name filter.",
         "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}},
        {"name": "get_messages", "description": "Get messages from a personal Teams chat matched by name substring.",
         "inputSchema": {"type": "object", "properties": {"chat": {"type": "string"}, "limit": {"type": "integer"}},
                          "required": ["chat"]}},
    ]

    def respond(_id, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": _id}
        if error:
            msg["error"] = error
        else:
            msg["result"] = result
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def text_result(s):
        return {"content": [{"type": "text", "text": s}]}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method, _id = req.get("method"), req.get("id")
        if method == "initialize":
            respond(_id, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "teams-personal", "version": "0.1.0"}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            respond(_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = req["params"]["name"]
            a = req["params"].get("arguments") or {}
            data = build()
            if name == "list_chats":
                q = (a.get("query") or "").lower()
                lines = [f"{_ts(c['last'])}  {c['count']} msgs  {c['name']}"
                         for c in data["chats"] if q in c["name"].lower()]
                respond(_id, text_result("\n".join(lines) or "no chats"))
            elif name == "get_messages":
                chat = a.get("chat", "")
                limit = int(a.get("limit") or 40)
                matches = [c for c in data["chats"] if chat.lower() in c["name"].lower()]
                if not matches:
                    respond(_id, text_result(f"no chat matching {chat!r}"))
                else:
                    t = matches[0]
                    ms = data["by_chat"][t["id"]][-limit:]
                    body = f"=== {t['name']} ===\n" + "\n".join(
                        f"[{_ts(m['time'])}] {m['sender']}: {m['text']}" for m in ms)
                    respond(_id, text_result(body))
            else:
                respond(_id, error={"code": -32601, "message": f"unknown tool {name}"})
        elif _id is not None:
            respond(_id, error={"code": -32601, "message": f"unknown method {method}"})


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list-chats"); p.add_argument("--query", default="")
    p = sub.add_parser("messages"); p.add_argument("--chat", required=True); p.add_argument("--limit", type=int, default=30)
    sub.add_parser("serve")
    args = ap.parse_args(argv)
    if args.cmd == "serve":
        return serve()
    data = build()
    if args.cmd == "list-chats":
        cmd_list_chats(data, args)
    elif args.cmd == "messages":
        cmd_messages(data, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
