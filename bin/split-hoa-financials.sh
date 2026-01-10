#!/bin/bash
#
# split-hoa-financials.sh - Split HOA financial PDFs and convert to markdown
#
# Usage: split-hoa-financials.sh <input.pdf> [max_pages] [output_dir]
#
# This script:
#   1. Splits the PDF into chunks of max_pages (default: 30)
#   2. Converts each chunk to markdown
#   3. Cleans up intermediate files
#
# Requirements: poppler-utils (pdfseparate, pdfunite, pdftotext)

set -e

# Defaults
DEFAULT_MAX_PAGES=30

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Check dependencies
check_deps() {
    for cmd in pdfseparate pdfunite pdftotext pdfinfo; do
        if ! command -v $cmd &> /dev/null; then
            error "$cmd not found. Install with: sudo apt install poppler-utils"
        fi
    done
}

# Main
main() {
    check_deps

    if [ -z "$1" ]; then
        echo "Usage: $0 <input.pdf> [max_pages] [output_dir]"
        echo ""
        echo "Arguments:"
        echo "  input.pdf    - The PDF file to split"
        echo "  max_pages    - Maximum pages per chunk (default: $DEFAULT_MAX_PAGES)"
        echo "  output_dir   - Output directory (default: <input>-split/)"
        echo ""
        echo "Example:"
        echo "  $0 'Financial-Report.pdf' 30"
        echo "  $0 'Financial-Report.pdf' 25 ~/Documents/output"
        exit 1
    fi

    INPUT_PDF="$1"
    MAX_PAGES="${2:-$DEFAULT_MAX_PAGES}"

    if [ ! -f "$INPUT_PDF" ]; then
        error "File not found: $INPUT_PDF"
    fi

    # Validate max_pages is a number
    if ! [[ "$MAX_PAGES" =~ ^[0-9]+$ ]]; then
        error "max_pages must be a number: $MAX_PAGES"
    fi

    # Extract base name and create output directory
    BASENAME=$(basename "$INPUT_PDF" .pdf)
    OUTPUT_DIR="${3:-$(dirname "$INPUT_PDF")/${BASENAME}-split}"

    info "Processing: $INPUT_PDF"
    info "Max pages per chunk: $MAX_PAGES"
    info "Output directory: $OUTPUT_DIR"

    # Get page count
    TOTAL_PAGES=$(pdfinfo "$INPUT_PDF" | grep "Pages:" | awk '{print $2}')
    info "Total pages: $TOTAL_PAGES"

    # Calculate number of chunks
    NUM_CHUNKS=$(( (TOTAL_PAGES + MAX_PAGES - 1) / MAX_PAGES ))
    info "Will create $NUM_CHUNKS chunks"

    # Create directories
    mkdir -p "$OUTPUT_DIR/pages"
    mkdir -p "$OUTPUT_DIR/parts"
    mkdir -p "$OUTPUT_DIR/markdown"

    # Step 1: Split into individual pages
    info "Splitting PDF into individual pages..."
    pdfseparate "$INPUT_PDF" "$OUTPUT_DIR/pages/page-%03d.pdf"

    # Step 2: Create chunks
    CHUNK=1
    PAGE=1

    while [ $PAGE -le $TOTAL_PAGES ]; do
        START_PAGE=$PAGE
        END_PAGE=$((PAGE + MAX_PAGES - 1))

        if [ $END_PAGE -gt $TOTAL_PAGES ]; then
            END_PAGE=$TOTAL_PAGES
        fi

        info "Creating chunk $CHUNK: pages $START_PAGE-$END_PAGE..."

        # Collect page files for this chunk (using array for paths with spaces)
        CHUNK_FILES=()
        for i in $(seq -f "%03g" $START_PAGE $END_PAGE); do
            CHUNK_FILES+=("$OUTPUT_DIR/pages/page-$i.pdf")
        done

        # Combine into chunk PDF
        CHUNK_PDF="$OUTPUT_DIR/parts/chunk-$(printf '%02d' $CHUNK)-pages-${START_PAGE}-to-${END_PAGE}.pdf"
        pdfunite "${CHUNK_FILES[@]}" "$CHUNK_PDF"

        # Convert to text
        CHUNK_TXT="$OUTPUT_DIR/markdown/chunk-$(printf '%02d' $CHUNK).txt"
        pdftotext -layout "$CHUNK_PDF" "$CHUNK_TXT"

        # Create markdown with header
        CHUNK_MD="$OUTPUT_DIR/markdown/chunk-$(printf '%02d' $CHUNK)-pages-${START_PAGE}-to-${END_PAGE}.md"
        cat > "$CHUNK_MD" << EOF
# HOA Financial Report - Chunk $CHUNK (Pages $START_PAGE-$END_PAGE)

**Source:** $(basename "$INPUT_PDF")
**Generated:** $(date '+%Y-%m-%d %H:%M:%S')
**Pages:** $START_PAGE to $END_PAGE of $TOTAL_PAGES

---

\`\`\`
$(cat "$CHUNK_TXT")
\`\`\`
EOF

        # Remove the intermediate text file
        rm "$CHUNK_TXT"

        CHUNK=$((CHUNK + 1))
        PAGE=$((END_PAGE + 1))
    done

    # Step 3: Keep individual pages for debugging
    # (Previously deleted - now kept for diagnostics)
    info "Keeping individual page files in: $OUTPUT_DIR/pages/"

    # Step 4: Also extract raw text per page for easier debugging
    info "Extracting raw text per page..."
    mkdir -p "$OUTPUT_DIR/text"
    for i in $(seq -f "%03g" 1 $TOTAL_PAGES); do
        pdftotext -layout "$OUTPUT_DIR/pages/page-$i.pdf" "$OUTPUT_DIR/text/page-$i.txt" 2>/dev/null
    done

    # Summary
    echo ""
    info "=== COMPLETE ==="
    echo ""
    echo "Created $((CHUNK - 1)) chunks from $TOTAL_PAGES pages"
    echo ""
    echo "Output structure:"
    echo "  $OUTPUT_DIR/"
    echo "  ├── pages/        - Individual page PDFs ($TOTAL_PAGES files)"
    echo "  ├── parts/        - Combined chunk PDFs ($((CHUNK - 1)) files)"
    echo "  ├── markdown/     - Chunk text as markdown ($((CHUNK - 1)) files)"
    echo "  └── text/         - Per-page raw text ($TOTAL_PAGES files)"
    echo ""
    echo "PDF chunks:"
    ls -lh "$OUTPUT_DIR/parts/"*.pdf | awk '{print "  " $9 " (" $5 ")"}'
    echo ""
    echo "Markdown line counts:"
    wc -l "$OUTPUT_DIR/markdown/"*.md
    echo ""
    info "Ready for review! Start with:"
    echo "  cat \"$OUTPUT_DIR/markdown/chunk-01\"*.md | head -200"
    echo "  cat \"$OUTPUT_DIR/text/page-001.txt\"  # Individual page text"
}

main "$@"
