# HOA Financial Processor

## Purpose
Automated processing of HOA monthly financial PDF packages into structured, analyzable data (Excel/CSV).

## Architecture

```
PDF Input → Split → Extract Text/Images → Claude Parse → Excel Output
                                              ↓
                                    Checkpoint Recovery
```

### Components

1. **PDF Splitter** (`bin/split-hoa-financials.sh`)
   - Splits large PDFs into manageable chunks (30 pages default)
   - Uses poppler-utils (pdfseparate, pdfunite, pdftotext)
   - Outputs: chunk PDFs + markdown text extracts

2. **Image Extractor** (`src/image_extractor.py`)
   - Extracts embedded images from PDF pages
   - Used for scanned invoices that need OCR

3. **Claude Client** (`src/claude_client.py`)
   - Wrapper for Claude CLI (`claude` command)
   - Handles: text parsing, image OCR, categorization
   - Includes retry logic and token management

4. **Parsers** (`src/parsers/`)
   - `balance_sheet.py` - Balance Sheet reports
   - `disbursements.py` - Check disbursements, transactions
   - `invoices.py` - Vendor invoices (text + OCR)
   - Each outputs structured data for Excel

5. **Excel Writer** (`src/excel_writer.py`)
   - Creates multi-tab .xlsx files
   - One tab per report type

6. **Checkpoint Manager** (`src/checkpoint.py`)
   - Saves progress after each major step
   - Enables recovery from token limits or errors

## Report Types (Enclave at Canyon Lake)

| Report | Pages (typical) | Structure |
|--------|-----------------|-----------|
| Balance Sheet | 3-6 | Hierarchical accounts, balances, changes |
| Investment Listing | 1 | Bank accounts, balances, rates |
| Check Disbursements | 10-20 | Transactions by vendor |
| Vendor Invoices | 20-40 | Scanned images, need OCR |

## Usage

```bash
# Full process
./bin/process-financials ~/Downloads/Financial_Package.pdf

# Resume from checkpoint
./bin/process-financials --resume

# Specific steps only
./bin/process-financials --step split
./bin/process-financials --step parse
./bin/process-financials --step excel
```

## Dependencies

- Python 3.10+
- poppler-utils (pdfseparate, pdfunite, pdftotext, pdfimages)
- Claude CLI (claude command)
- Python packages: see requirements.txt

## Token Management

- Claude CLI uses Claude Code subscription (no API key needed)
- If tokens exhausted: script saves checkpoint, exits gracefully
- Resume with `--resume` flag after token refresh (up to 5 hours)

## Data Flow

```
data/input/
  └── Financial_Package.pdf          # Original PDF
  └── Financial_Package-split/       # Split output
      ├── parts/                     # Chunk PDFs
      ├── markdown/                  # Text extracts
      └── images/                    # Extracted images

data/output/
  └── Financial_Package_2025-11.xlsx # Final Excel

data/checkpoints/
  └── Financial_Package.json         # Progress state
```
