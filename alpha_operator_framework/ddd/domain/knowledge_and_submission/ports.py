"""Knowledge and Submission Bounded Context - Ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from .models import KnowledgeBase, SubmissionCase


class KnowledgeRepositoryPort(ABC):
    """Port for persisting and retrieving KnowledgeBase aggregate."""

    @abstractmethod
    def load_knowledge(self) -> KnowledgeBase:
        ...

    @abstractmethod
    def save_knowledge(self, knowledge_base: KnowledgeBase) -> None:
        ...


class SubmissionGatewayPort(ABC):
    """Port for sending approved SubmissionCases to the platform API."""

    @abstractmethod
    def submit_approved_case(self, submission_case: SubmissionCase) -> str:
        """Submit and return platform confirmation ID."""
        ...
