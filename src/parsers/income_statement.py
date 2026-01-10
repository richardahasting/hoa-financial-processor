"""Parser for Income Statement reports."""

import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class IncomeStatementParser:
    """Parse Income Statement report text into structured data."""

    def __init__(self, claude_client=None):
        """
        Initialize parser.

        Args:
            claude_client: Optional ClaudeClient for AI-assisted parsing
        """
        self.claude = claude_client

    def parse(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse income statement text into structured records.

        Args:
            text: Raw text from income statement report

        Returns:
            List of line item records
        """
        if self.claude:
            return self._parse_with_claude(text)
        return self._parse_with_regex(text)

    def _parse_with_regex(self, text: str) -> List[Dict[str, Any]]:
        """Parse using regex patterns."""
        records = []
        current_section = None  # Income or Expense
        current_category = None  # e.g., Assessment Income, Administrative

        # Pattern for account lines with 8 numeric columns
        # Account Code - Name    Actual Budget Variance   Actual Budget Variance   AnnualBudget Remaining
        account_pattern = re.compile(
            r'^\s*(\d{4})\s*-\s*(.+?)\s+'
            r'(-?[\d,().]+)\s+(-?[\d,().]+)\s+(-?[\d,().]+)\s+'  # Current Period
            r'(-?[\d,().]+)\s+(-?[\d,().]+)\s+(-?[\d,().]+)\s+'  # YTD
            r'(-?[\d,().]+)\s+(-?[\d,().]+)\s*$'                  # Annual Budget, Remaining
        )

        # Pattern for Total lines
        total_pattern = re.compile(
            r'^\s*Total\s+(.+?)\s+'
            r'(-?[\d,().]+)\s+(-?[\d,().]+)\s+(-?[\d,().]+)\s+'
            r'(-?[\d,().]+)\s+(-?[\d,().]+)\s+(-?[\d,().]+)\s+'
            r'(-?[\d,().]+)\s+(-?[\d,().]+)\s*$'
        )

        for line in text.split('\n'):
            # Skip empty lines and page markers
            if not line.strip() or 'Printed by' in line or 'Page ' in line:
                continue

            # Track main sections
            if line.strip() == 'Income':
                current_section = 'Income'
                continue
            elif line.strip() == 'Expense':
                current_section = 'Expense'
                continue

            # Track categories (lines that don't start with numbers and aren't totals)
            stripped = line.strip()
            if (stripped and
                not stripped[0].isdigit() and
                not stripped.startswith('Total') and
                not stripped.startswith('Current') and
                not stripped.startswith('Actual') and
                not any(c.isdigit() for c in stripped[:10]) and
                len(stripped) < 50):
                # This might be a category header
                potential_cat = stripped
                if potential_cat not in ['Income', 'Expense', 'Operating', 'Reserves']:
                    current_category = potential_cat
                continue

            # Try to match account line
            acct_match = account_pattern.match(line)
            if acct_match:
                try:
                    records.append({
                        'account_code': acct_match.group(1),
                        'account_name': acct_match.group(2).strip(),
                        'section': current_section or 'Unknown',
                        'category': current_category or 'Unknown',
                        'is_total': False,
                        'current_actual': self._parse_amount(acct_match.group(3)),
                        'current_budget': self._parse_amount(acct_match.group(4)),
                        'current_variance': self._parse_amount(acct_match.group(5)),
                        'ytd_actual': self._parse_amount(acct_match.group(6)),
                        'ytd_budget': self._parse_amount(acct_match.group(7)),
                        'ytd_variance': self._parse_amount(acct_match.group(8)),
                        'annual_budget': self._parse_amount(acct_match.group(9)),
                        'budget_remaining': self._parse_amount(acct_match.group(10))
                    })
                except (ValueError, TypeError) as e:
                    logger.debug(f"Could not parse account line: {line} - {e}")
                continue

            # Try to match total line
            total_match = total_pattern.match(line)
            if total_match:
                try:
                    total_name = total_match.group(1).strip()
                    records.append({
                        'account_code': '',
                        'account_name': f"Total {total_name}",
                        'section': current_section or 'Unknown',
                        'category': total_name,
                        'is_total': True,
                        'current_actual': self._parse_amount(total_match.group(2)),
                        'current_budget': self._parse_amount(total_match.group(3)),
                        'current_variance': self._parse_amount(total_match.group(4)),
                        'ytd_actual': self._parse_amount(total_match.group(5)),
                        'ytd_budget': self._parse_amount(total_match.group(6)),
                        'ytd_variance': self._parse_amount(total_match.group(7)),
                        'annual_budget': self._parse_amount(total_match.group(8)),
                        'budget_remaining': self._parse_amount(total_match.group(9))
                    })
                except (ValueError, TypeError) as e:
                    logger.debug(f"Could not parse total line: {line} - {e}")

        logger.info(f"Parsed {len(records)} income statement records with regex")
        return records

    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount string to float."""
        if not amount_str:
            return 0.0
        # Handle parentheses for negative numbers
        negative = '(' in amount_str
        cleaned = re.sub(r'[(),\s$]', '', amount_str)
        value = float(cleaned) if cleaned else 0.0
        return -value if negative else value

    def _parse_with_claude(self, text: str) -> List[Dict[str, Any]]:
        """Parse using Claude for complex reports."""
        schema = """
        Return a JSON array of income statement line items. Each record should have:
        {
            "account_code": "4-digit account code (empty for totals)",
            "account_name": "account name or Total X",
            "section": "Income or Expense",
            "category": "subcategory like Assessment Income, Administrative, etc.",
            "is_total": boolean (true for Total lines),
            "current_actual": numeric (current month actual),
            "current_budget": numeric (current month budget),
            "current_variance": numeric (actual - budget, negative in parens),
            "ytd_actual": numeric (year to date actual),
            "ytd_budget": numeric (year to date budget),
            "ytd_variance": numeric,
            "annual_budget": numeric (full year budget),
            "budget_remaining": numeric (annual - ytd actual)
        }

        Parse ALL line items including individual accounts AND totals.
        Numbers in parentheses are negative.
        """

        example = """
        [
            {
                "account_code": "4000",
                "account_name": "Residential Assessments",
                "section": "Income",
                "category": "Assessment Income",
                "is_total": false,
                "current_actual": 0.00,
                "current_budget": 0.00,
                "current_variance": 0.00,
                "ytd_actual": 123516.80,
                "ytd_budget": 124920.00,
                "ytd_variance": -1403.20,
                "annual_budget": 124920.00,
                "budget_remaining": 1403.20
            },
            {
                "account_code": "",
                "account_name": "Total Assessment Income",
                "section": "Income",
                "category": "Assessment Income",
                "is_total": true,
                "current_actual": 0.00,
                "current_budget": 0.00,
                "current_variance": 0.00,
                "ytd_actual": 123516.80,
                "ytd_budget": 124920.00,
                "ytd_variance": -1403.20,
                "annual_budget": 124920.00,
                "budget_remaining": 1403.20
            }
        ]
        """

        try:
            result = self.claude.parse_text_to_json(text, schema, example)
            if isinstance(result, list):
                logger.info(f"Parsed {len(result)} income statement records with Claude")
                return result
            return []
        except Exception as e:
            logger.error(f"Claude parsing failed: {e}")
            return self._parse_with_regex(text)

    def get_summary(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract key totals from parsed records.

        Returns:
            Dictionary with total income, expenses, net income
        """
        summary = {
            'total_income_ytd': 0.0,
            'total_expense_ytd': 0.0,
            'net_income_ytd': 0.0,
            'total_income_budget': 0.0,
            'total_expense_budget': 0.0
        }

        for record in records:
            if record.get('is_total'):
                name = record.get('account_name', '').lower()
                if 'operating income' in name or 'total income' in name:
                    summary['total_income_ytd'] = record.get('ytd_actual', 0)
                    summary['total_income_budget'] = record.get('annual_budget', 0)
                elif 'operating expense' in name or 'total expense' in name:
                    summary['total_expense_ytd'] = record.get('ytd_actual', 0)
                    summary['total_expense_budget'] = record.get('annual_budget', 0)

        summary['net_income_ytd'] = summary['total_income_ytd'] - summary['total_expense_ytd']
        return summary
