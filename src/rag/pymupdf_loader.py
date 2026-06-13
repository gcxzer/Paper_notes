"""PyMuPDF-based PDF loader."""
from pathlib import Path

import pymupdf

from rag.config import image_output_path


def extract_text_from_pdf(pdf_path: str | Path) -> list[dict]:
    pdf_path = Path(pdf_path)
    pages = []

    with pymupdf.open(pdf_path) as doc:
        for page_index, page in enumerate(doc):
            text = page.get_text("text")

            pages.append(
                {
                    "text": text,
                    "metadata": {
                        "source_pdf": str(pdf_path),
                        "file_name": pdf_path.name,
                        "paper_id": pdf_path.stem,
                        "page_number": page_index + 1,
                    },
                }
            )

    return pages


def extract_images_from_pdf(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
) -> list[dict]:
    """Extract PDF images and return structured image records."""
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir) if output_dir is not None else image_output_path(pdf_path.stem, loader="pymupdf")

    if not pdf_path.exists():
        print(f"PDF file does not exist: {pdf_path}")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    print("\nExtracting images from PDF...")

    image_records = []

    with pymupdf.open(pdf_path) as doc:
        for page_index in range(len(doc)):
            page_image_records = _extract_images_from_pdf_page(
                doc=doc,
                page_index=page_index,
                output_dir=output_dir,
                paper_id=pdf_path.stem,
            )
            image_records.extend(page_image_records)

    print(f"Extracted {len(image_records)} images")
    print(f"Image output directory: {output_dir}")

    return image_records


def _extract_images_from_pdf_page(
    doc,
    page_index: int,
    output_dir: str | Path,
    paper_id: str,
) -> list[dict]:
    """Extract all images from a PDF page and save them to disk.

    Args:
        doc: PyMuPDF Document object.
        page_index: Zero-based page index.
        output_dir: Directory where images are saved.
        paper_id: Stable paper identifier, usually the PDF file stem.

    Returns:
        Image records for node creation.
    """
    output_dir = Path(output_dir)

    # Get the selected page.
    page = doc[page_index]

    # Get all images on the page.
    image_list = page.get_images(full=True)
    image_records = []

    for image_index, img in enumerate(image_list):
        # xref is the image reference ID.
        xref = img[0]

        # Extract image bytes and file extension.
        base_image = doc.extract_image(xref)
        image_bytes = base_image["image"]
        image_ext = base_image["ext"]

        # Generate a unique image filename.
        image_filename = f"page_{page_index + 1}_img_{image_index + 1}.{image_ext}"
        image_path = output_dir / image_filename

        # Save image bytes to disk.
        with image_path.open("wb") as img_file:
            img_file.write(image_bytes)

        page_number = page_index + 1
        image_number = image_index + 1

        image_records.append(
            {
                "image_path": image_path,
                "paper_id": paper_id,
                "page_number": page_number,
                "image_index": image_number,
                "source_anchor": f"{paper_id}:page:{page_number}:image:{image_number}",
            }
        )

    return image_records
