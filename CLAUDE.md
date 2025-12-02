# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python project for automated PDF translation from Thai to English. The main script (`translate_pdfs.py`) processes PDF files using OCR to extract Thai text and translates them using the Anthropic Claude API. Results are exported in multiple formats (DOCX, JSON, CSV).

## Environment Setup

This project uses a Python 3.12 virtual environment located in `venv/`.

**Activate the virtual environment:**
```bash
source venv/bin/activate
```

**Deactivate when done:**
```bash
deactivate
```

## Required Dependencies

The main script requires the following packages:

**Already installed in venv:**
- **PyMuPDF (fitz)** - PDF to image conversion
- **Pillow (PIL)** - Image processing
- **python-docx (docx)** - DOCX file generation
- **requests** - HTTP library

**Need to be installed:**
```bash
pip install pytesseract anthropic
```

**System dependencies:**
- **Tesseract OCR** with Thai language support
  - macOS: `brew install tesseract tesseract-lang`
  - Ubuntu: `sudo apt-get install tesseract-ocr tesseract-ocr-tha`
  - Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki

## Project Structure

```
.
├── PDF/                      # Input folder - place PDF files here
├── output/                   # Output folder - generated automatically
│   └── {pdf_name}/          # One subfolder per processed PDF
│       ├── page_*.png       # Extracted page images
│       ├── {pdf_name}_thai_english.docx
│       ├── pages_thai_english.json
│       └── pages_thai_english.csv
├── venv/                     # Python virtual environment
├── translate_pdfs.py         # Main translation script
└── CLAUDE.md                 # This file
```

## Running the Translation Pipeline

**1. Set up environment:**
```bash
# Activate virtual environment
source venv/bin/activate

# Install missing dependencies
pip install pytesseract anthropic

# Set API key
export ANTHROPIC_API_KEY="your_api_key_here"
```

**2. Add PDFs to the input folder:**
```bash
# Place Thai PDF files in the PDF/ directory
cp your_file.pdf PDF/
```

**3. Run the script:**
```bash
python translate_pdfs.py
```

## Script Configuration

Key constants in `translate_pdfs.py`:
- `INPUT_FOLDER` - Source folder for PDFs (default: "PDF")
- `OUTPUT_FOLDER` - Destination for results (default: "output")
- `MODEL_NAME` - Claude model to use (default: "claude-3-5-sonnet-20241022")
- `TESSERACT_LANG` - OCR language (default: "tha" for Thai)
- `DPI` - Image resolution for PDF conversion (default: 300)

## Script Architecture

The translation pipeline follows these steps:

1. **PDF to Images** (`pdf_to_images`): Converts each PDF page to a high-resolution PNG image using PyMuPDF
2. **OCR Processing** (`ocr_all_pages`): Extracts Thai text from images using Tesseract OCR
3. **Translation** (`translate_all_pages`): Translates Thai text to English via Anthropic Claude API
4. **Output Generation**: Creates DOCX, JSON, and CSV files with side-by-side Thai/English content

Each function includes error handling to continue processing even if individual pages fail.

## Development Notes

- The script processes all PDFs in `INPUT_FOLDER` sequentially
- Each PDF gets its own output subfolder with all generated files
- Page images are preserved for debugging and reference
- Translation uses one API call per page for better error recovery
- If Tesseract is not in PATH, set `pytesseract.pytesseract.tesseract_cmd` in the script
