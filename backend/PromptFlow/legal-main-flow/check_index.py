"""Check the exact current local contract index, never an old full-text marker."""

from typing import Optional

from promptflow.core import tool
from model_config_loader import get_local_config_dir
from contract_index import check_contract_index


@tool
def my_python_tool(filename: str, document_text: str = "",
                   document_paragraphs: Optional[list] = None) -> bool:
    return check_contract_index(
        filename, document_text, document_paragraphs,
        get_local_config_dir() / ".ally-contract-index",
        get_local_config_dir() / "contract_index.json",
    )["Found"]
