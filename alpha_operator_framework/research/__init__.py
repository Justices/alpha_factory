"""文献研究与研报认知提炼模块 (Literature & Research Mining Engine)."""

from .document_parser import (
    DocumentType,
    ParsedDocument,
    clean_literature_text,
    extract_formulas_from_text,
    extract_text_from_pdf_bytes,
    load_literature_content,
    parse_document,
)
from .idea_extractor import (
    PaperIdea,
    IdeaExtractor,
)
from .field_loader import (
    BASE_CORE_FIELDS,
    load_real_market_fields,
)
from .field_grounder import (
    SemanticFieldGrounder,
)
from .ast_translator import (
    PaperToASTTranslator,
)
from .db_persister import (
    compute_expression_sha,
    persist_research_pipeline_results,
)
from .llm_client import (
    ProviderConfig,
    LLMConfig,
    LLMConfigManager,
    UnifiedLLMClient,
    load_llm_config_from_env,
    call_openai_compatible_chat,
    extract_ideas_with_llm,
)
from .pipeline import (
    ResearchPipelineResult,
    ingest_literature_to_alphas,
    run_literature_research_pipeline,
)
from .reflexion_engine import (
    LLMReflexionEngine,
    ReflexionIteration,
)

__all__ = [
    "DocumentType",
    "ParsedDocument",
    "clean_literature_text",
    "extract_formulas_from_text",
    "extract_text_from_pdf_bytes",
    "load_literature_content",
    "parse_document",
    "PaperIdea",
    "IdeaExtractor",
    "BASE_CORE_FIELDS",
    "load_real_market_fields",
    "SemanticFieldGrounder",
    "PaperToASTTranslator",
    "compute_expression_sha",
    "persist_research_pipeline_results",
    "ProviderConfig",
    "LLMConfig",
    "LLMConfigManager",
    "UnifiedLLMClient",
    "load_llm_config_from_env",
    "call_openai_compatible_chat",
    "extract_ideas_with_llm",
    "ResearchPipelineResult",
    "ingest_literature_to_alphas",
    "run_literature_research_pipeline",
    "LLMReflexionEngine",
    "ReflexionIteration",
]
