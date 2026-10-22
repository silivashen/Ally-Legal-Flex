"""Compatibility route for explicitly preparing the shared local contract index."""

from typing import Optional

from promptflow.core import tool
from model_config_loader import get_local_config_dir
from contract_index import index_document


def index_file():
    return get_local_config_dir() / "contract_index.json"


@tool
def my_python_tool(filename: str, document_text: str,
                   document_paragraphs: Optional[list] = None) -> dict:
    return index_document(filename, document_text, document_paragraphs,
                          get_local_config_dir() / ".ally-contract-index")
