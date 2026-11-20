"""Phase 5 M2.5: consented, bounded in-memory PDF/DOCX visual processing.

No session mutation, Supabase access, logging or automatic provider invocation.
Caller supplies authoritative revalidation before AND after each outbound request.
"""
from __future__ import annotations

from io import BytesIO
from typing import Callable, Any

from services.knowledge_service import KnowledgeError, validate_file
from services.visual_extraction_manifest_service import (
    VisualManifest, inspect_visual_manifest, MAX_UPLOAD_BYTES,
)
from services.visual_provider_service import (
    VisionBudget, VisualProviderError, VisualEvidence, analyze_visual_image,
    MAX_IMAGE_BYTES,
)
from services.visual_evidence_merge_service import (
    NativeEvidenceBlock, VisualMergeError, merge_visual_evidence,
)
from services.temporary_document_service import TemporaryDocument


class VisualProcessingError(RuntimeError):
    """Public error containing no user document or provider response text."""


def _extract_native(filename: str, data: bytes, extension: str) -> tuple[NativeEvidenceBlock, ...]:
    blocks: list[NativeEvidenceBlock] = []
    try:
        if extension == '.pdf':
            import pymupdf
            with pymupdf.open(stream=data, filetype='pdf') as pdf:
                if pdf.needs_pass:
                    raise VisualProcessingError('Password-protected PDFs are not supported.')
                for number, page in enumerate(pdf, 1):
                    text = page.get_text('text').strip()
                    if text:
                        blocks.append(NativeEvidenceBlock(text, pdf_page=number))
        elif extension == '.docx':
            from docx import Document
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            doc = Document(BytesIO(data))
            for block_no, element in enumerate(doc.element.body.iterchildren(), 1):
                if element.tag == qn('w:p'):
                    value = Paragraph(element, doc).text
                elif element.tag == qn('w:tbl'):
                    table = Table(element, doc)
                    value = '\n'.join(' | '.join(c.text.strip() for c in row.cells) for row in table.rows)
                else:
                    continue
                if value.strip():
                    blocks.append(NativeEvidenceBlock(value.strip(), docx_body_block=block_no))
        else:
            text = data.decode('utf-8-sig')
            if text.strip():
                blocks.append(NativeEvidenceBlock(text.strip()))
    except VisualProcessingError:
        raise
    except Exception as exc:
        raise VisualProcessingError('Unable to extract native document text.') from exc
    return tuple(blocks)


def _render_pdf(data: bytes, page_number: int) -> bytes:
    """Bounded full-page rendering; never return a cached pixmap or PDF bytes."""
    try:
        import pymupdf
        with pymupdf.open(stream=data, filetype='pdf') as pdf:
            if type(page_number) is not int or not 1 <= page_number <= len(pdf):
                raise VisualProcessingError('Invalid PDF visual page location.')
            page = pdf[page_number - 1]
            bounds = page.rect
            if bounds.width <= 0 or bounds.height <= 0:
                raise VisualProcessingError('Invalid PDF page dimensions.')
            scale = min(150 / 72, 2048 / max(bounds.width, bounds.height))
            if scale <= 0:
                raise VisualProcessingError('Invalid PDF rendering resolution.')
            px_w = int(bounds.width * scale) + 1
            px_h = int(bounds.height * scale) + 1
            if px_w * px_h > 16_000_000:
                raise VisualProcessingError('PDF page exceeds visual rendering pixel limit.')
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            if pixmap.width > 2048 or pixmap.height > 2048:
                raise VisualProcessingError('PDF rendering exceeded image dimensions.')
            encoded = pixmap.tobytes('png')
            if len(encoded) > MAX_IMAGE_BYTES:
                raise VisualProcessingError('Rendered PDF page exceeds image size limit.')
            return encoded
    except VisualProcessingError:
        raise
    except Exception as exc:
        raise VisualProcessingError('Unable to render PDF visual page safely.') from exc


def _docx_images(data: bytes, manifest: VisualManifest) -> dict[str, bytes]:
    """Resolve image *occurrences* using Word relationships and body-block order."""
    try:
        from docx import Document
        from docx.oxml.ns import qn
        doc = Document(BytesIO(data))
        expected = tuple(manifest.candidates)
        found: dict[str, bytes] = {}
        ordinal = 0
        for block_no, block in enumerate(doc.element.body.iterchildren(), 1):
            if block.tag not in (qn('w:p'), qn('w:tbl')):
                continue
            for blip in block.iter(qn('a:blip')):
                rel = blip.get(qn('r:embed'))
                if not rel:
                    continue
                part = doc.part.related_parts.get(rel)
                if part is None or not str(part.content_type).startswith('image/'):
                    continue
                ordinal += 1
                if ordinal > len(expected):
                    raise VisualProcessingError('Word image manifest differs from the selected document.')
                candidate = expected[ordinal - 1]
                if (candidate.kind != 'docx_image' or candidate.docx_image_ordinal != ordinal
                        or candidate.docx_body_block != block_no
                        or candidate.media_path != str(part.partname).lstrip('/')):
                    raise VisualProcessingError('Word image source location mismatch.')
                raw = part.blob
                if len(raw) > MAX_IMAGE_BYTES:
                    raise VisualProcessingError('Embedded Word image exceeds provider size limit.')
                found[candidate.source_id] = raw
        if len(found) != len(expected):
            raise VisualProcessingError('Word image manifest is incomplete.')
        return found
    except VisualProcessingError:
        raise
    except Exception as exc:
        raise VisualProcessingError('Unable to resolve embedded Word images safely.') from exc


def process_visual_document(*, owner_user_id: str, filename: str, data: bytes,
                            manifest: VisualManifest, consent: bool, budget: VisionBudget,
                            revalidate: Callable[[], None], client: Any = None,
                            vision_fn: Callable[..., VisualEvidence] = analyze_visual_image
                            ) -> TemporaryDocument:
    """Process an already-approved manifest; fail closed if any candidate fails.

    `revalidate` is mandatory and must verify live user, consent-file attempt and
    generation. It is called before processing, before each provider request,
    after each response and before returning. No partial result is returned.
    """
    if consent is not True:
        raise VisualProcessingError('Explicit image-processing consent is required.')
    if not callable(revalidate):
        raise VisualProcessingError('Live session verification is required.')
    if not isinstance(budget, VisionBudget) or not isinstance(manifest, VisualManifest):
        raise VisualProcessingError('Valid visual manifest and spending budget are required.')
    if not isinstance(data, bytes) or not data or len(data) > MAX_UPLOAD_BYTES:
        raise VisualProcessingError('Document exceeds the upload limit.')
    try:
        valid = validate_file(filename, data)
        verified = inspect_visual_manifest(valid.display_name, data)
        if verified != manifest or not verified.candidates:
            raise VisualProcessingError('Visual manifest does not match the selected document.')
        if len(manifest.candidates) > budget.max_calls:
            raise VisualProcessingError('Vision call limit is insufficient for this document.')
        if (budget.estimated_spent_usd + len(manifest.candidates) * budget.next_reservation_usd
                > budget.max_estimated_usd):
            raise VisualProcessingError('Configured estimated vision budget is insufficient for this document.')
        revalidate()
        native = _extract_native(valid.display_name, data, valid.extension)
        images = _docx_images(data, manifest) if valid.extension == '.docx' else {}
        visual: list[VisualEvidence] = []
        for candidate in manifest.candidates:
            revalidate()
            image = (_render_pdf(data, candidate.pdf_page) if valid.extension == '.pdf'
                     else images[candidate.source_id])
            revalidate()
            result = vision_fn(source_id=candidate.source_id, image_bytes=image,
                               consent=True, budget=budget, client=client)
            # Reject fake or malformed provider output before further calls.
            if not isinstance(result, VisualEvidence) or result.source_id != candidate.source_id:
                raise VisualProcessingError('Visual evidence source validation failed.')
            visual.append(result)
            revalidate()
            if budget.stopped or budget.estimated_spent_usd > budget.max_estimated_usd:
                raise VisualProcessingError('Estimated vision spending budget was exceeded; result discarded.')
        document = merge_visual_evidence(owner_user_id=owner_user_id, manifest=manifest,
                                         native_blocks=native, visual_evidence=tuple(visual))
        revalidate()
        return document
    except VisualProcessingError:
        raise
    except (KnowledgeError, VisualProviderError, VisualMergeError) as exc:
        raise VisualProcessingError('Unable to complete visual document processing safely.') from exc
    except Exception as exc:
        # Session revalidation may raise DocumentAccessError: caller must handle
        # its own session state clearing. Do not convert that exception here.
        from services.document_analysis_service import DocumentAccessError
        if isinstance(exc, DocumentAccessError):
            raise
        raise VisualProcessingError('Unable to complete visual document processing safely.') from exc
