"""Periodic execution of persisted maintenance policies."""

import asyncio

from cs2webui.core.backups import BackupStore
from cs2webui.core.instances import InstanceStore
from cs2webui.core.maintenance import MaintenancePolicy, MaintenanceStore
from cs2webui.host.a2s import A2sClient, A2sError
from cs2webui.host.agent_client import AgentClient, AgentUnavailableError
from cs2webui.host.lifecycle import LifecyclePlanner


class MaintenanceRunner:
    def __init__(
        self,
        instances: InstanceStore,
        policies: MaintenanceStore,
        backups: BackupStore,
        planner: LifecyclePlanner,
        agent: AgentClient,
        a2s: A2sClient,
        game_host: str,
    ) -> None:
        self._instances = instances
        self._policies = policies
        self._backups = backups
        self._planner = planner
        self._agent = agent
        self._a2s = a2s
        self._game_host = game_host

    async def run_due(self) -> list[dict[str, str]]:
        return [await self.run(policy) for policy in self._policies.due()]

    async def run(self, policy: MaintenancePolicy) -> dict[str, str]:
        instance = self._instances.get(policy.instance_id)
        if not instance:
            return {"instance_id": policy.instance_id, "status": "missing"}
        if policy.defer_while_players_online:
            try:
                info = await asyncio.to_thread(
                    self._a2s.query_info, self._game_host, instance.game_port
                )
                if info.players and self._policies.may_defer(
                    instance.id, policy.max_defer_minutes
                ):
                    return {"instance_id": instance.id, "status": "deferred_players_online"}
            except (A2sError, OSError):
                pass
        if policy.backup_before_update:
            try:
                self._backups.create(instance)
            except OSError:
                self._instances.set_status(instance.id, "failed")
                return {"instance_id": instance.id, "status": "backup_failed"}
        commands = self._planner.stop(instance)
        if policy.update_before_restart:
            commands += self._planner.install(instance)
        commands += self._planner.start(instance, masked=False)
        try:
            for command in commands:
                result = await self._agent.execute(command)
                if result["returncode"] != 0:
                    self._instances.set_status(instance.id, "failed")
                    return {"instance_id": instance.id, "status": "failed"}
        except AgentUnavailableError:
            self._instances.set_status(instance.id, "failed")
            return {"instance_id": instance.id, "status": "agent_unavailable"}
        self._instances.set_status(instance.id, "running")
        self._policies.mark_run(instance.id)
        return {"instance_id": instance.id, "status": "completed"}
