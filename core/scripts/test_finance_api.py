"""Finance API Integration Test Suite.

Usage:
    python3 core/scripts/test_finance_api.py [--base-url URL] [--verbose]

Requires: httpx (pip install httpx)
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field

import httpx

# ---------- Config ----------

DEFAULT_BASE_URL = "http://localhost:8801"
TEST_USER = {"email": "test-finance@example.com", "password": "Test1234", "name": "Finance Tester"}


@dataclass
class TestResult:
    label: str
    method: str
    path: str
    expected: int
    actual: int
    body: dict | list | str = ""
    passed: bool = False
    error: str = ""


@dataclass
class TestReport:
    results: list[TestResult] = field(default_factory=list)
    bugs: list[str] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def add(self, result: TestResult) -> None:
        self.results.append(result)

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print(f"  RESULTS: {self.passed} passed, {self.failed} failed / {len(self.results)} total")
        print("=" * 60)
        if self.failed:
            print("\nFailures:")
            for r in self.results:
                if not r.passed:
                    print(f"  FAIL [{r.actual}] {r.label} (expected {r.expected})")
                    if r.error:
                        print(f"        {r.error}")
        if self.bugs:
            print("\nBugs Found:")
            for b in self.bugs:
                print(f"  - {b}")


class FinanceAPITest:
    def __init__(self, base_url: str, verbose: bool = False):
        self.base_url = base_url
        self.verbose = verbose
        self.report = TestReport()
        self.client: httpx.AsyncClient | None = None
        # Saved IDs
        self.food_id = ""
        self.transport_id = ""
        self.salary_id = ""
        self.cash_id = ""
        self.bank_id = ""
        self.visa_id = ""
        self.txn1_id = ""
        self.txn2_id = ""
        self.sub_id = ""
        self.plan_id = ""

    async def request(
        self,
        label: str,
        method: str,
        path: str,
        *,
        json_data: dict | None = None,
        expected: int = 200,
        params: dict | None = None,
    ) -> dict | list | str:
        """Make API request and record result."""
        url = f"{self.base_url}{path}"
        try:
            resp = await self.client.request(
                method,
                url,
                json=json_data,
                params=params,
            )
            try:
                body = resp.json()
            except Exception:
                body = resp.text

            passed = resp.status_code == expected
            result = TestResult(
                label=label,
                method=method,
                path=path,
                expected=expected,
                actual=resp.status_code,
                body=body,
                passed=passed,
                error=""
                if passed
                else (body.get("detail", "") if isinstance(body, dict) else str(body)[:100]),
            )
            self.report.add(result)

            status = "PASS" if passed else "FAIL"
            print(f"  {status} [{resp.status_code}] {label}")
            if self.verbose and not passed:
                print(f"        Body: {json.dumps(body, ensure_ascii=False)[:200]}")

            return body
        except Exception as e:
            result = TestResult(
                label=label,
                method=method,
                path=path,
                expected=expected,
                actual=0,
                passed=False,
                error=str(e),
            )
            self.report.add(result)
            print(f"  FAIL [ERR] {label}: {e}")
            return {}

    async def setup(self) -> bool:
        """Register or login test user."""
        # Use a temporary client for auth (no cookie jar issues)
        tmp = httpx.AsyncClient(timeout=15.0)

        # Try login first
        resp = await tmp.post(
            f"{self.base_url}/auth/login",
            json={"email": TEST_USER["email"], "password": TEST_USER["password"]},
        )
        if resp.status_code != 200:
            # Register
            resp = await tmp.post(
                f"{self.base_url}/auth/register",
                json=TEST_USER,
            )
            if resp.status_code != 201:
                print(f"  Failed to authenticate: {resp.status_code} {resp.text}")
                await tmp.aclose()
                return False
            print(f"  Registered {TEST_USER['email']}")
        else:
            print(f"  Logged in as {TEST_USER['email']}")

        # Extract session cookie from Set-Cookie header (may be Secure flag)
        cookie_value = ""
        for h in resp.headers.get_list("set-cookie"):
            if "workshop_session=" in h:
                cookie_value = h.split("workshop_session=")[1].split(";")[0]
                break

        if not cookie_value:
            # Fallback: check resp.cookies
            cookie_value = resp.cookies.get("workshop_session", "")

        if not cookie_value:
            print("  WARNING: No session cookie received!")
            await tmp.aclose()
            return False

        await tmp.aclose()

        # Create the main client with the session cookie explicitly set
        self.client = httpx.AsyncClient(
            timeout=15.0,
            cookies={"workshop_session": cookie_value},
        )
        print(f"  Session cookie: {cookie_value[:30]}...")
        return True

    async def cleanup_test_data(self) -> None:
        """Remove test data from previous runs."""
        import psycopg

        try:
            with psycopg.connect("postgresql://joneshong:dev_12345@localhost/workshop") as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM finance.transaction_tags WHERE transaction_id IN "
                        "(SELECT id FROM finance.transactions WHERE space_id = %s)",
                        ("default",),
                    )
                    cur.execute(
                        "DELETE FROM finance.transaction_attachments WHERE transaction_id IN "
                        "(SELECT id FROM finance.transactions WHERE space_id = %s)",
                        ("default",),
                    )
                    for table in [
                        "wallet_snapshots",
                        "transactions",
                        "subscriptions",
                        "installment_plans",
                        "budgets",
                        "categories",
                        "wallets",
                    ]:
                        cur.execute(
                            f"DELETE FROM finance.{table} WHERE space_id = %s", ("default",)
                        )
                conn.commit()
            print("  Cleaned up test data")
        except ImportError:
            print("  psycopg not available, skipping cleanup (tests may fail on duplicates)")

    # ---------- Test Groups ----------

    async def test_categories(self) -> None:
        print("\n--- 1. CATEGORIES ---")
        params = {"space_id": "default"}

        body = await self.request(
            "POST /categories (Food)",
            "POST",
            "/api/finance/categories",
            json_data={"name": "Food", "icon": "utensils", "color": "#FF6B6B"},
            params=params,
            expected=201,
        )
        self.food_id = body.get("id", "") if isinstance(body, dict) else ""

        body = await self.request(
            "POST /categories (Transport)",
            "POST",
            "/api/finance/categories",
            json_data={"name": "Transport", "icon": "car", "color": "#4ECDC4"},
            params=params,
            expected=201,
        )
        self.transport_id = body.get("id", "") if isinstance(body, dict) else ""

        body = await self.request(
            "POST /categories (Salary)",
            "POST",
            "/api/finance/categories",
            json_data={"name": "Salary", "icon": "briefcase", "color": "#45B7D1"},
            params=params,
            expected=201,
        )
        self.salary_id = body.get("id", "") if isinstance(body, dict) else ""

        await self.request(
            "GET /categories (tree)",
            "GET",
            "/api/finance/categories",
            params=params,
            expected=200,
        )

        await self.request(
            "GET /categories?flat=true",
            "GET",
            "/api/finance/categories",
            params={**params, "flat": "true"},
            expected=200,
        )

        if self.food_id:
            body = await self.request(
                "PUT /categories/{id}",
                "PUT",
                f"/api/finance/categories/{self.food_id}",
                json_data={"name": "Food & Drink", "color": "#FF8888"},
                expected=200,
            )
            if isinstance(body, dict):
                actual_name = body.get("name", "")
                if actual_name != "Food & Drink":
                    self.report.bugs.append(
                        f"PUT /categories update name: expected 'Food & Drink', got '{actual_name}'"
                    )

        if self.transport_id:
            await self.request(
                "DELETE /categories/{id}",
                "DELETE",
                f"/api/finance/categories/{self.transport_id}",
                expected=204,
            )

        # Duplicate should return 409 (or 500 if not handled)
        body = await self.request(
            "POST /categories (duplicate name)",
            "POST",
            "/api/finance/categories",
            json_data={"name": "Food & Drink", "icon": "utensils", "color": "#FF6B6B"},
            params=params,
            expected=409,
        )

    async def test_wallets(self) -> None:
        print("\n--- 2. WALLETS ---")
        params = {"space_id": "default"}

        body = await self.request(
            "POST /wallets (Cash)",
            "POST",
            "/api/finance/wallets",
            json_data={
                "name": "Cash",
                "type": "cash",
                "currency": "TWD",
                "initial_balance": "5000",
            },
            params=params,
            expected=201,
        )
        self.cash_id = body.get("id", "") if isinstance(body, dict) else ""

        body = await self.request(
            "POST /wallets (Bank)",
            "POST",
            "/api/finance/wallets",
            json_data={
                "name": "Bank Account",
                "type": "bank_account",
                "currency": "TWD",
                "initial_balance": "100000",
            },
            params=params,
            expected=201,
        )
        self.bank_id = body.get("id", "") if isinstance(body, dict) else ""

        body = await self.request(
            "POST /wallets (Credit Card)",
            "POST",
            "/api/finance/wallets",
            json_data={
                "name": "VISA",
                "type": "credit_card",
                "currency": "TWD",
                "credit_limit": "50000",
            },
            params=params,
            expected=201,
        )
        self.visa_id = body.get("id", "") if isinstance(body, dict) else ""

        await self.request(
            "GET /wallets",
            "GET",
            "/api/finance/wallets",
            params=params,
            expected=200,
        )

        if self.cash_id:
            body = await self.request(
                "GET /wallets/{id}",
                "GET",
                f"/api/finance/wallets/{self.cash_id}",
                expected=200,
            )
            # Verify balance (Decimal may return "5000.0000")
            if isinstance(body, dict):
                from decimal import Decimal as D

                bal = body.get("current_balance")
                if bal is not None and D(str(bal)) != D("5000"):
                    self.report.bugs.append(
                        f"Wallet initial balance mismatch: expected 5000, got {bal}"
                    )

            await self.request(
                "PUT /wallets/{id}",
                "PUT",
                f"/api/finance/wallets/{self.cash_id}",
                json_data={"name": "Cash Wallet"},
                expected=200,
            )

        # Not found
        await self.request(
            "GET /wallets/{bad_id} (404)",
            "GET",
            "/api/finance/wallets/nonexistent",
            expected=404,
        )

    async def test_transactions(self) -> None:
        print("\n--- 3. TRANSACTIONS ---")
        params = {"space_id": "default"}

        body = await self.request(
            "POST /transactions (expense)",
            "POST",
            "/api/finance/transactions",
            json_data={
                "description": "Lunch",
                "amount": "250",
                "type": "expense",
                "category_id": self.food_id,
                "wallet_id": self.cash_id,
                "currency": "TWD",
                "payment_method": "cash",
                "transacted_at": "2026-03-01T12:00:00",
            },
            params=params,
            expected=201,
        )
        self.txn1_id = body.get("id", "") if isinstance(body, dict) else ""

        body = await self.request(
            "POST /transactions (income)",
            "POST",
            "/api/finance/transactions",
            json_data={
                "description": "March Salary",
                "amount": "50000",
                "type": "income",
                "category_id": self.salary_id,
                "wallet_id": self.bank_id,
                "currency": "TWD",
                "payment_method": "bank_transfer",
                "transacted_at": "2026-03-01T09:00:00",
            },
            params=params,
            expected=201,
        )
        self.txn2_id = body.get("id", "") if isinstance(body, dict) else ""

        await self.request(
            "GET /transactions",
            "GET",
            "/api/finance/transactions",
            params=params,
            expected=200,
        )

        await self.request(
            "GET /transactions?year_month=2026-03",
            "GET",
            "/api/finance/transactions",
            params={**params, "year_month": "2026-03"},
            expected=200,
        )

        await self.request(
            "GET /transactions?type=expense",
            "GET",
            "/api/finance/transactions",
            params={**params, "type": "expense"},
            expected=200,
        )

        await self.request(
            "GET /transactions?search=Lunch",
            "GET",
            "/api/finance/transactions",
            params={**params, "search": "Lunch"},
            expected=200,
        )

        if self.txn1_id:
            await self.request(
                "GET /transactions/{id}",
                "GET",
                f"/api/finance/transactions/{self.txn1_id}",
                expected=200,
            )
            await self.request(
                "PUT /transactions/{id}",
                "PUT",
                f"/api/finance/transactions/{self.txn1_id}",
                json_data={"description": "Lunch at restaurant", "amount": "280"},
                expected=200,
            )
            await self.request(
                "DELETE /transactions/{id}",
                "DELETE",
                f"/api/finance/transactions/{self.txn1_id}",
                expected=204,
            )

    async def test_subscriptions(self) -> None:
        print("\n--- 4. SUBSCRIPTIONS ---")
        params = {"space_id": "default"}

        body = await self.request(
            "POST /subscriptions (Netflix)",
            "POST",
            "/api/finance/subscriptions",
            json_data={
                "name": "Netflix",
                "amount": "390",
                "currency": "TWD",
                "billing_cycle": "monthly",
                "category_id": self.food_id,
                "wallet_id": self.bank_id,
                "start_date": "2026-01-01",
            },
            params=params,
            expected=201,
        )
        self.sub_id = body.get("id", "") if isinstance(body, dict) else ""

        await self.request(
            "GET /subscriptions",
            "GET",
            "/api/finance/subscriptions",
            params=params,
            expected=200,
        )

        if self.sub_id:
            await self.request(
                "GET /subscriptions/{id}",
                "GET",
                f"/api/finance/subscriptions/{self.sub_id}",
                expected=200,
            )
            await self.request(
                "PUT /subscriptions/{id}",
                "PUT",
                f"/api/finance/subscriptions/{self.sub_id}",
                json_data={"name": "Netflix Premium", "amount": "490"},
                expected=200,
            )

        await self.request(
            "GET /subscriptions?status=active",
            "GET",
            "/api/finance/subscriptions",
            params={**params, "status": "active"},
            expected=200,
        )

    async def test_installment_plans(self) -> None:
        print("\n--- 5. INSTALLMENT PLANS ---")
        params = {"space_id": "default"}

        body = await self.request(
            "POST /installment-plans",
            "POST",
            "/api/finance/installment-plans",
            json_data={
                "description": "iPhone 16",
                "total_amount": "36900",
                "num_installments": 12,
                "installment_amount": "3075",
                "currency": "TWD",
                "wallet_id": self.visa_id,
                "payment_method": "credit_card",
                "start_date": "2026-01-01",
            },
            params=params,
            expected=201,
        )
        self.plan_id = body.get("id", "") if isinstance(body, dict) else ""

        await self.request(
            "GET /installment-plans",
            "GET",
            "/api/finance/installment-plans",
            params=params,
            expected=200,
        )

        if self.plan_id:
            await self.request(
                "GET /installment-plans/{id}",
                "GET",
                f"/api/finance/installment-plans/{self.plan_id}",
                expected=200,
            )
            await self.request(
                "PUT /installment-plans/{id}",
                "PUT",
                f"/api/finance/installment-plans/{self.plan_id}",
                json_data={"description": "iPhone 16 Pro"},
                expected=200,
            )

    async def test_budgets(self) -> None:
        print("\n--- 6. BUDGETS ---")
        params = {"space_id": "default"}

        await self.request(
            "POST /budgets (Food 2026-03)",
            "POST",
            "/api/finance/budgets",
            json_data={
                "category_id": self.food_id,
                "year_month": "2026-03",
                "budget_amount": "8000",
            },
            params=params,
            expected=201,
        )

        await self.request(
            "POST /budgets (upsert same)",
            "POST",
            "/api/finance/budgets",
            json_data={
                "category_id": self.food_id,
                "year_month": "2026-03",
                "budget_amount": "10000",
            },
            params=params,
            expected=201,
        )

        await self.request(
            "GET /budgets",
            "GET",
            "/api/finance/budgets",
            params=params,
            expected=200,
        )

        await self.request(
            "GET /budgets/2026-03/status",
            "GET",
            "/api/finance/budgets/2026-03/status",
            params=params,
            expected=200,
        )

    async def test_transfer(self) -> None:
        print("\n--- 7. TRANSFER ---")
        params = {"space_id": "default"}

        if self.bank_id and self.cash_id:
            body = await self.request(
                "POST /transfer (Bank->Cash)",
                "POST",
                "/api/finance/transfer",
                json_data={
                    "from_wallet_id": self.bank_id,
                    "to_wallet_id": self.cash_id,
                    "amount": "10000",
                    "currency": "TWD",
                    "description": "ATM Withdrawal",
                    "transacted_at": "2026-03-01T14:00:00",
                },
                params=params,
                expected=200,
            )
            if isinstance(body, list) and len(body) == 2:
                print(
                    f"    -> Transfer created 2 transactions: out={body[0].get('id', '?')}, in={body[1].get('id', '?')}"
                )
            elif isinstance(body, list):
                self.report.bugs.append(f"Transfer should return 2 transactions, got {len(body)}")

    async def test_wallet_advanced(self) -> None:
        print("\n--- 8. WALLET ADVANCED ---")
        params = {"space_id": "default"}

        if self.cash_id:
            await self.request(
                "POST /wallets/{id}/sync",
                "POST",
                f"/api/finance/wallets/{self.cash_id}/sync",
                json_data={"synced_balance": "14500", "notes": "Manual count"},
                params=params,
                expected=200,
            )

            await self.request(
                "GET /wallets/{id}/reconcile",
                "GET",
                f"/api/finance/wallets/{self.cash_id}/reconcile",
                expected=200,
            )

    async def test_summary(self) -> None:
        print("\n--- 9. SUMMARY ---")
        params = {"space_id": "default"}

        body = await self.request(
            "GET /summary/2026-03",
            "GET",
            "/api/finance/summary/2026-03",
            params=params,
            expected=200,
        )
        if isinstance(body, dict):
            fields = ["year_month", "total_income", "total_expense", "net"]
            missing = [f for f in fields if f not in body]
            if missing:
                self.report.bugs.append(f"Summary missing fields: {missing}")

    async def test_edge_cases(self) -> None:
        print("\n--- 10. EDGE CASES ---")
        params = {"space_id": "default"}

        # 401 without auth
        noauth = httpx.AsyncClient(timeout=10)
        resp = await noauth.get(f"{self.base_url}/api/finance/wallets", params=params)
        passed = resp.status_code == 401
        self.report.add(
            TestResult(
                label="GET /wallets (no auth → 401)",
                method="GET",
                path="/api/finance/wallets",
                expected=401,
                actual=resp.status_code,
                passed=passed,
            )
        )
        print(f"  {'PASS' if passed else 'FAIL'} [{resp.status_code}] GET /wallets (no auth → 401)")
        await noauth.aclose()

        # 404 on non-existent transaction
        await self.request(
            "GET /transactions/{bad_id} (404)",
            "GET",
            "/api/finance/transactions/nonexistent",
            expected=404,
        )

        # 404 on non-existent subscription
        await self.request(
            "GET /subscriptions/{bad_id} (404)",
            "GET",
            "/api/finance/subscriptions/nonexistent",
            expected=404,
        )

        # 404 on non-existent installment plan
        await self.request(
            "GET /installment-plans/{bad_id} (404)",
            "GET",
            "/api/finance/installment-plans/nonexistent",
            expected=404,
        )

        # GET with include_inactive
        await self.request(
            "GET /wallets?include_inactive=true",
            "GET",
            "/api/finance/wallets",
            params={**params, "include_inactive": "true"},
            expected=200,
        )

        # Wallet filter by tag
        await self.request(
            "GET /transactions?tag=test",
            "GET",
            "/api/finance/transactions",
            params={**params, "tag": "test"},
            expected=200,
        )

        # Wallet filter by wallet_id
        if self.cash_id:
            await self.request(
                "GET /transactions?wallet_id=...",
                "GET",
                "/api/finance/transactions",
                params={**params, "wallet_id": self.cash_id},
                expected=200,
            )

    async def run(self) -> int:
        """Run all tests and return exit code."""
        print("=" * 60)
        print("  FINANCE API INTEGRATION TEST")
        print(f"  Target: {self.base_url}")
        print("=" * 60)

        print("\n--- 0. SETUP ---")
        if not await self.setup():
            print("ABORT: Cannot authenticate")
            return 1
        await self.cleanup_test_data()

        await self.test_categories()
        await self.test_wallets()
        await self.test_transactions()
        await self.test_subscriptions()
        await self.test_installment_plans()
        await self.test_budgets()
        await self.test_transfer()
        await self.test_wallet_advanced()
        await self.test_summary()
        await self.test_edge_cases()

        self.report.print_summary()

        # Endpoint coverage summary
        endpoints = {
            "GET /wallets",
            "GET /wallets/{id}",
            "POST /wallets",
            "PUT /wallets/{id}",
            "POST /wallets/{id}/sync",
            "GET /wallets/{id}/reconcile",
            "GET /categories",
            "POST /categories",
            "PUT /categories/{id}",
            "DELETE /categories/{id}",
            "GET /transactions",
            "GET /transactions/{id}",
            "POST /transactions",
            "PUT /transactions/{id}",
            "DELETE /transactions/{id}",
            "GET /subscriptions",
            "GET /subscriptions/{id}",
            "POST /subscriptions",
            "PUT /subscriptions/{id}",
            "GET /installment-plans",
            "GET /installment-plans/{id}",
            "POST /installment-plans",
            "PUT /installment-plans/{id}",
            "GET /budgets",
            "POST /budgets",
            "GET /budgets/{year_month}/status",
            "POST /transfer",
            "GET /summary/{year_month}",
        }
        print(f"\n  Endpoint coverage: {len(endpoints)} unique endpoints tested")
        print(f"  Total test cases: {len(self.report.results)}")

        if self.client:
            await self.client.aclose()

        return 0 if self.report.failed == 0 else 1


async def main():
    parser = argparse.ArgumentParser(description="Finance API Integration Test")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    test = FinanceAPITest(args.base_url, verbose=args.verbose)
    exit_code = await test.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
