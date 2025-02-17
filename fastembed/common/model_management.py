import os
import shutil
import tarfile
from pathlib import Path
from typing import List, Optional, Dict, Any

import requests
from huggingface_hub import snapshot_download
from huggingface_hub.utils import RepositoryNotFoundError
from tqdm import tqdm
from loguru import logger


def locate_model_file(model_dir: Path, file_names: List[str]) -> Path:
    """
    Find model path for both TransformerJS style `onnx`  subdirectory structure and direct model weights structure used
    by Optimum and Qdrant
    """
    if not model_dir.is_dir():
        raise ValueError(f"Provided model path '{model_dir}' is not a directory.")

    for file_name in file_names:
        file_paths = [path for path in model_dir.rglob(file_name) if path.is_file()]

        if file_paths:
            return file_paths[0]

    raise ValueError(f"Could not find either of {', '.join(file_names)} in {model_dir}")


class ModelManagement:
    @classmethod
    def download_file_from_gcs(cls, url: str, output_path: str, show_progress: bool = True) -> str:
        """
        Downloads a file from Google Cloud Storage.

        Args:
            url (str): The URL to download the file from.
            output_path (str): The path to save the downloaded file to.
            show_progress (bool, optional): Whether to show a progress bar. Defaults to True.

        Returns:
            str: The path to the downloaded file.
        """

        if os.path.exists(output_path):
            return output_path
        response = requests.get(url, stream=True)

        # Handle HTTP errors
        if response.status_code == 403:
            raise PermissionError(
                "Authentication Error: You do not have permission to access this resource. "
                "Please check your credentials."
            )

        # Get the total size of the file
        total_size_in_bytes = int(response.headers.get("content-length", 0))

        # Warn if the total size is zero
        if total_size_in_bytes == 0:
            print(f"Warning: Content-length header is missing or zero in the response from {url}.")

        show_progress = total_size_in_bytes and show_progress

        with tqdm(total=total_size_in_bytes, unit="iB", unit_scale=True, disable=not show_progress) as progress_bar:
            with open(output_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:  # Filter out keep-alive new chunks
                        progress_bar.update(len(chunk))
                        file.write(chunk)
        return output_path

    @classmethod
    def download_files_from_huggingface(cls, hf_source_repo: str, cache_dir: Optional[str] = None) -> str:
        """
        Downloads a model from HuggingFace Hub.
        Args:
            hf_source_repo (str): Name of the model on HuggingFace Hub, e.g. "qdrant/all-MiniLM-L6-v2-onnx".
            cache_dir (Optional[str]): The path to the cache directory.
        Returns:
            Path: The path to the model directory.
        """

        return snapshot_download(
            repo_id=hf_source_repo,
            ignore_patterns=["model.safetensors", "pytorch_model.bin"],
            cache_dir=cache_dir,
        )

    @classmethod
    def decompress_to_cache(cls, targz_path: str, cache_dir: str):
        """
        Decompresses a .tar.gz file to a cache directory.

        Args:
            targz_path (str): Path to the .tar.gz file.
            cache_dir (str): Path to the cache directory.

        Returns:
            cache_dir (str): Path to the cache directory.
        """
        # Check if targz_path exists and is a file
        if not os.path.isfile(targz_path):
            raise ValueError(f"{targz_path} does not exist or is not a file.")

        # Check if targz_path is a .tar.gz file
        if not targz_path.endswith(".tar.gz"):
            raise ValueError(f"{targz_path} is not a .tar.gz file.")

        try:
            # Open the tar.gz file
            with tarfile.open(targz_path, "r:gz") as tar:
                # Extract all files into the cache directory
                tar.extractall(path=cache_dir)
        except tarfile.TarError as e:
            # If any error occurs while opening or extracting the tar.gz file,
            # delete the cache directory (if it was created in this function)
            # and raise the error again
            if "tmp" in cache_dir:
                shutil.rmtree(cache_dir)
            raise ValueError(f"An error occurred while decompressing {targz_path}: {e}")

        return cache_dir

    @classmethod
    def retrieve_model_gcs(cls, model_name: str, source_url: str, cache_dir: str) -> Path:
        fast_model_name = f"fast-{model_name.split('/')[-1]}"

        cache_tmp_dir = Path(cache_dir) / "tmp"
        model_tmp_dir = cache_tmp_dir / fast_model_name
        model_dir = Path(cache_dir) / fast_model_name

        # check if the model_dir and the model files are both present for macOS
        if model_dir.exists() and len(list(model_dir.glob("*"))) > 0:
            return model_dir

        if model_tmp_dir.exists():
            shutil.rmtree(model_tmp_dir)

        cache_tmp_dir.mkdir(parents=True, exist_ok=True)

        model_tar_gz = Path(cache_dir) / f"{fast_model_name}.tar.gz"

        cls.download_file_from_gcs(
            source_url,
            output_path=str(model_tar_gz),
        )

        cls.decompress_to_cache(targz_path=str(model_tar_gz), cache_dir=str(cache_tmp_dir))
        assert model_tmp_dir.exists(), f"Could not find {model_tmp_dir} in {cache_tmp_dir}"

        model_tar_gz.unlink()
        # Rename from tmp to final name is atomic
        model_tmp_dir.rename(model_dir)

        return model_dir

    @classmethod
    def download_model(cls, model: Dict[str, Any], cache_dir: Path) -> Path:
        """
        Downloads a model from HuggingFace Hub or Google Cloud Storage.

        Args:
            model (Dict[str, Any]): The model description.
                Example:
                ```
                {
                    "model": "BAAI/bge-base-en-v1.5",
                    "dim": 768,
                    "description": "Base English model, v1.5",
                    "size_in_GB": 0.44,
                    "sources": {
                        "url": "https://storage.googleapis.com/qdrant-fastembed/fast-bge-base-en-v1.5.tar.gz",
                        "hf": "qdrant/bge-base-en-v1.5-onnx-q",
                    }
                }
                ```
            cache_dir (str): The path to the cache directory.

        Returns:
            Path: The path to the downloaded model directory.
        """

        hf_source = model.get("sources", {}).get("hf")
        url_source = model.get("sources", {}).get("url")

        if hf_source:
            try:
                return Path(cls.download_files_from_huggingface(hf_source, cache_dir=str(cache_dir)))
            except (EnvironmentError, RepositoryNotFoundError, ValueError) as e:
                logger.error(f"Could not download model from HuggingFace: {e}" "Falling back to other sources.")

        if url_source:
            return cls.retrieve_model_gcs(model["model"], url_source, str(cache_dir))

        raise ValueError(f"Could not download model {model['model']} from any source.")
