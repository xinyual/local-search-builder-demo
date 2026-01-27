from docling_core.transforms.chunker import HybridChunker

# -----------------------------
# Docling parse + chunk
# -----------------------------

def chunk_by_docling_chunker(doc):
    chunker = HybridChunker(merge_list_items=True)
    chunks = list(chunker.chunk(dl_doc=doc))
    res = []
    for chunk in chunks:
        meta = chunk.meta
        headings = meta.headings if meta and meta.headings else []
        res.append({"text": chunker.contextualize(chunk), "path": " ".join(headings)})
    return res