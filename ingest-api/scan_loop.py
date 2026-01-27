from constants import *
import os, sqlite3, time
from typing import List, Tuple
from ingest import *
from ingest import _bulk_index_chunks_batched_docling
from sqlite_operations import *





async def scan_one_watch(index_name: str, folder: str, mode: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_scan_one_watch_sync, index_name, folder, mode)

def _scan_one_watch_sync(index_name: str, folder: str, mode: str) -> Dict[str, Any]:
    if not folder or not os.path.isdir(folder):
        return {
            "ok": False,
            "index_name": index_name,
            "folder": folder,
            "mode": mode,
            "error": f"folder not found or not a directory: {folder}",
        }

    new_files = select_new_files(index_name=index_name, folder=folder)
    print(new_files)
    if not new_files:
        return {
            "ok": True,
            "index_name": index_name,
            "folder": folder,
            "mode": mode,
            "new_files": 0,
            "parsed_files": 0,
            "indexed_chunks": 0,
            "failures": 0,
            "message": "no new files",
        }

    converter: DocumentConverter = GLOBAL_RESOURCE.get("converter")
    if converter is None:
        return {
            "ok": False,
            "index_name": index_name,
            "folder": folder,
            "mode": mode,
            "error": "converter not initialized",
        }

    parsed_files, indexed_chunks, failures = _bulk_index_chunks_batched_docling(
        get_os_client(), index_name, "", "", folder, new_files, converter)

    mark_ingested(index_name=index_name, recs=parsed_files)

    return {
        "ok": True,
        "index_name": index_name,
        "folder": folder,
        "mode": mode,
        "new_files": len(new_files),
        "parsed_files": parsed_files,
        "indexed_chunks": indexed_chunks,
        "failures": failures
    }






def open_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


# GLOBAL_RESOURCE["watch_map"] = {
#   "docs": {
#      "index_name": "docs",
#      "folder": "/data/tmpPages",
#      "type": "BM25",
#      "enabled": True,
#      "interval_s": 1800,
#      "last_scan_ts": 0,
#   },
# }

def due(w) -> bool:
    if not w.get("enabled", True):
        return False
    interval_s = int(w.get("interval_s", 1800))
    last_ts = int(w.get("last_scan_ts", 0))
    return (int(time.time()) - last_ts) >= interval_s

async def scan_loop():
    while True:
        await asyncio.sleep(10)

        async with WATCH_LOCK:
            watch_items = list(GLOBAL_RESOURCE.get("watch_map", {}).items())
        print("watch_items: ", watch_items)
        now = int(time.time())
        for index_name, w in watch_items:
            if not due(w):
                continue

            folder = w["folder"]
            mode = w.get("type", "BM25")

            try:
                await scan_one_watch(index_name=index_name, folder=folder, mode=mode)

                # 更新 last_scan_ts
                async with WATCH_LOCK:
                    # watch 可能被删了，做下保护
                    ww = GLOBAL_RESOURCE.get("watch_map", {}).get(index_name)
                    if ww:
                        ww["last_scan_ts"] = now
            except Exception as e:
                # 失败不要阻塞别的 watch
                print(f"[watch] scan failed index={index_name} folder={folder}: {e}")
