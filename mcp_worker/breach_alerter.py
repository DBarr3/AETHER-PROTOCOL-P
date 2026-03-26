"""
Aether MCP Worker — Breach Alerter
Sends breach and anomaly alerts from VPS5 back to VPS2.

Aether Systems LLC — Patent Pending
"""

import json
import logging
import os
import time

logger = logging.getLogger("aether.mcp.breach")


class BreachAlerter:
    def __init__(self, node_auth=None):
        self.vps2_url = os.getenv("VPS2_ALERT_ENDPOINT", "http://198.211.115.41/agent/breach-alert")
        self.alert_key = os.getenv("MCP_ALERT_KEY", "")
        self._node_auth = node_auth

    async def send_alert(self, severity, client_id, task_id, reason, protocol_c_hash):
        import httpx
        payload = {"severity": severity, "client_id": client_id, "task_id": task_id, "reason": reason, "protocol_c_hash": protocol_c_hash, "node": "VPS5", "timestamp": time.time()}
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.alert_key:
            headers["X-MCP-Alert-Key"] = self.alert_key
        if self._node_auth:
            headers.update(self._node_auth.sign_request(body))
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.vps2_url, content=body, headers=headers)
            if resp.status_code == 200:
                logger.info("Breach alert sent: severity=%s client=%s", severity, client_id)
                return True
            logger.warning("Breach alert rejected: status=%d", resp.status_code)
            return False
        except Exception as e:
            logger.error("Failed to send breach alert: %s", e)
            return False

    async def send_critical(self, client_id, task_id, details, protocol_c_hash):
        logger.critical("CRITICAL BREACH: client=%s task=%s", client_id, task_id[:8])
        return await self.send_alert("critical", client_id, task_id, details, protocol_c_hash)
