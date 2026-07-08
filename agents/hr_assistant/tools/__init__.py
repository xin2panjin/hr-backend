from .candidate_detail import get_candidate_detail
from .talent_search import search_talent_pool
from .candidate_compare import compare_candidates

HR_ASSISTANT_TOOLS = [
    search_talent_pool,
    get_candidate_detail,
    compare_candidates,
]