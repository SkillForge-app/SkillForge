"""RealRetriever (AI-11): contract A4 over embeddings and the knowledge index.

    retriever = RealRetriever()            # the index from SKILLFORGE_VECTOR_STORE, lazily
    await retriever.retrieve("influencer disclosure rules", "marketing/strategy", k=5)

The query is embedded with the `embedding` role (core/llm/models.yaml; its `query_prefix` is
put first, e.g. BGE's search instruction) and the index returns the closest chunks in the
domain. Same rules as every A4 backend; on top of them, an empty index or one built with a
different model raises ConfigError instead of quietly returning nothing.

The index check (a count over the whole index on pgvector) passes once per INFO_TTL_S, not on
every query (review F6): an index that is emptied later is noticed within that time; until
then a query returns no passages. A failing check is never cached. The store's blocking calls
run in a worker thread, so a query doesn't hold up the event loop.
"""

import asyncio
import time
from collections.abc import Callable

from core.knowledge.retrieval import DEFAULT_K, check_request
from core.knowledge.store import VectorStore, check_model, store_from_env
from core.knowledge.types import Passage
from core.llm import embed, load_config
from core.llm.config import ModelConfig
from core.llm.errors import ConfigError
from core.llm.gateway import EMBEDDING_ROLE

EMPTY_INDEX = (
    "the knowledge index is empty; in production, DE's pipeline fills the pgvector view "
    "(check SKILLFORGE_VECTOR_STORE and DE's active_config); for a local index, run ingest "
    "(python -m evaluation.retrieval build-index)"
)
INFO_TTL_S = 60.0  # how long a passed index check is trusted


class RealRetriever:
    def __init__(
        self,
        store: VectorStore | None = None,
        *,
        model_role: str = EMBEDDING_ROLE,
        model_config: ModelConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self.model_role = model_role
        self._model_config = model_config
        self._clock = clock
        self._checked: dict[tuple[str, int], float] = {}  # (model, dimensions) -> passed at

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = store_from_env()
        return self._store

    async def retrieve(self, query: str, domain: str, k: int = DEFAULT_K) -> list[Passage]:
        check_request(query, domain, k)
        role = (self._model_config or load_config()).role(self.model_role)
        store = self.store
        await self._check_index(store, role.model, role.dimensions or 0)
        [vector] = await embed([role.query_prefix + query], model_role=self.model_role)
        results = await asyncio.to_thread(store.search, vector, domain, k)
        return [record.to_passage() for record, _ in results]

    async def _check_index(self, store: VectorStore, model: str, dimensions: int) -> None:
        """Raise ConfigError for an empty index or one from another model; a pass is trusted
        for INFO_TTL_S."""
        key = (model, dimensions)
        passed = self._checked.get(key)
        if passed is not None and self._clock() - passed < INFO_TTL_S:
            return
        info = await asyncio.to_thread(store.info)
        if not info.count:
            raise ConfigError(EMPTY_INDEX)
        check_model(info, model, dimensions)
        self._checked[key] = self._clock()
