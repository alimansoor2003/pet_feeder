"""
identifier.py
-------------
Single responsibility: turn an image of an animal into an embedding
vector, and compare it against the embeddings of pets stored in
database.json to find the best match.

Knows nothing about YOLO, the web layer, or feeding logic. It only
answers: "whose pet is this, and how confident am I?"
"""

import json
import os
from typing import Dict, Optional, Tuple

import numpy as np
import torch
from PIL import Image
from torchvision import models, transforms

# MVP device rule: everything stays on CPU. Never mix CPU/CUDA tensors.
DEVICE = "cpu"

# Below this cosine similarity, the best match is reported as "Unknown".
SIMILARITY_THRESHOLD = 0.75


def _build_embedding_model() -> torch.nn.Module:
    """
    Use timm's ViT (Vision Transformer) model.
    ViT is state-of-the-art for fine-grained identification.
    """
    import timm
    
    model = timm.create_model(
        'vit_small_patch16_224',  # Small ViT, 224x224 input
        pretrained=True,
        num_classes=0  # Remove classification head -> feature extraction
    )
    model.eval()
    model.to(DEVICE)
    return model


_TRANSFORM = transforms.Compose(
    [
        transforms.Resize((256, 256)),      # Larger input
        transforms.CenterCrop((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        ),
    ]
)


class Identifier:
    def __init__(self, database_path: str = "database.json"):
        self.database_path = database_path
        self.model = _build_embedding_model()
        self._embedding_cache: Dict[str, np.ndarray] = {}

    # -- embedding helpers ---------------------------------------------------

    def embed(self, image: Image.Image) -> np.ndarray:
        image = image.convert("RGB")
        tensor = _TRANSFORM(image).unsqueeze(0).to(DEVICE)
        with torch.no_grad():
            vector = self.model(tensor).squeeze(0).cpu().numpy()
        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

    # -- database access (read-only from here; database.json owns storage) --

    def _load_database(self) -> dict:
        if not os.path.exists(self.database_path):
            return {}
        with open(self.database_path, "r") as f:
            return json.load(f)

    def _get_pet_embedding(self, name: str, image_path: str) -> Optional[np.ndarray]:
        if not os.path.exists(image_path):
            return None
        cache_key = f"{name}:{os.path.getmtime(image_path)}"
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]
        pet_image = Image.open(image_path)
        vector = self.embed(pet_image)
        self._embedding_cache[cache_key] = vector
        return vector

    # -- public API ------------------------------------------------------------

    def match(self, image: Image.Image) -> Tuple[Optional[str], float]:
        """
        Compare `image` (already cropped to the animal by the detector)
        against every pet in the database.

        Returns:
            (pet_name, score) if the best match clears SIMILARITY_THRESHOLD
            (None, score)      otherwise (i.e. "Unknown")
        """
        query_vector = self.embed(image)
        database = self._load_database()

        best_name = None
        best_score = 0.0

        for name, info in database.items():
            pet_vector = self._get_pet_embedding(name, info["image"])
            if pet_vector is None:
                continue
            score = self._cosine_similarity(query_vector, pet_vector)
            if score > best_score:
                best_score = score
                best_name = name

        if best_name is not None and best_score >= SIMILARITY_THRESHOLD:
            return best_name, best_score
        return None, best_score
