"""BorgNet: Distributed adaptive memetic hive for goal-directed agents."""

__version__ = "0.1.0"

from borgnet.logging import configure_logging, get_logger, set_level
from borgnet.models import MessageEnvelope, PresencePayload, TaskPayload
from borgnet.metrics import Metrics
from borgnet.sim import Agent, Simulation, Task
from borgnet.stigmergy import DemandMap, DemandSignal
from borgnet.memetic import Strategy, StrategyPool
from borgnet.security import (
    QuorumManager,
    SignedEnvelope,
    TrustRegistry,
    TrustScore,
)
from borgnet.agent import AgentRunner, StepResult, StubWorker, Worker

__all__ = [
    "configure_logging",
    "get_logger",
    "set_level",
    "MessageEnvelope",
    "PresencePayload",
    "TaskPayload",
    "Metrics",
    "Agent",
    "Simulation",
    "Task",
    "DemandMap",
    "DemandSignal",
    "Strategy",
    "StrategyPool",
    "QuorumManager",
    "SignedEnvelope",
    "TrustRegistry",
    "TrustScore",
    "AgentRunner",
    "StepResult",
    "StubWorker",
    "Worker",
]
