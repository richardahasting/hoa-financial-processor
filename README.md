# HOA Financial Processor

Automated processing of HOA monthly financial PDF packages into structured, analyzable data (Excel/CSV).

## Overview

Takes large HOA financial PDF reports, splits them into chunks, extracts text and images, and uses Claude AI to parse and categorize the financial data into Excel/CSV output. Includes checkpoint recovery so processing can resume after interruption.

## Architecture

```
PDF Input → Split → Extract Text/Images → Claude Parse → Excel Output
                                              ↓
                                    Checkpoint Recovery
```

## Components

- **`bin/split-hoa-financials.sh`** — Splits large PDFs into manageable chunks (30 pages default) using poppler-utils
- **`src/image_extractor.py`** — Extracts embedded images from PDF pages for scanned invoice OCR
- **`src/claude_client.py`** — Wrapper for Claude CLI with retry logic and token management
- **`src/parsers/`** — Financial data parsers for different document types

## Requirements

```bash
pip install -r requirements.txt
```

Also requires poppler-utils:
```bash
sudo apt install poppler-utils
```

## Usage

```bash
# Split a PDF into chunks
bin/split-hoa-financials.sh input.pdf

# Process chunks through Claude
python src/claude_client.py
```

## Configuration

Copy and edit the config:
```bash
cp config/config.example.json config/config.json
```
