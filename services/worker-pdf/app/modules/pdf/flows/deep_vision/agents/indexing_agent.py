"""PDF Indexing Agent — Vision-based ingestion using ColPali patches."""
import os
import uuid
import torch
import structlog
import json
from typing import Any, Dict, List, Optional
from PIL import Image
from pdf2image import convert_from_path, pdfinfo_from_path
from app.infrastructure.database.postgres import async_session_factory
from app.models.knowledge import Document, KnowledgeBase
from app.models.tenant import Tenant
from app.modules.pdf.flows.deep_vision.agents.pdf_agent import get_colpali
from app.modules.pdf.utils.qdrant_multivector import QdrantMultiVectorManager
from sqlalchemy import select, update as sql_update
from sqlalchemy.orm import selectinload
import gc

logger = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HUMAN-AI SYNERGY: PURE CLASSIFICATION BY USER
#
#  With this approach, Gemini is completely removed from indexing.
#  Classification is instantly mapped from the user's Hint, providing 
#  100% deterministic, zero-cost, instantaneous metadata.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Maps user-selected hint → static classification metadata (no AI needed)
_HINT_TO_META: Dict[str, Dict[str, str]] = {
    # ── Finance & Accounting ──
    "invoice":          {"doc_type": "Invoice / Receipt",           "industry": "Finance & Accounting"},
    "financial_report": {"doc_type": "Financial Report",            "industry": "Finance & Accounting"},
    "tax_return":       {"doc_type": "Tax Return / Declaration",    "industry": "Finance & Accounting"},
    "bank_statement":   {"doc_type": "Bank / Account Statement",    "industry": "Finance & Accounting"},
    "purchase_order":   {"doc_type": "Purchase Order",              "industry": "Finance & Accounting"},
    # ── Legal & Compliance ──
    "contract":         {"doc_type": "Legal Contract / Agreement",  "industry": "Legal & Compliance"},
    "nda":              {"doc_type": "Non-Disclosure Agreement",    "industry": "Legal & Compliance"},
    "policy":           {"doc_type": "Policy / Compliance Document","industry": "Legal & Compliance"},
    "audit_report":     {"doc_type": "Audit / Compliance Report",   "industry": "Legal & Compliance"},
    # ── Human Resources ──
    "hr_record":        {"doc_type": "HR / Personnel Record",       "industry": "Human Resources"},
    "resume":           {"doc_type": "Resume / CV",                 "industry": "Human Resources"},
    "perf_review":      {"doc_type": "Performance Review",          "industry": "Human Resources"},
    # ── Medical & Healthcare ──
    "medical_record":   {"doc_type": "Medical / Clinical Record",   "industry": "Medical & Healthcare"},
    "prescription":     {"doc_type": "Medical Prescription",        "industry": "Medical & Healthcare"},
    "lab_result":       {"doc_type": "Lab / Test Result",           "industry": "Medical & Healthcare"},
    # ── Tech & Engineering ──
    "tech_spec":        {"doc_type": "Technical Specification",     "industry": "Tech & Engineering"},
    "api_doc":          {"doc_type": "API / Developer Documentation","industry": "Tech & Engineering"},
    "arch_diagram":     {"doc_type": "Architecture Diagram / Doc",  "industry": "Tech & Engineering"},
    # ── Logistics & Supply Chain ──
    "bill_of_lading":   {"doc_type": "Bill of Lading",              "industry": "Logistics & Supply Chain"},
    "customs_decl":     {"doc_type": "Customs Declaration",         "industry": "Logistics & Supply Chain"},
    "inventory":        {"doc_type": "Inventory / Stock Report",    "industry": "Logistics & Supply Chain"},
    # ── Real Estate ──
    "lease_agreement":  {"doc_type": "Lease / Rental Agreement",    "industry": "Real Estate"},
    "property_deed":    {"doc_type": "Property Deed / Title",       "industry": "Real Estate"},
    # ── Construction & Engineering ──
    "floor_plan":       {"doc_type": "Floor Plan / Blueprint",      "industry": "Construction & Engineering"},
    "building_permit":  {"doc_type": "Building Permit / License",   "industry": "Construction & Engineering"},
    "construction_contract": {"doc_type": "Construction Contract",  "industry": "Construction & Engineering"},
    # ── General Business ──
    "business_report":  {"doc_type": "Business / Strategy Report",  "industry": "General Business"},
    "meeting_minutes":  {"doc_type": "Meeting Minutes",             "industry": "General Business"},
    # ── Marketing & Strategy ──
    "marketing_mat":    {"doc_type": "Marketing Material / Deck",   "industry": "Marketing & Strategy"},
    "campaign_plan":    {"doc_type": "Campaign / Marketing Plan",   "industry": "Marketing & Strategy"},
    "brand_guidelines": {"doc_type": "Brand Guidelines",            "industry": "Marketing & Strategy"},
    # ── Literature & Education ──
    "other_book":       {"doc_type": "Book / E-Book",               "industry": "Literature & Education"},
    "other_manual":     {"doc_type": "Instruction Manual",          "industry": "Literature & Education"},
    "textbook":         {"doc_type": "Textbook / Course Material",  "industry": "Literature & Education"},
    # ── Academic & Research ──
    "other_research":   {"doc_type": "Research Paper",              "industry": "Academic & Research"},
    "other_article":    {"doc_type": "News Article / Blog",         "industry": "Academic & Research"},
    "thesis":           {"doc_type": "Thesis / Dissertation",       "industry": "Academic & Research"},
    # ── Other / Custom ──
    "other_misc":       {"doc_type": "General Document",            "industry": "Other / Custom"},
}

def _build_static_metadata(hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Instantly builds structured metadata based on the user's categorical hint.
    Bypasses AI completely for maximum speed and cost efficiency.
    
    Priority:
    1. Direct slug lookup in _HINT_TO_META (e.g., "invoice")
    2. Heritage parsing for "Industry: X | Type: Y" format
    3. Generic fallback
    """
    if not hint:
        return {
            "doc_type": "Unclassified Document",
            "industry": "Unknown",
            "source_hint": "none",
            "dna": {"summary": "Awaiting generic RAG analysis"},
            "specialized_fields": {}
        }
    
    # 1. Direct Slug Lookup (Fastest/Deterministic)
    clean_hint = hint.strip().lower()
    if clean_hint in _HINT_TO_META:
        static_meta = _HINT_TO_META[clean_hint]
        return {
            "doc_type": static_meta["doc_type"],
            "industry": static_meta["industry"],
            "source_hint": hint,
            "dna": {"summary": f"Strategic {static_meta['doc_type']} identified in {static_meta['industry']} domain."},
            "specialized_fields": {
                "classification_mode": "taxonomy_direct",
                "slug": clean_hint,
                "extracted_at": "2026-03-24T07:18:00Z"
            }
        }
    
    # 2. Heritage Parsing Fallback
    try:
        industry = "Unknown"
        doc_type = "Unclassified Document"
        
        if "|" in hint:
            parts = hint.split("|")
            for part in parts:
                if "Industry:" in part:
                    industry = part.replace("Industry:", "").strip()
                if "Type:" in part:
                    doc_type = part.replace("Type:", "").strip()
        else:
            industry = hint.strip()

        return {
            "doc_type": doc_type,
            "industry": industry,
            "source_hint": hint,
            "dna": {"summary": f"Strategic {doc_type} identified in {industry} domain (Parsed)."},
            "specialized_fields": {
                "classification_mode": "heritage_parsed",
                "extracted_at": "2026-03-24T07:18:00Z"
            }
        }
    except Exception as e:
        logger.error("hint_parsing_failed", hint=hint, error=str(e))
        return {
            "doc_type": "Parsing Error",
            "industry": "Error",
            "source_hint": hint,
            "dna": {"summary": "Failed to extract strategic signals from heritage hint."},
            "specialized_fields": {}
        }


async def indexing_agent(doc_id: str) -> Dict[str, Any]:
    """Indexes a PDF document into Qdrant using ColPali multi-vectors."""
    async with async_session_factory() as db:
        # Fetch document with its context hierarchy (KB -> Tenant)
        query = (
            select(Document)
            .options(
                selectinload(Document.kb).selectinload(KnowledgeBase.tenant)
            )
            .where(Document.id == uuid.UUID(doc_id))
        )
        res = await db.execute(query)
        doc = res.scalar_one_or_none()
        if not doc:
            return {"error": f"Document {doc_id} not found."}

        # Extract context
        context_hint = doc.context_hint
        kb_id = doc.kb_id
        file_path = doc.file_path

        doc.status = "processing"
        await db.commit()

        try:
            # Fetch current metadata to preserve it during updates
            initial_meta = doc.metadata_json or {}
            
            result = await _run_indexing_core(
                id_for_meta=str(doc.id),
                file_path=file_path,
                kb_id=kb_id,
                context_hint=context_hint,
                is_source=False,
                initial_schema=initial_meta
            )
            
            # Update Document with result
            doc.status = "done"
            doc.indexed_at = doc.updated_at
            doc.metadata_json = result.get("metadata")
            await db.commit()
            return {"status": "success", "pages_indexed": result.get("pages"), "doc_type": result.get("metadata", {}).get("doc_type")}
            
        except Exception as e:
            logger.error("indexing_failed", doc_id=doc_id, error=str(e))
            doc.status = "error"
            await db.commit()
            return {"error": str(e)}

async def indexing_agent_source(source_id: str) -> Dict[str, Any]:
    """Indexes a PDF DataSource into Qdrant using ColPali multi-vectors."""
    from app.models.data_source import DataSource
    async with async_session_factory() as db:
        query = select(DataSource).where(DataSource.id == uuid.UUID(source_id))
        res = await db.execute(query)
        source = res.scalar_one_or_none()
        if not source:
            return {"error": f"DataSource {source_id} not found."}

        context_hint = source.context_hint
        file_path = source.file_path
        
        # DataSource doesn't have a status field for indexing, but we can log it
        logger.info("source_indexing_started", source_id=source_id)

        try:
            # Fetch current schema to preserve it during updates
            initial_schema = source.schema_json or {}
            
            result = await _run_indexing_core(
                id_for_meta=str(source.id),
                file_path=file_path,
                kb_id=None, # Direct uploads don't have kb_id
                context_hint=context_hint,
                is_source=True,
                initial_schema=initial_schema
            )
            
            # Optionally update source metadata
            source.schema_json = {
                **initial_schema,
                "page_count": result.get("pages"),
                "indexed": True,
                "metadata": result.get("metadata"),
                "progress": 100,
                "current_step": "Vision indexing complete. Neural map finalized."
            }
            source.indexing_status = "done"
            await db.commit()
            return {"status": "success", "pages_indexed": result.get("pages")}
            
        except Exception as e:
            logger.error("source_indexing_failed", source_id=source_id, error=str(e))
            async with async_session_factory() as db2:
                from sqlalchemy import update
                await db2.execute(
                    update(DataSource)
                    .where(DataSource.id == uuid.UUID(source_id))
                    .values(indexing_status="failed")
                )
                await db2.commit()
            return {"error": str(e)}

async def _run_indexing_core(
    id_for_meta: str, 
    file_path: str, 
    kb_id: Optional[uuid.UUID], 
    context_hint: Optional[str], 
    is_source: bool,
    initial_schema: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Core logic to index a PDF file into Qdrant."""
    if initial_schema is None:
        initial_schema = {}
        
    if not file_path or not os.path.exists(file_path):
        raise ValueError(f"File not found at {file_path}")

    # Get page count to process page-by-page (Memory Efficiency)
    info = pdfinfo_from_path(file_path)
    total_pages = info["Pages"]
    
    model, processor = get_colpali()
    
    # Collection naming logic: kb_{kb_id} if exists, else ds_{source_id}
    if kb_id:
        collection_name = f"kb_{str(kb_id).replace('-', '')}"
    else:
        collection_name = f"ds_{str(id_for_meta).replace('-', '')}"
        
    qdrant = QdrantMultiVectorManager(collection_name=collection_name)
    await qdrant.ensure_collection()

    # Optimization: Extreme minimalist batching for high-res vision models
    CHUNK_SIZE = 1 # Force single-page inference to prevent huge OOM/Swap spikes
    RENDER_BATCH_SIZE = 1 # One-by-one rendering to ensure immediate visibility of progress
    
    import hashlib
    
    for start_page in range(1, total_pages + 1, RENDER_BATCH_SIZE):
        end_render_page = min(start_page + RENDER_BATCH_SIZE - 1, total_pages)
        
        logger.info(f"Rendering PDF pages {start_page} to {end_render_page} (Total: {total_pages})...")
        # Batch PDF rendering - much more efficient than page-by-page
        render_batch = convert_from_path(
            file_path, 
            dpi=120, # Optimized DPI
            first_page=start_page, 
            last_page=end_render_page,
            thread_count=2 # Reduced thread count to save memory
        )
        
        if not render_batch:
            continue
            
        # Process the rendered batch in smaller inference chunks
        for chunk_offset in range(0, len(render_batch), CHUNK_SIZE):
            chunk_images = render_batch[chunk_offset: chunk_offset + CHUNK_SIZE]
            current_page_base = start_page + chunk_offset
            
            # Update progress for EVERY page to give the user confidence
            progress = int((current_page_base / total_pages) * 98)
            async with async_session_factory() as db:
                if is_source:
                    from app.models.data_source import DataSource
                    await db.execute(
                        sql_update(DataSource)
                        .where(DataSource.id == uuid.UUID(id_for_meta))
                        .values(schema_json={
                            **initial_schema,
                            "progress": progress, 
                            "current_step": f"Neural Vision Trace: Page {current_page_base} of {total_pages} processed",
                            "page_count": total_pages
                        })
                    )
                else:
                    from app.models.knowledge import Document
                    await db.execute(
                        sql_update(Document)
                        .where(Document.id == uuid.UUID(id_for_meta))
                        .values(metadata_json={
                            **initial_schema,
                            "progress": progress, 
                            "current_step": f"Neural Vision Trace: Page {current_page_base} of {total_pages} processed",
                            "page_count": total_pages
                        })
                    )
                await db.commit()
            
            logger.info("page_indexing_step", page=current_page_base, total=total_pages, doc_id=id_for_meta)
            
            with torch.inference_mode(): # More efficient than no_grad
                processed_batch = processor.process_images(chunk_images).to(model.device)
                image_embeddings = model.forward(**processed_batch)
                
                points_to_upsert = []
                for i, image_emb in enumerate(image_embeddings):
                    current_page = current_page_base + i
                    page_vectors = image_emb.cpu().tolist()
                    
                    # Metadata for retrieval
                    smart_metadata = {
                        "doc_id": id_for_meta if not is_source else None,
                        "source_id": id_for_meta if is_source else None,
                        "kb_id": str(kb_id) if kb_id else None,
                        "page_num": current_page,
                        "is_header_page": current_page == 1
                    }

                    # Generate a deterministic UUID for the page point
                    page_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"{id_for_meta}_{current_page}")
                    
                    points_to_upsert.append({
                        "id": str(page_uuid),
                        "colpali_vectors": page_vectors,
                        "muvera_vector": [0.0] * 40960, # Placeholder
                        "metadata": smart_metadata
                    })

                # Batch upsert to Qdrant (async-style wait=False)
                qdrant.upsert_batch(points_to_upsert, wait=False)
                
                # Cleanup to keep memory stable
                del processed_batch
                del image_embeddings
                gc.collect() # Force immediate garbage collection
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

    doc_dna = _build_static_metadata(context_hint)
    
    # Final update for completion
    async with async_session_factory() as db:
        if is_source:
            from app.models.data_source import DataSource
            from sqlalchemy import update as sql_update
            await db.execute(
                sql_update(DataSource)
                .where(DataSource.id == uuid.UUID(id_for_meta))
                .values(schema_json={
                    **initial_schema,
                    "progress": 100, 
                    "current_step": "Vision indexing complete. Neural map finalized.",
                    "page_count": total_pages,
                    "metadata": doc_dna
                })
            )
        else:
            from app.models.knowledge import Document
            from sqlalchemy import update as sql_update
            await db.execute(
                sql_update(Document)
                .where(Document.id == uuid.UUID(id_for_meta))
                .values(metadata_json={
                    **initial_schema,
                    "progress": 100, 
                    "current_step": "Vision indexing complete. Neural map finalized.",
                    "page_count": total_pages,
                    "dna": doc_dna
                })
            )
        await db.commit()

    return {"pages": total_pages, "metadata": doc_dna}
