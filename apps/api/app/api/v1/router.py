from fastapi import APIRouter

from app.modules.chat.api import router as chat_router
from app.modules.identity.api import router as identity_router
from app.modules.knowledge.api import router as knowledge_router
from app.modules.memory.api import router as memory_router
from app.modules.planner.api import router as planner_router
from app.modules.tools.api import router as tools_router

router = APIRouter(prefix="/api/v1")
router.include_router(identity_router)
router.include_router(chat_router)
router.include_router(memory_router)
router.include_router(knowledge_router)
router.include_router(planner_router)
router.include_router(tools_router)
