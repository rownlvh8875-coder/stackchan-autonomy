from io import BytesIO

from PIL import Image

from .models import Observation


class Perception:
    """Small grayscale signature; no original media retained or written to disk."""

    def __init__(self, threshold: float = 0.03):
        self.threshold = threshold
        self._previous: bytes | None = None

    def process(self, observation: Observation) -> Observation:
        if observation.image is None:
            return observation
        with Image.open(BytesIO(observation.image)) as image:
            if image.width * image.height > 4_000_000:
                raise ValueError("image exceeds local processing limit")
            signature = image.convert("L").resize((16, 16)).tobytes()
        previous = self._previous
        changed = previous is None or (
            sum(abs(a - b) for a, b in zip(signature, previous)) / (256 * 255) >= self.threshold
        )
        self._previous = signature
        return observation.model_copy(update={"scene_changed": changed})
