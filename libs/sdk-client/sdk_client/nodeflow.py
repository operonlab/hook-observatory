"""Nodeflow API client — Core module at /api/nodeflow.

Wraps DAG flow orchestration: flows, nodes, edges, runs, and action registry.

Usage:
    from sdk_client.nodeflow import NodeflowClient

    client = NodeflowClient()
    flows = client.list_flows()
    detail = client.get_flow("flow-uuid")
"""

from typing import Any

from ._base import BaseClient


class NodeflowClient(BaseClient):
    """HTTP client for the Nodeflow Core API module.

    Args:
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:10000.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(module="nodeflow", **kwargs)

    # ======================== Flows ========================

    def list_flows(self, page: int = 1, page_size: int = 20) -> dict:
        """List flows. GET /flows"""
        return self._get("/flows", {"page": page, "page_size": page_size})

    def get_flow(self, flow_id: str) -> dict:
        """Get flow detail with nodes and edges. GET /flows/{id}"""
        return self._get(f"/flows/{flow_id}")

    def create_flow(self, data: dict) -> dict:
        """Create a flow. POST /flows

        Body: name, description, trigger_type (event|schedule|manual),
              trigger_config, status (default: draft).
        """
        return self._post("/flows", data)

    def update_flow(self, flow_id: str, data: dict) -> dict:
        """Update a flow. PUT /flows/{id}"""
        return self._put(f"/flows/{flow_id}", data)

    def activate_flow(self, flow_id: str) -> dict:
        """Activate a flow. POST /flows/{id}/activate"""
        return self._post(f"/flows/{flow_id}/activate")

    def pause_flow(self, flow_id: str) -> dict:
        """Pause a flow. POST /flows/{id}/pause"""
        return self._post(f"/flows/{flow_id}/pause")

    def trigger_flow(self, flow_id: str, input_data: dict | None = None) -> dict:
        """Manually trigger a flow. POST /flows/{id}/trigger"""
        return self._post(f"/flows/{flow_id}/trigger", {"input_data": input_data or {}})

    # ======================== Nodes ========================

    def list_nodes(self, flow_id: str) -> list[dict]:
        """List nodes in a flow. GET /flows/{id}/nodes"""
        return self._get(f"/flows/{flow_id}/nodes")

    def create_node(self, data: dict) -> dict:
        """Create a node. POST /nodes

        Body: flow_id, node_type, label, config, position_x, position_y.
        """
        return self._post("/nodes", data)

    def update_node(self, node_id: str, data: dict) -> dict:
        """Update a node. PUT /nodes/{id}"""
        return self._put(f"/nodes/{node_id}", data)

    def delete_node(self, node_id: str) -> None:
        """Delete a node. DELETE /nodes/{id}"""
        self._delete(f"/nodes/{node_id}")

    # ======================== Edges ========================

    def list_edges(self, flow_id: str) -> list[dict]:
        """List edges in a flow. GET /flows/{id}/edges"""
        return self._get(f"/flows/{flow_id}/edges")

    def create_edge(self, data: dict) -> dict:
        """Create an edge. POST /edges

        Body: flow_id, source_node_id, target_node_id, source_port (default: output).
        """
        return self._post("/edges", data)

    def delete_edge(self, edge_id: str) -> None:
        """Delete an edge. DELETE /edges/{id}"""
        self._delete(f"/edges/{edge_id}")

    # ======================== Runs ========================

    def list_runs(self, flow_id: str, page: int = 1, page_size: int = 20) -> dict:
        """List flow runs. GET /flows/{id}/runs"""
        return self._get(f"/flows/{flow_id}/runs", {"page": page, "page_size": page_size})

    def get_run(self, flow_run_id: str) -> dict:
        """Get run detail. GET /flow-runs/{id}"""
        return self._get(f"/flow-runs/{flow_run_id}")

    # ======================== Registry ========================

    def list_actions(self) -> list[dict]:
        """List available action types. GET /actions"""
        return self._get("/actions")
