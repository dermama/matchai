"""Health check endpoint."""
import time
from fastapi import APIRouter
from core.state_machine import get_state_machine

router = APIRouter()
START_TIME = time.time()


@router.get("/health")
async def health():
    sm = get_state_machine()
    task = sm.active_task
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME),
        "active_task": task.task_id if task else None,
        "task_state": task.state if task else None,
    }


@router.get("/")
async def root():
    return {"message": "🤖 Matchai AI Agent Server", "version": "1.0.0"}
