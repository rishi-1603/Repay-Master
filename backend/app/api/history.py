"""Saved-scenario history: list / create / delete, scoped to the
authenticated user.

Ownership is enforced at the SQL layer inside utils/auth.py (`WHERE id = ?
AND username = ?`), not just here -- so even a bug in this router could
never let one user read or delete another user's saved scenario by
guessing an id.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.auth import delete_scenario, get_saved_scenarios, save_scenario  # noqa: E402
from app.core.security import get_current_username
from app.schemas.auth import ScenarioCreate, ScenarioRead

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[ScenarioRead])
def list_history(username: str = Depends(get_current_username)) -> list[ScenarioRead]:
    return [ScenarioRead(**row) for row in get_saved_scenarios(username)]


@router.post("", response_model=ScenarioRead, status_code=201)
def create_history_entry(
    payload: ScenarioCreate, username: str = Depends(get_current_username)
) -> ScenarioRead:
    new_id = save_scenario(username, payload.label, payload.params)
    # save_scenario only returns the new row's id, not the full record (it's
    # shared with the Streamlit app, which never needed the full row back)
    # -- re-fetch to hand the client a complete ScenarioRead, including the
    # server-assigned id and created_at timestamp it needs for later delete.
    match = next((row for row in get_saved_scenarios(username) if row["id"] == new_id), None)
    if match is None:  # pragma: no cover - would only happen on a concurrent delete race
        raise HTTPException(status_code=500, detail="Scenario was saved but could not be re-read.")
    return ScenarioRead(**match)


@router.delete("/{scenario_id}", status_code=204)
def delete_history_entry(scenario_id: int, username: str = Depends(get_current_username)) -> None:
    deleted = delete_scenario(scenario_id, username)
    if not deleted:
        # Same 404 whether the id doesn't exist at all or belongs to another
        # user -- doesn't confirm/deny another account's data to the caller.
        raise HTTPException(status_code=404, detail="Scenario not found.")
