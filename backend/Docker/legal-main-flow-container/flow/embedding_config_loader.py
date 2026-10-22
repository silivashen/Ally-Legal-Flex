import json

from model_config_loader import find_local_config


def get_embedding_config(connection=None):
    """Read only the frontend configuration; retain connection for flow compatibility."""
    try:
        config_path = find_local_config("model_config.json")
    except FileNotFoundError as exc:
        raise RuntimeError(
            "未找到本机 Embedding 配置，请在 Model Settings 中填写并保存。"
        ) from exc
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法读取本机 Embedding 配置文件。") from exc
    if not isinstance(config, dict):
        raise RuntimeError("本机 Embedding 配置格式无效。")

    fields = ("embedding_base_url", "embedding_model", "embedding_key")
    if any(not isinstance(config.get(field), str) or not config[field].strip()
           for field in fields):
        raise RuntimeError(
            "本机 Embedding 配置不完整。请在 Model Settings 中填写 "
            "Embedding API Base URL、Model 和 API Key，然后保存。"
        )
    return {
        "base_url": config["embedding_base_url"].strip().rstrip("/"),
        "model": config["embedding_model"].strip(),
        "api_key": config["embedding_key"].strip(),
    }


def get_embedding_key(connection=None):
    return get_embedding_config(connection)["api_key"]
