"""Claude CLI wrapper for text parsing and image OCR."""

import json
import subprocess
import time
from pathlib import Path
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)


class TokenLimitError(Exception):
    """Raised when Claude CLI indicates token/rate limits."""
    pass


class ClaudeClient:
    """Wrapper for Claude CLI to handle parsing and OCR tasks."""

    def __init__(self, max_retries: int = 3, retry_delay: float = 5.0):
        """
        Initialize Claude client.

        Args:
            max_retries: Number of retries on transient failures
            retry_delay: Seconds to wait between retries
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._verify_claude_cli()

    def _verify_claude_cli(self):
        """Verify Claude CLI is available."""
        try:
            result = subprocess.run(
                ['claude', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError("Claude CLI not working properly")
            logger.info(f"Claude CLI available: {result.stdout.strip()}")
        except FileNotFoundError:
            raise RuntimeError(
                "Claude CLI not found. Install from: https://claude.ai/code"
            )

    def _run_claude(
        self,
        prompt: str,
        image_path: Optional[Path] = None,
        output_format: str = 'text',
        timeout: int = 120
    ) -> str:
        """
        Run Claude CLI with given prompt.

        Args:
            prompt: The prompt to send to Claude
            image_path: Optional path to image for multimodal input
            output_format: 'text' or 'json'
            timeout: Command timeout in seconds

        Returns:
            Claude's response as string

        Raises:
            TokenLimitError: If rate/token limited
            RuntimeError: On other failures
        """
        use_stdin = False
        stdin_content = None

        # Handle image input by embedding base64 in prompt
        if image_path and Path(image_path).exists():
            import base64
            import mimetypes
            image_path = Path(image_path)

            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(str(image_path))
            if not mime_type:
                mime_type = 'image/png'

            # Read and encode image
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            # Embed as data URI in prompt - use stdin for large content
            data_uri = f"data:{mime_type};base64,{image_data}"
            prompt = f"[Image: {data_uri}]\n\n{prompt}"
            logger.debug(f"Embedded image ({len(image_data)} bytes base64) in prompt")
            use_stdin = True
            stdin_content = prompt

        # Build command - use -p for print (non-interactive) mode
        if use_stdin:
            # For large prompts with images, use stdin
            cmd = ['claude', '-p', '-']
        else:
            cmd = ['claude', '-p', prompt]

        if output_format == 'json':
            cmd.extend(['--output-format', 'json'])

        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Running Claude CLI (attempt {attempt + 1})")
                result = subprocess.run(
                    cmd,
                    input=stdin_content if use_stdin else None,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )

                # Check for token/rate limit indicators
                output = result.stdout + result.stderr
                if any(phrase in output.lower() for phrase in [
                    'rate limit', 'token limit', 'quota exceeded',
                    'too many requests', 'capacity'
                ]):
                    raise TokenLimitError(
                        "Claude rate/token limit reached. "
                        "Save checkpoint and retry later."
                    )

                if result.returncode != 0:
                    logger.warning(f"Claude CLI error: {result.stderr}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                        continue
                    raise RuntimeError(f"Claude CLI failed: {result.stderr}")

                return result.stdout.strip()

            except subprocess.TimeoutExpired:
                logger.warning(f"Claude CLI timeout (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise RuntimeError("Claude CLI timed out after retries")

        raise RuntimeError("Claude CLI failed after all retries")

    def parse_text_to_json(
        self,
        text: str,
        schema_description: str,
        example: Optional[str] = None
    ) -> dict:
        """
        Parse unstructured text into structured JSON.

        Args:
            text: The text to parse
            schema_description: Description of expected JSON structure
            example: Optional example of expected output

        Returns:
            Parsed data as dictionary
        """
        prompt = f"""Parse the following financial report text into structured JSON.

{schema_description}

{f'Example output format:{chr(10)}{example}{chr(10)}' if example else ''}

Return ONLY valid JSON, no explanations or markdown.

TEXT TO PARSE:
{text}
"""
        response = self._run_claude(prompt, output_format='text')

        # Extract JSON from response (handle if wrapped in markdown)
        json_str = response
        if '```json' in response:
            json_str = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            json_str = response.split('```')[1].split('```')[0]

        try:
            return json.loads(json_str.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.debug(f"Response was: {response}")
            raise RuntimeError(f"Invalid JSON from Claude: {e}")

    def ocr_image(
        self,
        image_path: Path,
        context: Optional[str] = None
    ) -> dict:
        """
        OCR an image (including handwritten text).

        Args:
            image_path: Path to image file
            context: Optional context about what the image contains

        Returns:
            Dictionary with OCR results and structured data
        """
        context_hint = f"Context: {context}" if context else ""

        prompt = f"""Analyze this image and extract all text content.
{context_hint}

This may be a scanned invoice or financial document. Extract:
1. All visible text (including handwritten)
2. Any amounts/numbers
3. Dates
4. Vendor/company names
5. Description of services/items

Return as JSON with structure:
{{
    "raw_text": "all text as single string",
    "vendor": "vendor name if visible",
    "date": "date if visible (YYYY-MM-DD format)",
    "amount": "total amount if visible",
    "invoice_number": "invoice/reference number if visible",
    "description": "description of services/items",
    "line_items": [
        {{"description": "item", "amount": "cost"}}
    ],
    "confidence": "high/medium/low",
    "notes": "any issues or uncertainties"
}}

Return ONLY valid JSON."""

        return self.parse_text_to_json(
            "",  # No text, image will be provided
            "Invoice/document OCR result",
        )
        # Note: Need to modify _run_claude call for image

    def ocr_image_raw(self, image_path: Path, context: Optional[str] = None) -> str:
        """
        OCR an image and return raw text extraction.

        Args:
            image_path: Path to image file
            context: Optional context hint

        Returns:
            Extracted text as string
        """
        context_hint = f"This is a {context}." if context else ""

        prompt = f"""Extract ALL text from this image, preserving layout as much as possible.
{context_hint}

Include:
- All printed text
- All handwritten text (do your best)
- Numbers and amounts
- Any headers or labels

Return the extracted text, nothing else."""

        return self._run_claude(prompt, image_path=image_path)

    def categorize_transaction(
        self,
        description: str,
        amount: float,
        vendor: str
    ) -> dict:
        """
        Categorize a transaction.

        Args:
            description: Transaction description
            amount: Transaction amount
            vendor: Vendor name

        Returns:
            Dictionary with category and subcategory
        """
        prompt = f"""Categorize this HOA transaction:

Vendor: {vendor}
Amount: ${amount:.2f}
Description: {description}

Common HOA categories:
- Management (fees, admin)
- Maintenance (repairs, landscaping, pool)
- Utilities (water, electric, trash)
- Insurance
- Legal/Collections
- Capital Improvements
- Reserves

Return JSON:
{{"category": "main category", "subcategory": "specific type", "notes": "any relevant notes"}}

Return ONLY valid JSON."""

        response = self._run_claude(prompt)
        try:
            # Handle markdown wrapped JSON
            json_str = response
            if '```' in response:
                json_str = response.split('```')[1]
                if json_str.startswith('json'):
                    json_str = json_str[4:]
                json_str = json_str.split('```')[0]
            return json.loads(json_str.strip())
        except json.JSONDecodeError:
            return {
                "category": "Unknown",
                "subcategory": "Unknown",
                "notes": f"Failed to categorize: {response}"
            }

    def detect_report_type(self, text_sample: str) -> str:
        """
        Detect what type of financial report this is.

        Args:
            text_sample: First ~100 lines of text

        Returns:
            Report type: 'balance_sheet', 'disbursements', 'invoice',
                        'investment_listing', 'unknown'
        """
        prompt = f"""Identify the type of financial report from this text sample.

Possible types:
- balance_sheet: Shows assets, liabilities, equity with balances
- disbursements: Check disbursements, payments by vendor
- invoice: Vendor invoice (may be scanned)
- investment_listing: Bank accounts and investment balances
- income_statement: Income Statement Report showing revenue and expenses (current vs YTD vs budget)
- expense_trend: Income and Expense Trend Report with monthly columns (Jan-Dec) and budget comparison
- accounts_receivable: Member assessments owed
- bank_reconciliation: Bank account reconciliation with outstanding checks/deposits
- unknown: Cannot determine

TEXT SAMPLE:
{text_sample[:2000]}

Return ONLY the report type (one of the options above), nothing else."""

        response = self._run_claude(prompt).strip().lower()

        valid_types = [
            'balance_sheet', 'disbursements', 'invoice',
            'investment_listing', 'income_statement', 'expense_trend',
            'accounts_receivable', 'bank_reconciliation', 'unknown'
        ]

        # Clean up response
        for valid in valid_types:
            if valid in response:
                return valid

        return 'unknown'

    def batch_detect_page_types(
        self,
        page_samples: dict,
        batch_size: int = 20
    ) -> dict:
        """
        Classify multiple pages in batched Claude calls.

        Args:
            page_samples: Dict mapping page_id to text sample (first ~500 chars)
            batch_size: Number of pages per Claude call

        Returns:
            Dict mapping page_id to report type
        """
        all_results = {}
        page_ids = list(page_samples.keys())

        for i in range(0, len(page_ids), batch_size):
            batch_ids = page_ids[i:i + batch_size]
            batch_data = {pid: page_samples[pid] for pid in batch_ids}

            logger.info(f"  Classifying pages {batch_ids[0]} to {batch_ids[-1]}...")

            # Build the prompt with all pages in this batch
            pages_text = ""
            for pid in batch_ids:
                sample = batch_data[pid][:600]  # First 600 chars per page
                pages_text += f"\n--- {pid} ---\n{sample}\n"

            prompt = f"""Classify each page by its financial report type.

Possible types:
- balance_sheet: Assets, liabilities, equity, account balances
- disbursements: Check disbursements, payments, vendor transactions
- invoice: Vendor invoice or bill
- investment_listing: Bank accounts, investment balances, rates
- income_statement: Income Statement Report - revenue/expenses with current period vs YTD vs budget columns
- expense_trend: Income and Expense Trend Report - monthly breakdown (Jan-Dec columns) with budget comparison
- accounts_receivable: Member assessments owed, AR aging
- bank_reconciliation: Bank reconciliation with outstanding checks/deposits, GL balance
- scanned_image: Page appears to be a scanned image (minimal text)
- unknown: Cannot determine

IMPORTANT: Distinguish between income_statement (shows "Current Actual", "YTD Actual", "YTD Budget") and expense_trend (shows monthly columns like "Jan", "Feb", "Mar"... "Nov", "Full Year Actual", "Total Budget").

PAGES TO CLASSIFY:
{pages_text}

Return a JSON object mapping each page ID to its type. Example:
{{"page_001": "balance_sheet", "page_002": "balance_sheet", "page_003": "disbursements"}}

Return ONLY valid JSON, nothing else."""

            response = self._run_claude(prompt)

            # Parse the JSON response
            try:
                json_str = response
                if '```' in response:
                    json_str = response.split('```')[1]
                    if json_str.startswith('json'):
                        json_str = json_str[4:]
                    json_str = json_str.split('```')[0]

                batch_results = json.loads(json_str.strip())

                # Validate and normalize results
                valid_types = [
                    'balance_sheet', 'disbursements', 'invoice',
                    'investment_listing', 'income_statement', 'expense_trend',
                    'accounts_receivable', 'bank_reconciliation',
                    'scanned_image', 'unknown'
                ]
                for pid in batch_ids:
                    result = batch_results.get(pid, 'unknown').lower()
                    # Find matching valid type
                    matched = 'unknown'
                    for vt in valid_types:
                        if vt in result:
                            matched = vt
                            break
                    all_results[pid] = matched

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse batch response: {e}")
                # Fall back to unknown for this batch
                for pid in batch_ids:
                    all_results[pid] = 'unknown'

        return all_results

    def group_consecutive_pages(self, page_types: dict) -> list:
        """
        Group consecutive pages of the same type.

        Args:
            page_types: Dict mapping page_id (e.g., "page_001") to type

        Returns:
            List of dicts: [{"type": "balance_sheet", "pages": ["page_001", "page_002"]}, ...]
        """
        if not page_types:
            return []

        # Sort by page number
        sorted_pages = sorted(page_types.keys(), key=lambda x: int(x.split('_')[1]))

        groups = []
        current_group = None

        for page_id in sorted_pages:
            page_type = page_types[page_id]

            if current_group is None or current_group['type'] != page_type:
                # Start new group
                if current_group:
                    groups.append(current_group)
                current_group = {'type': page_type, 'pages': [page_id]}
            else:
                # Add to current group
                current_group['pages'].append(page_id)

        # Don't forget the last group
        if current_group:
            groups.append(current_group)

        return groups
