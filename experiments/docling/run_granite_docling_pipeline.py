#!/usr/bin/env python3
"""Stage 1 (Granite-Docling VLM pipeline): converts the same real PDF
through Docling's VLM pipeline using ibm-granite/granite-docling-258M
(explicit HF transformers backend, CPU), exporting the same Markdown +
DoclingDocument JSON + images as the default-pipeline script, for a
direct comparison.
"""
import sys
import time
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import VlmPipelineOptions
from docling.datamodel.vlm_model_specs import GRANITEDOCLING_TRANSFORMERS
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.vlm_pipeline import VlmPipeline
from docling_core.types.doc import ImageRefMode

def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <input.pdf> <output_dir>", file=sys.stderr)
        return 1
    input_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline_options = VlmPipelineOptions(vlm_options=GRANITEDOCLING_TRANSFORMERS)
    pipeline_options.generate_picture_images = True
    pipeline_options.images_scale = 2.0

    t0 = time.perf_counter()
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=VlmPipeline, pipeline_options=pipeline_options
            )
        }
    )
    result = converter.convert(str(input_path))
    t1 = time.perf_counter()
    print(f"conversion wall-clock: {t1 - t0:.2f}s")

    doc = result.document
    doc.save_as_json(output_dir / "document.json")
    doc.save_as_markdown(output_dir / "document.md", image_mode=ImageRefMode.REFERENCED)

    print(f"pages: {len(doc.pages)}")
    print(f"tables: {len(doc.tables)}")
    print(f"pictures: {len(doc.pictures)}")
    print(f"wrote: {output_dir}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
