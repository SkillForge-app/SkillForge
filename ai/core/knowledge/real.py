"""RealRetriever (AI-11): contract A4 over embeddings and the knowledge index.

    retriever = RealRetriever()            # the index from SKILLFORGE_VECTOR_STORE, lazily
    await retriever.retrieve("influencer disclosure rules", "marketing/strategy", k=5)

The query is embedded with the `embedding` role (core/llm/models.yaml; its `query_prefix` is
put first, e.g. BGE's search instruction) and the index returns the closest chunks in the
domain. Same rules as every A4 backend; on top of them, an empty index or one built with a
different model raises ConfigError instead of quietly returning nothing.
"""

from core.knowledge.retrieval import DEFAULT_K, check_request
from core.knowledge.store import VectorStore, check_model, store_from_env
from core.knowledge.types import Passage
from core.llm import embed, load_config
from core.llm.config import ModelConfig
from core.llm.errors import ConfigError
from core.llm.gateway import EMBEDDING_ROLE

EMPTY_INDEX = (
    "the knowledge index is empty; run ingest (python -m evaluation.retrieval build-index)"
)


class RealRetriever:
    def __init__(
        self,
        store: VectorStore | None = None,
        *,
        model_role: str = EMBEDDING_ROLE,
        model_config: ModelConfig | None = None,
    ) -> None:
        self._store = store
        self.model_role = model_role
        self._model_config = model_config

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = store_from_env()
        return self._store

    async def retrieve(self, query: str, domain: str, k: int = DEFAULT_K) -> list[Passage]:
        check_request(query, domain, k)
        role = (self._model_config or load_config()).role(self.model_role)
        info = self.store.info()
        if not info.count:
            raise ConfigError(EMPTY_INDEX)
        check_model(info, role.model, role.dimensions or 0)
        [vector] = await embed([role.query_prefix + query], model_role=self.model_role)
        return [record.to_passage() for record, _ in self.store.search(vector, domain, k)]
