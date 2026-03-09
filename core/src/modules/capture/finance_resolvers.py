"""Finance reference resolvers — wallet, category.

Uses existing service layer (wallet_service, category_service) for auto-creation.
No duplicated creation logic — delegates to BaseCRUDService.create().
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .resolvers import ReferenceResolver, _normalize, register

# Map natural language → wallet type + display name
_WALLET_TYPE_MAP: dict[str, tuple[str, str]] = {
    "cash": ("cash", "現金"),
    "現金": ("cash", "現金"),
    "credit_card": ("credit_card", "信用卡"),
    "信用卡": ("credit_card", "信用卡"),
    "e_wallet": ("e_wallet", "電子錢包"),
    "電子錢包": ("e_wallet", "電子錢包"),
    "linepay": ("e_wallet", "LINE Pay"),
    "line_pay": ("e_wallet", "LINE Pay"),
    "悠遊付": ("e_wallet", "悠遊付"),
    "街口": ("e_wallet", "街口支付"),
    "bank_account": ("bank_account", "銀行帳戶"),
    "銀行": ("bank_account", "銀行帳戶"),
    "debit_card": ("debit_card", "金融卡"),
    "金融卡": ("debit_card", "金融卡"),
}

# Map natural language → category display name + icon
_CATEGORY_NAME_MAP: dict[str, tuple[str, str]] = {
    "food": ("餐飲", "🍽️"),
    "food_and_dining": ("餐飲", "🍽️"),
    "dining": ("餐飲", "🍽️"),
    "餐飲": ("餐飲", "🍽️"),
    "早餐": ("餐飲", "🍽️"),
    "午餐": ("餐飲", "🍽️"),
    "晚餐": ("餐飲", "🍽️"),
    "transport": ("交通", "🚗"),
    "transportation": ("交通", "🚗"),
    "交通": ("交通", "🚗"),
    "entertainment": ("娛樂", "🎮"),
    "娛樂": ("娛樂", "🎮"),
    "shopping": ("購物", "🛒"),
    "購物": ("購物", "🛒"),
    "groceries": ("日用品", "🛒"),
    "日用品": ("日用品", "🛒"),
    "health": ("醫療", "🏥"),
    "medical": ("醫療", "🏥"),
    "醫療": ("醫療", "🏥"),
    "education": ("教育", "📚"),
    "教育": ("教育", "📚"),
    "housing": ("居住", "🏠"),
    "rent": ("居住", "🏠"),
    "居住": ("居住", "🏠"),
    "utilities": ("水電", "💡"),
    "水電": ("水電", "💡"),
    "subscription": ("訂閱", "📱"),
    "訂閱": ("訂閱", "📱"),
    "income": ("收入", "💰"),
    "salary": ("薪資", "💰"),
    "收入": ("收入", "💰"),
    "other": ("其他", "📌"),
    "其他": ("其他", "📌"),
}


class WalletResolver(ReferenceResolver):
    schema = "finance"
    table = "wallets"

    async def find_by_name(self, db: AsyncSession, space_id: str, raw: str) -> str | None:
        """Wallet lookup — checks raw value and mapped display name via service layer."""
        from src.modules.finance.services import wallet_service

        normalized = _normalize(raw)
        search_terms = [normalized.replace("_", " ")]
        mapped = _WALLET_TYPE_MAP.get(normalized)
        if mapped:
            search_terms.append(mapped[1])  # display name

        for term in search_terms:
            wallet = await wallet_service.find_by_name(db, space_id, term)
            if wallet:
                return wallet.id
        return None

    async def auto_create(
        self, db: AsyncSession, space_id: str, raw: str, created_by: str | None
    ) -> str:
        from src.modules.finance.schemas import WalletCreate
        from src.modules.finance.services import wallet_service

        normalized = _normalize(raw)
        wtype, wname = _WALLET_TYPE_MAP.get(normalized, ("cash", raw.replace("_", " ").title()))
        data = WalletCreate(name=wname, type=wtype, currency="TWD")
        wallet = await wallet_service.create(db, space_id, data, created_by)
        return wallet.id


class CategoryResolver(ReferenceResolver):
    schema = "finance"
    table = "categories"

    async def find_by_name(self, db: AsyncSession, space_id: str, raw: str) -> str | None:
        """Category lookup — checks raw value and mapped display name via service layer."""
        from src.modules.finance.services import category_service

        normalized = _normalize(raw)
        search_terms = [normalized.replace("_", " ")]
        mapped = _CATEGORY_NAME_MAP.get(normalized)
        if mapped:
            search_terms.append(mapped[0])  # display name

        for term in search_terms:
            cat = await category_service.find_by_name(db, space_id, term)
            if cat:
                return cat.id
        return None

    async def auto_create(
        self, db: AsyncSession, space_id: str, raw: str, created_by: str | None
    ) -> str:
        from src.modules.finance.schemas import CategoryCreate
        from src.modules.finance.services import category_service

        normalized = _normalize(raw)
        cname, cicon = _CATEGORY_NAME_MAP.get(normalized, (raw.replace("_", " ").title(), "📌"))
        data = CategoryCreate(name=cname, icon=cicon)
        cat = await category_service.create(db, space_id, data, created_by)
        return cat.id


def register_finance_resolvers() -> None:
    """Register all finance resolvers. Called on module import."""
    register("finance.wallet", WalletResolver())
    register("finance.category", CategoryResolver())
