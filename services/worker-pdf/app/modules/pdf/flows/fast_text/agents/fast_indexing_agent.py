"""Fast PDF Indexing Agent — Text-based, No VLM.

Pipeline:
  PDF → PyMuPDF text extraction → RecursiveCharacterTextSplitter (300 tokens)
       → FastEmbed (BAAI/bge-small-en-v1.5) → Qdrant HNSW upsert

This is ~10-50x faster than the VLM ColPali pipeline, trading visual
understanding for speed. Ideal for text-heavy documents (contracts,
reports, papers, manuals).
"""
from __future__ import annotations

import os
import uuid
import structlog
from typing import Any, Dict, List, Optional

logger = structlog.get_logger(__name__)

# ── Lazy singletons ────────────────────────────────────────────────────────────
_embed_model = None


def _get_embedding_model():
    """Lazy-load FastEmbed model (tiny, no GPU needed)."""
    global _embed_model
    if _embed_model is None:
        from fastembed import TextEmbedding
        logger.info("loading_fastembed_model", model="BAAI/bge-small-en-v1.5")
        _embed_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        logger.info("fastembed_model_loaded")
    return _embed_model


def _extract_text_from_pdf(file_path: str) -> List[Dict[str, Any]]:
    """Extract text page-by-page using PyMuPDF (fitz). Returns list of page dicts."""
    import fitz  # PyMuPDF

    pages = []
    doc = fitz.open(file_path)
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        if text and text.strip():
            pages.append({"page_num": page_num + 1, "text": text.strip()})
    doc.close()
    logger.info("text_extraction_done", file=file_path, pages_with_text=len(pages))
    return pages


def _split_into_chunks(pages: List[Dict[str, Any]], chunk_size: int = 300, overlap: int = 50) -> List[Dict[str, Any]]:
    """Split page text into overlapping chunks using a simple word-based splitter."""
    chunks = []
    for page in pages:
        words = page["text"].split()
        step = chunk_size - overlap
        for start in range(0, len(words), step):
            chunk_words = words[start: start + chunk_size]
            if len(chunk_words) < 20:  # Skip tiny fragments
                continue
            chunks.append({
                "page_num": page["page_num"],
                "text": " ".join(chunk_words),
                "chunk_index": len(chunks),
            })
    logger.info("chunking_done", total_chunks=len(chunks))
    return chunks


def _embed_chunks(chunks: List[Dict[str, Any]]) -> List[List[float]]:
    """Generate dense embeddings for all chunks via FastEmbed."""
    model = _get_embedding_model()
    texts = [c["text"] for c in chunks]
    embeddings = list(model.embed(texts))
    logger.info("embedding_done", num_vectors=len(embeddings))
    return [list(e) for e in embeddings]


# ── Public API ─────────────────────────────────────────────────────────────────

async def fast_indexing_agent(source_id: str) -> Dict[str, Any]:
    """Index a PDF DataSource using the fast text pipeline.
    
    Writes to collection: `fast_ds_{source_id_no_dashes}`
    Marks DataSource.indexing_status = 'done' on success.
    """
    from app.models.data_source import DataSource
    from app.infrastructure.database.postgres import async_session_factory
    from app.modules.pdf.utils.qdrant_hnsw import QdrantHNSWManager
    from sqlalchemy import select, update

    logger.info("fast_indexing_started", source_id=source_id)

    async with async_session_factory() as db:
        res = await db.execute(select(DataSource).where(DataSource.id == uuid.UUID(source_id)))
        source = res.scalar_one_or_none()
        if not source:
            return {"error": f"DataSource {source_id} not found"}

        file_path = source.file_path
        if not file_path or not os.path.exists(file_path):
            await db.execute(
                update(DataSource)
                .where(DataSource.id == uuid.UUID(source_id))
                .values(indexing_status="failed")
            )
            await db.commit()
            return {"error": f"File not found: {file_path}"}

        # Mark as running with 5% progress
        await db.execute(
            update(DataSource)
            .where(DataSource.id == uuid.UUID(source_id))
            .values(
                indexing_status="running",
                schema_json={**(source.schema_json or {}), "progress": 5, "current_step": "Initializing metadata..."}
            )
        )
        await db.commit()

    try:
        # ── Step 1: Text Extraction ──────────────────────────────────────────
        async with async_session_factory() as db:
            await db.execute(
                update(DataSource)
                .where(DataSource.id == uuid.UUID(source_id))
                .values(schema_json={**(source.schema_json or {}), "progress": 10, "current_step": "Extracting text from PDF..."})
            )
            await db.commit()

        pages = _extract_text_from_pdf(file_path)
        if not pages:
            raise ValueError("No text extracted from PDF. File may be image-only — use Deep Vision mode instead.")

        # ── Step 2: Chunking ────────────────────────────────────────────────
        async with async_session_factory() as db:
            await db.execute(
                update(DataSource)
                .where(DataSource.id == uuid.UUID(source_id))
                .values(schema_json={**(source.schema_json or {}), "progress": 25, "current_step": "Partitioning text into neural chunks..."})
            )
            await db.commit()

        chunks = _split_into_chunks(pages, chunk_size=300, overlap=50)

        # ── Step 3: Embedding ───────────────────────────────────────────────
        async with async_session_factory() as db:
            await db.execute(
                update(DataSource)
                .where(DataSource.id == uuid.UUID(source_id))
                .values(schema_json={**(source.schema_json or {}), "progress": 40, "current_step": "Generating dense semantic embeddings..."})
            )
            await db.commit()

        vectors = _embed_chunks(chunks)

        # ── Step 4: Qdrant Upsert ───────────────────────────────────────────
        async with async_session_factory() as db:
            await db.execute(
                update(DataSource)
                .where(DataSource.id == uuid.UUID(source_id))
                .values(schema_json={**(source.schema_json or {}), "progress": 70, "current_step": "Syncing vectors with Qdrant Cloud..."})
            )
            await db.commit()

        collection_name = f"fast_ds_{source_id.replace('-', '')}"
        qdrant = QdrantHNSWManager(collection_name=collection_name)
        qdrant.ensure_collection()

        # Delete any existing chunks first (idempotency)
        try:
            qdrant.delete_by_source(source_id)
        except Exception:
            pass  # Collection might be fresh

        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{source_id}_{i}"))
            points.append({
                "id": point_id,
                "vector": vector,
                "payload": {
                    "source_id": source_id,
                    "page_num": chunk["page_num"],
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                },
            })

        # Upsert in batches of 100
        BATCH = 100
        for b in range(0, len(points), BATCH):
            qdrant.upsert_chunks(points[b: b + BATCH])
            
            # Sub-progress for large files
            progress = min(70 + int((b / len(points)) * 25), 95)
            async with async_session_factory() as db:
                await db.execute(
                    update(DataSource)
                    .where(DataSource.id == uuid.UUID(source_id))
                    .values(schema_json={**(source.schema_json or {}), "progress": progress, "current_step": f"Uploading vectors... ({b}/{len(points)})"})
                )
                await db.commit()

        logger.info("fast_indexing_upserted", source_id=source_id, total_points=len(points))

        # ── Step 5: Mark Done ───────────────────────────────────────────────
        async with async_session_factory() as db:
            await db.execute(
                update(DataSource)
                .where(DataSource.id == uuid.UUID(source_id))
                .values(
                    indexing_status="done",
                    schema_json={
                        "page_count": len(pages),
                        "chunk_count": len(chunks),
                        "indexed": True,
                        "indexing_mode": "fast_text",
                        "progress": 100,
                        "current_step": "Indexing complete. Neural sync verified."
                    },
                )
            )
            await db.commit()

        logger.info("fast_indexing_complete", source_id=source_id, chunks=len(chunks), pages=len(pages))
        return {"status": "success", "chunks": len(chunks), "pages_with_text": len(pages)}

    except Exception as e:
        logger.error("fast_indexing_failed", source_id=source_id, error=str(e))
        async with async_session_factory() as db:
            from sqlalchemy import update as sql_update
            await db.execute(
                sql_update(DataSource)
                .where(DataSource.id == uuid.UUID(source_id))
                .values(indexing_status="failed")
            )
            await db.commit()
        return {"error": str(e)}
