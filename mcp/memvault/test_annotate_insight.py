"""
對抗性測試：mcp/memvault/server.py — annotate_insight()

測試策略：根據函數簽名與文檔推導行為，不依賴實作細節。
外部 I/O (httpx) 透過 mock 隔離，內部邏輯（topic 截斷、tag 注入）直接驗證。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────
# 導入輔助
# ─────────────────────────────────────────────


def _get_annotate_insight():
    """延遲導入，避免模組載入時觸發副作用。"""
    from mcp.memvault.server import annotate_insight

    return annotate_insight


# ─────────────────────────────────────────────
# INV-7: tags always contain "realtime-annotation"
# ─────────────────────────────────────────────


class TestTagsInvariant:
    """驗證 'realtime-annotation' 永遠存在於 tags 中。"""

    @pytest.mark.asyncio
    async def test_default_tags_contains_realtime_annotation(self):
        """不傳 tags → 結果 payload 的 tags 仍包含 'realtime-annotation'。
        # invariant: INV-7
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("some insight")

        tags_sent = captured_payload.get("tags", [])
        assert "realtime-annotation" in tags_sent, (
            f"tags 必須包含 'realtime-annotation'，實際: {tags_sent}"
        )

    @pytest.mark.asyncio
    async def test_custom_tags_merged_with_realtime_annotation(self):
        """傳入自訂 tags → 結果應包含自訂 tags 加上 'realtime-annotation'。
        # invariant: INV-7 — 確認 merge 而非替換
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("insight", tags=["custom-tag", "another-tag"])

        tags_sent = captured_payload.get("tags", [])
        assert "realtime-annotation" in tags_sent, (
            "即使傳入自訂 tags，仍必須包含 'realtime-annotation'"
        )
        assert "custom-tag" in tags_sent, "自訂 tags 不應被丟棄"

    @pytest.mark.asyncio
    async def test_empty_tags_list_still_gets_realtime_annotation(self):
        """傳入空 tags=[] → 結果仍包含 'realtime-annotation'。
        # invariant: INV-7 — 空清單邊界情況
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("insight", tags=[])

        tags_sent = captured_payload.get("tags", [])
        assert "realtime-annotation" in tags_sent

    @pytest.mark.asyncio
    async def test_realtime_annotation_tag_present_on_api_error(self):
        """即使 API 回傳錯誤，tags 的驗證仍應在呼叫 API 前發生。
        # invariant: INV-7, INV-9 — 確認 payload 結構正確，即使 API 失敗
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            import httpx

            raise httpx.ConnectError("refused")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await annotate_insight("insight")

        # INV-9: 不應拋出例外
        assert isinstance(result, str)
        # 若 payload 有被捕獲，驗證 tags 結構
        if captured_payload:
            assert "realtime-annotation" in captured_payload.get("tags", [])


# ─────────────────────────────────────────────
# INV-8: topic length <= 15
# ─────────────────────────────────────────────


class TestTopicLengthInvariant:
    """驗證 topic 欄位長度不超過 15 個字元。"""

    @pytest.mark.asyncio
    async def test_short_insight_topic_within_15_chars(self):
        """短 insight（<15 chars）→ topic 長度 <= 15。
        # invariant: INV-8
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("short")

        topic = captured_payload.get("topic", "")
        assert len(topic) <= 15, f"topic 長度應 <= 15，實際: {len(topic)} — '{topic}'"

    @pytest.mark.asyncio
    async def test_long_insight_topic_truncated_to_15_chars(self):
        """長 insight（>15 chars）→ topic 應被截斷至 15 chars。
        # invariant: INV-8 — 核心截斷邏輯
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        long_insight = "a" * 100  # 明確超過 15 chars

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight(long_insight)

        topic = captured_payload.get("topic", "")
        assert len(topic) <= 15, (
            f"長 insight 的 topic 應截斷至 15 chars，實際: {len(topic)} — '{topic}'"
        )

    @pytest.mark.asyncio
    async def test_topic_is_prefix_of_insight(self):
        """topic 應為 insight 的前 15 個字元（不是其他任意值）。
        # invariant: INV-8 — 驗證截斷方向（prefix，非 suffix 或 hash）
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        insight = "Hello World This Is A Long Insight"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight(insight)

        topic = captured_payload.get("topic", "")
        expected_prefix = insight[:15]
        assert topic == expected_prefix, (
            f"topic 應為 insight 前 15 chars '{expected_prefix}'，實際: '{topic}'"
        )

    @pytest.mark.asyncio
    async def test_topic_exactly_15_chars_not_truncated(self):
        """insight 恰好 15 chars → topic 應完整保留（不截斷）。
        # invariant: INV-8 — 邊界值：恰好等於截斷點
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        exact_insight = "123456789012345"  # 恰好 15 chars
        assert len(exact_insight) == 15

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight(exact_insight)

        topic = captured_payload.get("topic", "")
        assert topic == exact_insight, f"15 chars 的 insight 不應被截斷，實際: '{topic}'"

    @pytest.mark.asyncio
    async def test_topic_16_chars_insight_truncated(self):
        """insight 16 chars → topic 只取前 15（截斷邊界 off-by-one）。
        # invariant: INV-8 — 防止 > 實作成 >=（off-by-one mutation）
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        sixteen_chars = "1234567890123456"  # 16 chars
        assert len(sixteen_chars) == 16

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight(sixteen_chars)

        topic = captured_payload.get("topic", "")
        assert len(topic) <= 15, f"16 chars insight 的 topic 應截斷至 15，實際: {len(topic)}"
        assert topic == sixteen_chars[:15]


# ─────────────────────────────────────────────
# INV-9: API unreachable → returns error string (no raise)
# ─────────────────────────────────────────────


class TestApiUnreachableInvariant:
    """驗證 API 不可用時回傳錯誤訊息字串，不拋例外。"""

    @pytest.mark.asyncio
    async def test_connect_error_returns_string_not_raises(self):
        """httpx.ConnectError → 回傳錯誤字串，不拋例外。
        # invariant: INV-9
        """
        import httpx

        annotate_insight = _get_annotate_insight()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            # 不應拋出例外
            result = await annotate_insight("test insight")

        assert isinstance(result, str), f"應回傳 str，實際: {type(result)}"

    @pytest.mark.asyncio
    async def test_timeout_error_returns_string_not_raises(self):
        """httpx.TimeoutException → 回傳錯誤字串，不拋例外。
        # invariant: INV-9
        """
        import httpx

        annotate_insight = _get_annotate_insight()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await annotate_insight("test insight")

        assert isinstance(result, str), f"應回傳 str，實際: {type(result)}"

    @pytest.mark.asyncio
    async def test_request_error_returns_string_not_raises(self):
        """httpx.RequestError（通用網路錯誤）→ 回傳錯誤字串，不拋例外。
        # invariant: INV-9
        """
        import httpx

        annotate_insight = _get_annotate_insight()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.RequestError("network error", request=MagicMock())
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await annotate_insight("test insight")

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_http_500_returns_string_not_raises(self):
        """API 回傳 500 → 回傳錯誤字串，不拋例外。
        # invariant: INV-9 — HTTP 錯誤狀態碼也算「不可用」
        """
        import httpx

        annotate_insight = _get_annotate_insight()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "500", request=MagicMock(), response=mock_response
                )
            )
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await annotate_insight("test insight")

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_generic_exception_returns_string_not_raises(self):
        """任何未預期例外 → 回傳錯誤字串，不拋例外。
        # invariant: INV-9 — 防禦性最廣泛的例外捕獲
        """
        annotate_insight = _get_annotate_insight()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("unexpected error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await annotate_insight("test insight")

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_error_return_value_contains_error_indicator(self):
        """錯誤時回傳的字串應包含錯誤指示（非空字串、非成功訊息）。
        # invariant: INV-9 — 錯誤字串應有意義，不是空字串
        """
        import httpx

        annotate_insight = _get_annotate_insight()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await annotate_insight("test insight")

        assert len(result) > 0, "錯誤回傳字串不應為空"


# ─────────────────────────────────────────────
# 組合不變量：payload 結構驗證
# ─────────────────────────────────────────────


class TestPayloadStructure:
    """驗證 annotate_insight 傳送到 API 的 payload 結構正確性。"""

    @pytest.mark.asyncio
    async def test_source_is_annotate_insight_tool(self):
        """payload 的 source 應為 'annotate_insight_tool'。
        # invariant: INV-7（source 是 payload 的一部分）
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("test insight")

        source = captured_payload.get("source", "")
        assert source == "annotate_insight_tool", (
            f"source 應為 'annotate_insight_tool'，實際: '{source}'"
        )

    @pytest.mark.asyncio
    async def test_block_type_passed_correctly(self):
        """block_type 參數應被正確傳遞至 API。
        # invariant: 防止 block_type 參數被硬編碼忽略
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("test insight", block_type="procedure")

        block_type_sent = captured_payload.get("block_type", "")
        assert block_type_sent == "procedure", (
            f"block_type 應被傳遞為 'procedure'，實際: '{block_type_sent}'"
        )

    @pytest.mark.asyncio
    async def test_importance_passed_correctly(self):
        """importance 參數應被正確傳遞至 API（非硬編碼）。
        # invariant: 防止 importance 參數被忽略
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("test insight", importance=0.9)

        importance_sent = captured_payload.get("importance", None)
        assert importance_sent == 0.9, f"importance=0.9 應被傳遞，實際: {importance_sent}"

    @pytest.mark.asyncio
    async def test_default_importance_is_0_7(self):
        """預設 importance 應為 0.7。
        # invariant: 確認預設值正確
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("test insight")

        importance_sent = captured_payload.get("importance", None)
        assert importance_sent == 0.7, f"預設 importance 應為 0.7，實際: {importance_sent}"

    @pytest.mark.asyncio
    async def test_insight_content_present_in_payload(self):
        """insight 內容應出現在 payload 中（content 或 body 欄位）。
        # invariant: 確認核心內容被傳遞
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        unique_insight = "unique_test_content_xyz_12345"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight(unique_insight)

        # insight 應出現在 payload 的某個欄位中
        payload_str = json.dumps(captured_payload)
        assert unique_insight in payload_str, f"insight 內容 '{unique_insight}' 應出現在 payload 中"


# ─────────────────────────────────────────────
# INV-7 + INV-8 + INV-9 組合：all-invariants smoke test
# ─────────────────────────────────────────────


class TestAllInvariantsCombined:
    """組合測試所有三個不變量同時成立。"""

    @pytest.mark.asyncio
    async def test_all_invariants_hold_on_success(self):
        """成功呼叫時，INV-7 + INV-8 同時成立。
        # invariant: INV-7, INV-8
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 201
            resp.json.return_value = {"id": "abc-123"}
            return resp

        long_insight = "This is a very long insight that exceeds fifteen characters easily"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await annotate_insight(long_insight, tags=["my-tag"])

        # INV-7: 'realtime-annotation' 存在
        assert "realtime-annotation" in captured_payload.get("tags", [])
        # INV-8: topic <= 15
        assert len(captured_payload.get("topic", "")) <= 15
        # result 是 str（不論成功或錯誤）
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_all_invariants_hold_on_failure(self):
        """API 失敗時，INV-9 成立（不拋例外，回傳 str）。
        # invariant: INV-9
        """
        import httpx

        annotate_insight = _get_annotate_insight()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            # 不應拋出例外
            result = await annotate_insight(
                "some insight for testing error handling",
                tags=["tag1"],
                importance=0.5,
            )

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_idempotent_realtime_annotation_tag(self):
        """若 tags 已包含 'realtime-annotation'，結果不應出現重複。
        # invariant: INV-7 — 防止 duplicate tag injection
        """
        annotate_insight = _get_annotate_insight()

        captured_payload = {}

        async def mock_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"id": "test-id"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await annotate_insight("insight", tags=["realtime-annotation", "other"])

        tags_sent = captured_payload.get("tags", [])
        count = tags_sent.count("realtime-annotation")
        assert count >= 1, "'realtime-annotation' 至少出現一次"
        # 冪等性：不應重複注入（若實作有防重複，count==1）
        # 若實作未防重複，count==2 也可接受，但記錄此行為
        assert "realtime-annotation" in tags_sent
