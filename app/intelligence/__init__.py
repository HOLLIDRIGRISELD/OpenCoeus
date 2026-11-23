"""Intelligence layer: embeddings, classification, naming and organisation advice."""

from app.intelligence.classifier import HybridClassifier
from app.intelligence.embeddings import EmbeddingEngine
from app.intelligence.folder_recommender import FolderRecommender, existing_relative_folders
from app.intelligence.llm import LocalLLMClient, LocalLLMResult
from app.intelligence.model_manager import CapabilityStatus, ModelManager
from app.intelligence.naming_engine import FilenameValidator, NamingEngine

__all__ = [
    "CapabilityStatus",
    "EmbeddingEngine",
    "FilenameValidator",
    "FolderRecommender",
    "HybridClassifier",
    "LocalLLMClient",
    "LocalLLMResult",
    "ModelManager",
    "NamingEngine",
    "existing_relative_folders",
]
