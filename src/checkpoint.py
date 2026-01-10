"""Checkpoint management for recovery from interruptions."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class CheckpointManager:
    """Manages checkpoint state for resumable processing."""

    def __init__(self, checkpoint_dir: Path, job_id: str):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoint files
            job_id: Unique identifier for this processing job
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.job_id = job_id
        self.checkpoint_file = self.checkpoint_dir / f"{job_id}.json"
        self.state = self._load_or_create()

    def _load_or_create(self) -> dict:
        """Load existing checkpoint or create new one."""
        if self.checkpoint_file.exists():
            with open(self.checkpoint_file, 'r') as f:
                return json.load(f)
        return {
            'job_id': self.job_id,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'status': 'initialized',
            'current_step': None,
            'completed_steps': [],
            'failed_steps': [],
            'data': {},
            'errors': []
        }

    def save(self):
        """Save current state to checkpoint file."""
        self.state['updated_at'] = datetime.now().isoformat()
        with open(self.checkpoint_file, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def start_step(self, step_name: str, metadata: Optional[dict] = None):
        """Mark a step as started."""
        self.state['current_step'] = step_name
        self.state['status'] = 'processing'
        if metadata:
            self.state['data'][f'{step_name}_metadata'] = metadata
        self.save()

    def complete_step(self, step_name: str, result: Optional[Any] = None):
        """Mark a step as completed."""
        if step_name not in self.state['completed_steps']:
            self.state['completed_steps'].append(step_name)
        self.state['current_step'] = None
        if result is not None:
            self.state['data'][f'{step_name}_result'] = result
        self.save()

    def fail_step(self, step_name: str, error: str):
        """Mark a step as failed."""
        self.state['failed_steps'].append({
            'step': step_name,
            'error': error,
            'timestamp': datetime.now().isoformat()
        })
        self.state['errors'].append(error)
        self.state['status'] = 'failed'
        self.save()

    def is_step_completed(self, step_name: str) -> bool:
        """Check if a step has been completed."""
        return step_name in self.state['completed_steps']

    def get_step_result(self, step_name: str) -> Optional[Any]:
        """Get the result of a completed step."""
        return self.state['data'].get(f'{step_name}_result')

    def set_data(self, key: str, value: Any):
        """Store arbitrary data in checkpoint."""
        self.state['data'][key] = value
        self.save()

    def get_data(self, key: str, default: Any = None) -> Any:
        """Retrieve data from checkpoint."""
        return self.state['data'].get(key, default)

    def mark_complete(self):
        """Mark the entire job as complete."""
        self.state['status'] = 'completed'
        self.state['completed_at'] = datetime.now().isoformat()
        self.save()

    def mark_token_limit(self):
        """Mark that we hit token limits - can resume later."""
        self.state['status'] = 'token_limit'
        self.state['token_limit_at'] = datetime.now().isoformat()
        self.save()

    def can_resume(self) -> bool:
        """Check if this job can be resumed."""
        return self.state['status'] in ['processing', 'token_limit', 'failed']

    def clear(self):
        """Clear checkpoint and start fresh."""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
        self.state = self._load_or_create()

    def summary(self) -> str:
        """Get a human-readable summary of checkpoint state."""
        lines = [
            f"Job: {self.job_id}",
            f"Status: {self.state['status']}",
            f"Created: {self.state['created_at']}",
            f"Updated: {self.state['updated_at']}",
            f"Completed steps: {', '.join(self.state['completed_steps']) or 'none'}",
            f"Current step: {self.state['current_step'] or 'none'}",
        ]
        if self.state['errors']:
            lines.append(f"Errors: {len(self.state['errors'])}")
        return '\n'.join(lines)
