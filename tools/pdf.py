from pypdf import PdfWriter


def merge_documents(pdf_list: list, output_filename: str = "merged.pdf") -> str:
    """Merge a list of PDF file paths into a single PDF."""
    merger = PdfWriter()
    for pdf in pdf_list:
        print(f"Appending: {pdf}")
        merger.append(pdf)
    merger.write(output_filename)
    merger.close()
    print(f"Merged into: {output_filename}")
    return output_filename
