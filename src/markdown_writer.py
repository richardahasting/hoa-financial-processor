"""Generate LLM-optimized markdown summary of HOA financials."""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MarkdownWriter:
    """Generate markdown summary optimized for LLM context consumption."""

    def __init__(self, output_path: Path):
        """
        Initialize markdown writer.

        Args:
            output_path: Path for output .md file
        """
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.lines = []

    def _fmt_currency(self, value: float) -> str:
        """Format value as currency with commas."""
        if value is None:
            return "$0.00"
        if value < 0:
            return f"-${abs(value):,.2f}"
        return f"${value:,.2f}"

    def _fmt_pct(self, value: float) -> str:
        """Format value as percentage."""
        if value is None:
            return "0.0%"
        return f"{value:,.1f}%"

    def _add_line(self, line: str = ""):
        """Add a line to the output."""
        self.lines.append(line)

    def _add_table(self, headers: List[str], rows: List[List[str]], align: Optional[List[str]] = None):
        """Add a pipe table."""
        if not rows:
            self._add_line("*No data*")
            return

        # Default right-align for numeric columns
        if align is None:
            align = ['l'] + ['r'] * (len(headers) - 1)

        # Header row
        self._add_line("| " + " | ".join(headers) + " |")

        # Separator with alignment
        sep_parts = []
        for a in align:
            if a == 'r':
                sep_parts.append("---:")
            elif a == 'c':
                sep_parts.append(":---:")
            else:
                sep_parts.append("---")
        self._add_line("| " + " | ".join(sep_parts) + " |")

        # Data rows
        for row in rows:
            self._add_line("| " + " | ".join(str(c) for c in row) + " |")

    def generate(
        self,
        summary: Dict[str, Any],
        balance_sheet_data: List[Dict],
        disbursement_data: List[Dict],
        expense_trend_data: List[Dict],
        income_statement_data: List[Dict],
        accounts_receivable_data: List[Dict],
        bank_reconciliation_data: List[Dict],
        report_date: str = None
    ):
        """
        Generate the full markdown summary.

        Args:
            summary: Summary metrics dict
            balance_sheet_data: Balance sheet records
            disbursement_data: Disbursement/check records
            expense_trend_data: Monthly expense trend records
            income_statement_data: Income statement records
            accounts_receivable_data: AR records
            bank_reconciliation_data: Bank reconciliation records
            report_date: Report period string
        """
        self.lines = []

        # Title
        self._add_line("# HOA Financial Summary")
        self._add_line()

        # 1. Executive Summary
        self._generate_executive_summary(summary, report_date)

        # 2. Alerts & Variances
        self._generate_alerts(expense_trend_data, income_statement_data)

        # 3. Accounts Receivable - Delinquent
        self._generate_ar_delinquent(accounts_receivable_data)

        # 4. Bank Reconciliation
        self._generate_bank_reconciliation(bank_reconciliation_data)

        # 5. Cash Position
        self._generate_cash_position(balance_sheet_data)

        # 6. Month-over-Month Changes
        self._generate_mom_changes(expense_trend_data)

        # 7. Notable Transactions
        self._generate_notable_transactions(disbursement_data)

        # Write to file
        self._write()

    def _generate_executive_summary(self, summary: Dict[str, Any], report_date: str = None):
        """Section 1: Executive Summary."""
        self._add_line("## 1. Executive Summary")
        self._add_line()

        # Report period
        if report_date:
            self._add_line(f"**Report Period:** {report_date}")
        self._add_line(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self._add_line()

        # Key metrics table
        metrics = [
            ["Total Assets", self._fmt_currency(summary.get('total_assets', 0))],
            ["Total Liabilities", self._fmt_currency(summary.get('total_liabilities', 0))],
            ["Net Equity", self._fmt_currency(summary.get('net_equity', 0))],
            ["Operating Funds", self._fmt_currency(summary.get('operating_funds', 0))],
            ["Reserve Funds", self._fmt_currency(summary.get('reserve_funds', 0))],
            ["Total AR", self._fmt_currency(summary.get('accounts_receivable', 0))],
            ["Monthly Expenses", self._fmt_currency(summary.get('monthly_expenses', 0))],
            ["Checks Written", str(summary.get('checks_written', 0))],
        ]

        self._add_table(["Metric", "Value"], metrics, ['l', 'r'])
        self._add_line()

    def _generate_alerts(self, expense_trend_data: List[Dict], income_statement_data: List[Dict]):
        """Section 2: Alerts & Variances - flag significant budget variances."""
        self._add_line("## 2. Alerts & Variances")
        self._add_line()

        alerts = []

        # Check expense trend data for variances
        for record in expense_trend_data:
            if record.get('is_total'):
                continue  # Skip totals, look at line items

            actual = record.get('full_year_actual', 0) or 0
            budget = record.get('total_budget', 0) or 0

            if budget == 0:
                continue

            variance = budget - actual
            variance_pct = (variance / budget * 100) if budget else 0

            # Flag if variance > 20% AND > $500, OR absolute variance > $2000
            if (abs(variance_pct) > 20 and abs(variance) > 500) or abs(variance) > 2000:
                alerts.append({
                    'account': f"{record.get('account_code', '')} - {record.get('account_name', '')}",
                    'actual': actual,
                    'budget': budget,
                    'variance': variance,
                    'variance_pct': variance_pct
                })

        # Also check income statement data
        for record in income_statement_data:
            if record.get('is_total'):
                continue

            actual = record.get('ytd_actual', 0) or 0
            budget = record.get('ytd_budget', 0) or 0

            if budget == 0:
                continue

            variance = record.get('ytd_variance', budget - actual) or 0
            variance_pct = (variance / budget * 100) if budget else 0

            # Flag if variance > 20% AND > $500, OR absolute variance > $2000
            if (abs(variance_pct) > 20 and abs(variance) > 500) or abs(variance) > 2000:
                # Avoid duplicates from expense trend
                account_key = f"{record.get('account_code', '')} - {record.get('account_name', '')}"
                if not any(a['account'] == account_key for a in alerts):
                    alerts.append({
                        'account': account_key,
                        'actual': actual,
                        'budget': budget,
                        'variance': variance,
                        'variance_pct': variance_pct
                    })

        # Sort by absolute variance descending
        alerts.sort(key=lambda x: abs(x['variance']), reverse=True)

        if not alerts:
            self._add_line("*No significant variances detected*")
        else:
            rows = []
            for a in alerts[:15]:  # Limit to top 15
                rows.append([
                    a['account'][:40],  # Truncate long names
                    self._fmt_currency(a['actual']),
                    self._fmt_currency(a['budget']),
                    self._fmt_currency(a['variance']),
                    self._fmt_pct(a['variance_pct'])
                ])

            self._add_table(
                ["Account", "YTD Actual", "Budget", "Variance $", "Variance %"],
                rows,
                ['l', 'r', 'r', 'r', 'r']
            )

        self._add_line()

    def _generate_ar_delinquent(self, accounts_receivable_data: List[Dict]):
        """Section 3: Accounts Receivable - Delinquent only."""
        self._add_line("## 3. Accounts Receivable - Delinquent")
        self._add_line()

        # Filter for delinquent accounts (those with 120+ day balances or high totals)
        delinquent = []
        for record in accounts_receivable_data:
            total = record.get('total_balance', 0) or 0
            over_120 = record.get('day_120_plus', 0) or 0

            # Include if has 120+ balance or total > $200
            if over_120 > 0 or total > 200:
                delinquent.append({
                    'name': record.get('name', 'Unknown'),
                    'address': record.get('address', ''),
                    'total': total,
                    'over_120': over_120
                })

        # Sort by total balance descending
        delinquent.sort(key=lambda x: x['total'], reverse=True)

        if not delinquent:
            self._add_line("*No delinquent accounts*")
        else:
            rows = []
            for d in delinquent:
                rows.append([
                    d['name'][:25],
                    d['address'][:30] if d['address'] else '',
                    self._fmt_currency(d['total']),
                    self._fmt_currency(d['over_120'])
                ])

            self._add_table(
                ["Name", "Address", "Total Balance", "120+ Days"],
                rows,
                ['l', 'l', 'r', 'r']
            )

            # Total
            total_delinquent = sum(d['total'] for d in delinquent)
            self._add_line()
            self._add_line(f"**Total Delinquent: {self._fmt_currency(total_delinquent)}**")

        self._add_line()

    def _generate_bank_reconciliation(self, bank_reconciliation_data: List[Dict]):
        """Section 4: Bank Reconciliation status."""
        self._add_line("## 4. Bank Reconciliation")
        self._add_line()

        if not bank_reconciliation_data:
            self._add_line("*No bank reconciliation data*")
        else:
            rows = []
            for record in bank_reconciliation_data:
                reconciled = "Yes" if record.get('is_reconciled', False) else "No"
                difference = record.get('difference', 0) or 0
                diff_str = self._fmt_currency(difference) if difference != 0 else "-"

                rows.append([
                    record.get('account_name', '')[:30],
                    record.get('account_type', ''),
                    self._fmt_currency(record.get('ending_balance_gl', 0)),
                    reconciled,
                    diff_str
                ])

            self._add_table(
                ["Account", "Type", "GL Balance", "Reconciled", "Difference"],
                rows,
                ['l', 'l', 'r', 'c', 'r']
            )

        self._add_line()

    def _generate_cash_position(self, balance_sheet_data: List[Dict]):
        """Section 5: Cash Position - operating vs reserve totals."""
        self._add_line("## 5. Cash Position")
        self._add_line()

        operating_total = 0.0
        reserve_total = 0.0

        for record in balance_sheet_data:
            category = record.get('category', '').lower()
            if 'asset' not in category:
                continue

            balance = record.get('current_balance', 0) or 0
            account_name = record.get('account_name', '').lower()
            subcategory = record.get('subcategory', '').lower()

            # Classify as operating or reserve
            if 'reserve' in account_name or 'reserve' in subcategory:
                reserve_total += balance
            else:
                operating_total += balance

        combined = operating_total + reserve_total

        rows = [
            ["Operating Accounts", self._fmt_currency(operating_total)],
            ["Reserve Accounts", self._fmt_currency(reserve_total)],
            ["**Combined Total**", f"**{self._fmt_currency(combined)}**"],
        ]

        self._add_table(["Account Type", "Balance"], rows, ['l', 'r'])
        self._add_line()

    def _generate_mom_changes(self, expense_trend_data: List[Dict]):
        """Section 6: Month-over-Month expense changes."""
        self._add_line("## 6. Month-over-Month Changes (Oct to Nov)")
        self._add_line()

        # Compare Oct to Nov for expense categories
        changes = []

        for record in expense_trend_data:
            if record.get('is_total'):
                continue

            oct_val = record.get('oct', 0) or 0
            nov_val = record.get('nov', 0) or 0
            change = nov_val - oct_val

            if change != 0:
                changes.append({
                    'account': f"{record.get('account_code', '')} - {record.get('account_name', '')}",
                    'oct': oct_val,
                    'nov': nov_val,
                    'change': change
                })

        # Sort by absolute change descending
        changes.sort(key=lambda x: abs(x['change']), reverse=True)

        if not changes:
            self._add_line("*No month-over-month data available*")
        else:
            rows = []
            for c in changes[:10]:  # Top 10
                rows.append([
                    c['account'][:40],
                    self._fmt_currency(c['oct']),
                    self._fmt_currency(c['nov']),
                    self._fmt_currency(c['change'])
                ])

            self._add_table(
                ["Account", "October", "November", "Change"],
                rows,
                ['l', 'r', 'r', 'r']
            )

        self._add_line()

    def _generate_notable_transactions(self, disbursement_data: List[Dict]):
        """Section 7: Notable transactions over $2,000."""
        self._add_line("## 7. Notable Transactions (>$2,000)")
        self._add_line()

        notable = []
        for record in disbursement_data:
            amount = record.get('amount', 0) or 0
            if amount > 2000:
                notable.append({
                    'vendor': record.get('vendor', 'Unknown'),
                    'amount': amount,
                    'description': record.get('description', record.get('account_name', '')),
                    'check': record.get('check_number', '')
                })

        # Sort by amount descending
        notable.sort(key=lambda x: x['amount'], reverse=True)

        if not notable:
            self._add_line("*No transactions over $2,000*")
        else:
            rows = []
            for n in notable[:15]:  # Limit to 15
                rows.append([
                    n['vendor'][:30],
                    self._fmt_currency(n['amount']),
                    n['description'][:35],
                    n['check']
                ])

            self._add_table(
                ["Vendor", "Amount", "Description", "Check #"],
                rows,
                ['l', 'r', 'l', 'l']
            )

        self._add_line()

    def _write(self):
        """Write lines to file."""
        content = "\n".join(self.lines)

        # Ensure under 400 lines
        if len(self.lines) > 400:
            logger.warning(f"Markdown has {len(self.lines)} lines, truncating to 400")
            content = "\n".join(self.lines[:400])
            content += "\n\n*[Truncated for context efficiency]*"

        with open(self.output_path, 'w') as f:
            f.write(content)

        logger.info(f"Saved markdown summary ({len(self.lines)} lines) to {self.output_path}")
