"""FastAPI route modules."""

from .game_disclosure import router as game_disclosure_router
from .game_list import router as game_list_router
from .recommendations import router as recommendation_router\nfrom .timeline import router as timeline_router

__all__ = ["game_disclosure_router", "game_list_router", "recommendation_router", "timeline_router"]
