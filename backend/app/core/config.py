"""集中管理环境变量与环境安全约束。"""

from __future__ import annotations

import hmac
import re
from enum import StrEnum
from functools import lru_cache
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.db_url import normalize_postgres_url

_SHOP_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AppEnvironment(StrEnum):
    """应用运行环境。"""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def agent_loop_llm_call_floor(
    *, max_turns: int, compaction_max_calls: int, quality_max_attempts: int
) -> int:
    """v2 工具循环一个回合最坏路径上的 LLM 调用次数（§6.10）。

    每轮一次决策调用 + 压缩调用 + 每次质量尝试（生成 + 独立 Reviewer）。最终作答直接由
    最后一轮决策产生，所以第一次质量尝试的「生成」已计入 `max_turns`，不能再计一次，故减 1。
    """

    return max_turns + compaction_max_calls + 2 * quality_max_attempts - 1


class Settings(BaseSettings):
    """Borough 后端配置。

    真实密钥和连接信息只从环境变量或未纳入版本控制的 `.env` 读取。
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_version: str = "0.1.0"
    database_url: str
    frontend_origin: AnyHttpUrl
    # 顾客端（shop）的精确 Origin。可选：未配置时只放行商家端；与 FRONTEND_ORIGIN 同样禁止 `*`。
    shop_origin: AnyHttpUrl | None = None
    business_timezone: str = "Asia/Shanghai"
    demo_merchant_tokens: dict[str, UUID] = Field(default_factory=dict)
    demo_merchants_endpoint_enabled: bool = True
    # 生产环境默认关闭演示端点。演示部署（对外展示用）必须显式开启这一项，
    # 而不是靠把 APP_ENV 降级成非生产来绕过——后者会同时关掉导出签名密钥必填、
    # 管理员令牌必填等一整组生产校验。
    demo_deployment_mode: bool = False
    # D18⑩：完整每日简报的定时预生成默认关闭——Cron 接线归 N5，真实首次生成需 R3
    # 授权；本版只支持商家手动触发（GET 首次现算 / POST regenerate）。
    daily_brief_schedule_enabled: bool = False
    session_ttl_seconds: int = Field(default=86_400, ge=300, le=2_592_000)
    buyer_alias_secret: str | None = None
    demo_customer_identities: dict[str, str] = Field(default_factory=dict)
    db_connect_max_attempts: int = Field(default=5, ge=1, le=20)
    db_connect_retry_seconds: float = Field(default=1.0, ge=0, le=60)
    db_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    # 推理模型出一次结构化意图要生成 1000+ 个 token（大部分是 reasoning），30 秒
    # 偏紧；超时在 DeepSeekLlmClient 里被吞成 fallback + degraded，表现为「模型没理解」
    # 而不是「超时了」，很难查。
    llm_timeout_seconds: float = Field(default=90.0, gt=0, le=120)
    llm_disable_thinking_for_structured: bool = True
    # `converse()` 走哪种 DeepSeek 协议。默认 openai：v1 链路已在用它，切换到 anthropic
    # 须有双协议真实冒烟的实测依据（PRD §16 风险表第 1 行；见后端计划 §6.17）。
    # 进程级配置；同一次对话的循环只用一种协议，切换后新开对话，不跨协议回放历史。
    llm_protocol: Literal["openai", "anthropic"] = "openai"
    # `converse()` 的思考模式。官方默认开启，这里显式默认关闭并且每次请求都发送，
    # 不依赖提供方默认值。开启后成本、延迟与 reasoning 回放要求都不同，改默认须以实测为据。
    # 单次调用可经 `LlmCallOptions.thinking="disabled"` 收紧，但不能越过这里放开。
    llm_thinking: Literal["enabled", "disabled"] = "disabled"
    # 默认两轮生成/复核：在保留一次纠错机会的同时，保证下方 10 次请求上限覆盖完整路径。
    # 如需三轮，部署时须连同 MAX_LLM_CALLS_PER_REQUEST 一起显式提高。
    quality_max_attempts: int = Field(default=2, ge=1, le=3)
    # 最坏调用路径是 classify 1 + understand 3（`intent/service.py` 自带 2 次重试）
    # + 指标口径 1 + （生成 + 复核）× 2 = 9 次，四个调用点共用同一个 LlmBudget。
    # 定 6 会让 understand 一重试就把质量循环挤成「预算耗尽」降级，把排查方向带偏。
    llm_max_calls_per_request: int = Field(
        default=10,
        ge=1,
        le=20,
        validation_alias=AliasChoices("MAX_LLM_CALLS_PER_REQUEST", "llm_max_calls_per_request"),
    )
    llm_max_tokens_per_request: int = Field(
        default=25_000,
        ge=100,
        le=200_000,
        validation_alias=AliasChoices("MAX_LLM_TOKENS_PER_REQUEST", "llm_max_tokens_per_request"),
    )
    # 全局每日预算（`llm_daily_budget` 只按 usage_date 聚合，不分商家、不分访客，
    # 公开演示时所有人共用同一个池子）。500_000 = 单请求上限 25_000 × 20 个问题，
    # 即最坏情况也保证 20 个完整问题。2026-08-17 真实 `deepseek-v4-flash` 实测每个
    # 完整问题约 6_000 token，因此实际可支撑约 80 个。
    llm_daily_budget_tokens: int = Field(default=500_000, ge=1_000, le=100_000_000)
    # v2 工具循环的五项上限（§6.10，PRD A2）。与上面 v1 的 `llm_max_calls_per_request`
    # 互不共享、互不校验：v1 的 10 按它自己的最坏路径精确配出，让 v2 公式去校验它，
    # 要么 v2 被迫压缩轮数，要么有人为了让校验通过去调大它，都会在不知情时改变 v1 行为。
    # 改这几个值须按 `agent_loop_llm_call_floor()` 重算并同步 AGENT_LOOP_MAX_LLM_CALLS。
    agent_loop_max_turns: int = Field(default=8, ge=1, le=32)
    agent_loop_max_tool_calls: int = Field(default=16, ge=1, le=64)
    agent_loop_wall_clock_seconds: float = Field(default=60.0, gt=0, le=300)
    agent_loop_max_llm_calls: int = Field(default=12, ge=1, le=64)
    # v2 自己的质量尝试次数，不复用 v1 的 `quality_max_attempts`：共用一个字段，
    # v1 调到 3 轮就会让 v2 的预算公式拒绝启动（反之亦然），两条链路就又绑在一起了。
    agent_loop_quality_max_attempts: int = Field(default=2, ge=1, le=3)
    # N4 摘要压缩（§6.12）的调用额度。N2 循环不发起压缩调用，默认的 1 是提前计入公式的预留。
    compaction_max_calls: int = Field(default=1, ge=0, le=4)
    # 压缩策略与触发阈值（§6.12，N4-A）。未经真实模型对比前默认零 LLM 调用的工具结果清理；
    # 阈值按字符估算（与 `estimate_tokens` 同口径）。单请求 token 预算按多次调用累计，每次决策都重发
    # 整段上下文，所以阈值要远低于 MAX_LLM_TOKENS_PER_REQUEST，否则压缩来不及生效预算就先耗尽。
    # 取值与 `app.agent.loop.compaction.CompactionStrategy` 一致；
    # core 不反向依赖 agent，故写成字面量。
    compaction_strategy: Literal["TOOL_RESULT_PRUNING", "SUMMARIZATION"] = "TOOL_RESULT_PRUNING"
    compaction_trigger_tokens: int = Field(default=8_000, ge=1_000, le=200_000)
    # v2 两端 Chat 回放同一会话最近几轮的用户与助手文字（D-N4-1，契约 §6.10 / §8.8.3）。
    # 0 表示不回放。只回放文字，不回放工具结果；更早的部分交给 N4 压缩。
    chat_history_max_turns: int = Field(default=6, ge=0, le=20)
    # N4 回合结束后的记忆抽取预算，与主工具循环分开；仍受每日预算总熔断限制。
    memory_extraction_max_calls: int = Field(default=1, ge=1, le=4)
    memory_extraction_max_tokens: int = Field(default=4_000, ge=100, le=20_000)
    # 受信 Skill 的两项上限（PRD A4）：单个正文字符数与单回合 `load_skill` 次数。
    # 超限都是拒绝而非截断；默认值与 `app.skills.loader` 的常量一致（有测试守着）。
    skill_max_chars: int = Field(default=8_000, ge=500, le=64_000)
    skill_max_per_turn: int = Field(default=3, ge=1, le=8)
    # 1024 对推理模型是错的：2026-08-17 实测单次结构化意图光 reasoning_tokens 就要
    # 1400–2200，正文一个字都吐不出来，content 返回空串，三次重试全部失败后回落
    # CHAT 模式——每次提问真实扣费却只得到兜底文案。这是上限不是花费，留足即可。
    # 4_096 同样不够：2026-08-22 真实模型验收发现环比/同比这类需要更多推理步骤的
    # 回答生成（比较两个周期、算百分比、组织语言）会把 4_096 全部耗在推理上，
    # 正文同样吐空，answer_service.py 把它当作模型不可用而降级为确定性摘要
    # （这是 R7 要求的正确兜底，但让本可回答的问题白白降级）。提到本字段允许的
    # 上限 8_000 留出足够推理余量；`remaining = budget.max_tokens - budget.tokens`
    # 仍会在单请求预算耗尽时把它按比例砍下去，不会让单次调用绕开每请求上限。
    llm_max_output_tokens_per_call: int = Field(default=8_000, ge=64, le=8_000)
    # 零 LLM 前置闸门：问题与业务知识库/指标目录/商家历史记忆的加权匹配分低于
    # 阈值时直接拒答，不占用任何 LLM 调用。默认阈值 3 = 至少一个候选词命中某篇
    # 知识文档的标题（见 openspec/changes/add-question-prefilter-gate/design.md D5）。
    question_prefilter_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("QUESTION_PREFILTER_ENABLED", "question_prefilter_enabled"),
    )
    question_prefilter_min_score: int = Field(
        default=3,
        ge=0,
        validation_alias=AliasChoices(
            "QUESTION_PREFILTER_MIN_SCORE", "question_prefilter_min_score"
        ),
    )
    # 本地化批量翻译通道的独立预算，与上面 llm_max_calls_per_request/
    # llm_max_tokens_per_request（主 Agent 流程）互不共享：翻译是 P1 增量
    # 能力，不应该挤占聊天问答本身的预算，也方便运维分开看两条费用曲线
    # （`llm_usage.purpose` 已经区分 AGENT / LOCALIZATION）。
    localization_max_calls_per_request: int = Field(
        default=4,
        ge=1,
        le=20,
        validation_alias=AliasChoices(
            "LOCALIZATION_MAX_CALLS_PER_REQUEST", "localization_max_calls_per_request"
        ),
    )
    localization_max_tokens_per_request: int = Field(
        default=12_000,
        ge=100,
        le=200_000,
        validation_alias=AliasChoices(
            "LOCALIZATION_MAX_TOKENS_PER_REQUEST", "localization_max_tokens_per_request"
        ),
    )
    # 单次批量翻译调用最多打包多少条待译文本；超出的条目留给下一批调用，
    # 受上面的单请求调用次数上限约束。
    localization_max_batch_items: int = Field(
        default=20,
        ge=1,
        le=200,
        validation_alias=AliasChoices(
            "LOCALIZATION_MAX_BATCH_ITEMS", "localization_max_batch_items"
        ),
    )
    # 单次批量翻译调用里所有条目文本长度之和的上限；单条本身超过这个上限则
    # 永远凑不成一批，直接缺席（不抛异常）。
    localization_max_batch_chars: int = Field(
        default=12_000,
        ge=100,
        le=200_000,
        validation_alias=AliasChoices(
            "LOCALIZATION_MAX_BATCH_CHARS", "localization_max_batch_chars"
        ),
    )
    rate_limit_per_minute: int = Field(default=10, ge=1, le=10_000)
    trusted_proxy_hops: int = Field(default=0, ge=0, le=4)
    trusted_proxy_ips: str = ""
    admin_token: str | None = None
    # 只读令牌：与 admin_token 共用同一批 `/api/admin/*` 端点，但只放行 GET
    # （见 `require_admin_or_viewer_token`）。它是可以打包进前端构建产物、公开
    # 展示的值——与演示商家 Token 同一豁免原则（AGENTS.md R6）；`admin_token`
    # 仍然绝不进代码或构建产物。
    viewer_token: str | None = None
    knowledge_max_document_bytes: int = Field(default=262_144, ge=1, le=2_097_152)
    export_signing_secret: str | None = None
    export_url_ttl_minutes: int = Field(default=15, ge=1, le=60)

    @property
    def trusted_proxy_ip_set(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.trusted_proxy_ips.split(",") if item.strip())

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: Any) -> Any:
        return normalize_postgres_url(value)

    @property
    def cors_allowed_origins(self) -> list[str]:
        """CORS 放行的精确 Origin：商家端，加上已配置的顾客端；永不含通配。"""

        origins = [str(self.frontend_origin).rstrip("/")]
        if self.shop_origin is not None:
            origins.append(str(self.shop_origin).rstrip("/"))
        return origins

    @field_validator("frontend_origin", "shop_origin", mode="before")
    @classmethod
    def reject_wildcard_origin(cls, value: Any) -> Any:
        if value == "*":
            raise ValueError("FRONTEND_ORIGIN / SHOP_ORIGIN 必须是精确 Origin，不能使用 *")
        return value

    @field_validator("frontend_origin", "shop_origin")
    @classmethod
    def require_origin_only(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is None:
            return value
        if (
            value.path not in (None, "/")
            or value.query is not None
            or value.fragment is not None
            or value.username is not None
            or value.password is not None
        ):
            raise ValueError("FRONTEND_ORIGIN / SHOP_ORIGIN 只能包含 scheme、host 和 port")
        return value

    @field_validator("business_timezone")
    @classmethod
    def require_business_timezone(cls, value: str) -> str:
        if value != "Asia/Shanghai":
            raise ValueError("BUSINESS_TIMEZONE 必须固定为 Asia/Shanghai")
        return value

    @model_validator(mode="after")
    def enforce_agent_loop_budget(self) -> Settings:
        floor = agent_loop_llm_call_floor(
            max_turns=self.agent_loop_max_turns,
            compaction_max_calls=self.compaction_max_calls,
            quality_max_attempts=self.agent_loop_quality_max_attempts,
        )
        if self.agent_loop_max_llm_calls < floor:
            raise ValueError(
                f"AGENT_LOOP_MAX_LLM_CALLS={self.agent_loop_max_llm_calls} 不足以覆盖最坏路径 "
                f"{floor} = AGENT_LOOP_MAX_TURNS {self.agent_loop_max_turns} "
                f"+ COMPACTION_MAX_CALLS {self.compaction_max_calls} "
                f"+ 2 × AGENT_LOOP_QUALITY_MAX_ATTEMPTS {self.agent_loop_quality_max_attempts} − 1"
            )
        return self

    @model_validator(mode="after")
    def enforce_viewer_token_is_distinct(self) -> Settings:
        # 不分环境：两把钥匙撞了，「只读」这条边界就不存在了，必须在配置阶段
        # 拦下，而不是指望调用方记得不要配错——包括本地开发环境。
        if (
            self.admin_token
            and self.viewer_token
            and hmac.compare_digest(self.admin_token, self.viewer_token)
        ):
            raise ValueError("ADMIN_TOKEN 与 VIEWER_TOKEN 不可相同，否则只读令牌等同管理员令牌")
        return self

    @model_validator(mode="after")
    def enforce_environment_safety(self) -> Settings:
        if self.app_env is AppEnvironment.PRODUCTION:
            self.demo_merchants_endpoint_enabled = self.demo_deployment_mode
            if not self.export_signing_secret:
                raise ValueError("生产环境必须配置 EXPORT_SIGNING_SECRET")
            if self._is_weak_secret(self.export_signing_secret):
                raise ValueError("EXPORT_SIGNING_SECRET 不可使用弱占位值")
            if not self.buyer_alias_secret:
                raise ValueError("生产环境必须配置 BUYER_ALIAS_SECRET")
            if self._is_weak_secret(self.buyer_alias_secret):
                raise ValueError("BUYER_ALIAS_SECRET 不可使用弱占位值")
            if self.llm_api_key and not self.admin_token:
                raise ValueError("生产环境配置 LLM_API_KEY 时必须设置 ADMIN_TOKEN")
            if self.admin_token and self._is_weak_secret(self.admin_token):
                raise ValueError("ADMIN_TOKEN 不可使用弱占位值")
        return self

    @field_validator("demo_customer_identities")
    @classmethod
    def validate_demo_customer_identities(cls, value: dict[str, str]) -> dict[str, str]:
        for slug, buyer_key in value.items():
            if not _SHOP_SLUG_PATTERN.fullmatch(slug):
                raise ValueError("DEMO_CUSTOMER_IDENTITIES 的键必须是合法 shop_slug")
            if not buyer_key.strip():
                raise ValueError("DEMO_CUSTOMER_IDENTITIES 的值不得为空")
        return value

    @staticmethod
    def _is_weak_secret(value: str) -> bool:
        normalized = value.strip().lower()
        placeholder_markers = ("<", "placeholder", "change-me", "example", "development")
        return len(value) < 16 or any(marker in normalized for marker in placeholder_markers)


@lru_cache
def get_settings() -> Settings:
    """读取并缓存进程级配置。"""

    return Settings()
