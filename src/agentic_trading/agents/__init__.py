"""7-Agent AI Research Desk package: multi-agent intelligence, memory, and orchestration."""
from __future__ import annotations

from agentic_trading.agents.data_analyst import DataAnalyst, FundamentalSnapshot
from agentic_trading.agents.envelope import (
    AgentEnvelope,
    compute_inputs_hash,
    invoke_with_schema_guard,
)
from agentic_trading.agents.llm_client import (
    DeterministicStubLLMClient,
    FailoverLLMClient,
    LLMClient,
    LocalOllamaJSONClient,
)
from agentic_trading.agents.market_analyst import MarketAnalyst
from agentic_trading.agents.memory import (
    DecisionLog,
    DecisionRecord,
    HumanLessonsStore,
    WorkingState,
)
from agentic_trading.agents.news_analyst import NewsAnalyst, NewsArticle, ScheduledEvent
from agentic_trading.agents.opportunity_scout import (
    CandidateProfile,
    OpportunityScout,
    ShortlistResult,
)
from agentic_trading.agents.orchestrator import (
    DeskCycleResult,
    TradingDeskOrchestrator,
    WatchlistTarget,
)
from agentic_trading.agents.reporter import DailyReporter
from agentic_trading.agents.strategist import Strategist, TradingMandate

__all__ = [
    "AgentEnvelope",
    "CandidateProfile",
    "DailyReporter",
    "DataAnalyst",
    "DecisionLog",
    "DecisionRecord",
    "DeskCycleResult",
    "DeterministicStubLLMClient",
    "FailoverLLMClient",
    "FundamentalSnapshot",
    "HumanLessonsStore",
    "LLMClient",
    "LocalOllamaJSONClient",
    "MarketAnalyst",
    "NewsAnalyst",
    "NewsArticle",
    "OpportunityScout",
    "ScheduledEvent",
    "ShortlistResult",
    "Strategist",
    "TradingDeskOrchestrator",
    "TradingMandate",
    "WatchlistTarget",
    "WorkingState",
    "compute_inputs_hash",
    "invoke_with_schema_guard",
]
