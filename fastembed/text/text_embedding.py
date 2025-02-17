from typing import Optional, Union, Iterable, List, Dict, Any, Type

import numpy as np

from fastembed.text.e5_onnx_embedding import E5OnnxEmbedding
from fastembed.text.jina_onnx_embedding import JinaOnnxEmbedding
from fastembed.text.onnx_embedding import OnnxTextEmbedding
from fastembed.text.text_embedding_base import TextEmbeddingBase


class TextEmbedding(TextEmbeddingBase):
    EMBEDDINGS_REGISTRY: List[Type[TextEmbeddingBase]] = [
        OnnxTextEmbedding,
        E5OnnxEmbedding,
        JinaOnnxEmbedding,
    ]

    @classmethod
    def list_supported_models(cls) -> List[Dict[str, Any]]:
        """
        Lists the supported models.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing the model information.

            Example:
                ```
                [
                    {
                        "model": "intfloat/multilingual-e5-large",
                        "dim": 1024,
                        "description": "Multilingual model, e5-large. Recommend using this model for non-English languages",
                        "size_in_GB": 2.24,
                        "sources": {
                            "gcp": "https://storage.googleapis.com/qdrant-fastembed/fast-multilingual-e5-large.tar.gz",
                            "hf": "qdrant/multilingual-e5-large-onnx",
                        }
                    }
                ]
                ```
        """
        result = []
        for embedding in cls.EMBEDDINGS_REGISTRY:
            result.extend(embedding.list_supported_models())
        return result

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        cache_dir: Optional[str] = None,
        threads: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(model_name, cache_dir, threads, **kwargs)

        for embedding in self.EMBEDDINGS_REGISTRY:
            supported_models = embedding.list_supported_models()
            if any(model_name == model["model"] for model in supported_models):
                self.model = embedding(model_name, cache_dir, threads, **kwargs)
                return

        raise ValueError(
            f"Model {model_name} is not supported in TextEmbedding."
            "Please check the supported models using `TextEmbedding.list_supported_models()`"
        )

    def embed(
        self,
        documents: Union[str, Iterable[str]],
        batch_size: int = 256,
        parallel: Optional[int] = None,
        **kwargs,
    ) -> Iterable[np.ndarray]:
        """
        Encode a list of documents into list of embeddings.
        We use mean pooling with attention so that the model can handle variable-length inputs.

        Args:
            documents: Iterator of documents or single document to embed
            batch_size: Batch size for encoding -- higher values will use more memory, but be faster
            parallel:
                If > 1, data-parallel encoding will be used, recommended for offline encoding of large datasets.
                If 0, use all available cores.
                If None, don't use data-parallel processing, use default onnxruntime threading instead.

        Returns:
            List of embeddings, one per document
        """
        yield from self.model.embed(documents, batch_size, parallel, **kwargs)
