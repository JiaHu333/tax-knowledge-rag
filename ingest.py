import argparse
import hashlib
import re
from pathlib import Path

from langchain_community.document_loaders import (
    Docx2txtLoader,
    TextLoader,
    PyPDFLoader,
    UnstructuredExcelLoader,
    UnstructuredPowerPointLoader,
)
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma


# ==================================================
# Basic configuration
# ==================================================

DOCS_DIR = Path("docs")
DB_DIR = Path("db")

EMBEDDING_MODEL = "nomic-embed-text"

LANGUAGE_CONFIG = {
    "zh": {
        "docs_dir": DOCS_DIR / "CN",
        "collection_name": "knowledge_base_cn",
    },
    "en": {
        "docs_dir": DOCS_DIR / "EN",
        "collection_name": "knowledge_base_en",
    },
}

SUPPORTED_SUFFIXES = {
    ".docx",
    ".txt",
    ".md",
    ".pdf",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
}

MARKDOWN_HEADERS = [
    ("#", "title"),
    ("##", "heading_2"),
    ("###", "heading_3"),
    ("####", "heading_4"),
]

TAX_TYPE_PATTERNS = {
    "VAT": [
        r"(?<![a-z])vat(?![a-z])",
        r"value added tax",
        r"增值税",
        r"进项税",
        r"销项税",
        r"视同销售",
        r"umsatzsteuer",
        r"vorsteuer",
    ],
    "CIT": [
        r"(?<![a-z])cit(?![a-z])",
        r"corporate income tax",
        r"corporation tax",
        r"企业所得税",
        r"körperschaftsteuer",
        r"gewerbesteuer",
        r"trade tax",
        r"营业税",
    ],
    "Payroll": [
        r"payroll tax",
        r"wage tax",
        r"工资税",
        r"员工所得税",
        r"个人所得税",
        r"lohnsteuer",
    ],
    "Withholding": [
        r"withholding tax",
        r"预提税",
        r"代扣税",
        r"源泉税",
        r"quellensteuer",
        r"kapitalertragsteuer",
    ],
}


# ==================================================
# File utilities
# ==================================================

def get_file_hash(file_path):
    """Calculate the SHA-256 hash of a file."""

    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for block in iter(lambda: file.read(8192), b""):
            sha256.update(block)

    return sha256.hexdigest()


def get_loader(file_path):
    """Return the appropriate document loader."""

    suffix = file_path.suffix.lower()

    if suffix == ".docx":
        return Docx2txtLoader(str(file_path))

    if suffix in {".txt", ".md"}:
        return TextLoader(
            str(file_path),
            encoding="utf-8",
        )

    if suffix == ".pdf":
        return PyPDFLoader(str(file_path))

    if suffix in {".xlsx", ".xls"}:
        return UnstructuredExcelLoader(str(file_path))

    if suffix in {".pptx", ".ppt"}:
        return UnstructuredPowerPointLoader(str(file_path))

    return None


def get_supported_files(language_docs_dir):
    """Return all supported files in one language directory."""

    if not language_docs_dir.exists():
        print(f"Directory does not exist: {language_docs_dir}")
        return []

    files = []

    for file_path in language_docs_dir.rglob("*"):
        if (
            file_path.is_file()
            and file_path.suffix.lower() in SUPPORTED_SUFFIXES
        ):
            files.append(file_path)

    return sorted(files)


# ==================================================
# Document loading and metadata
# ==================================================

def load_file(file_path, language, language_docs_dir):
    """Load one file and add file-level metadata."""

    loader = get_loader(file_path)

    if loader is None:
        print(f"Skip unsupported file: {file_path.name}")
        return []

    print(f"Loading file: {file_path}")

    loaded_docs = loader.load()

    relative_path = file_path.relative_to(
        language_docs_dir
    )
    relative_path_str = str(relative_path)
    file_hash = get_file_hash(file_path)

    for document in loaded_docs:
        document.metadata["source"] = file_path.name
        document.metadata["path"] = relative_path_str
        document.metadata["language"] = language
        document.metadata["file_hash"] = file_hash
        document.metadata["file_type"] = (
            file_path.suffix.lower()
        )

    return loaded_docs


# ==================================================
# Text splitting
# ==================================================

def create_markdown_header_splitter():
    """Create a splitter that records Markdown headings."""

    return MarkdownHeaderTextSplitter(
        headers_to_split_on=MARKDOWN_HEADERS,
        strip_headers=False,
    )


def create_recursive_splitter():
    """Create the final size-based text splitter."""

    return RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        separators=[
            "\n\n",
            "\n",
            "。",
            "；",
            "？",
            "！",
            ". ",
            "; ",
            "? ",
            "! ",
            " ",
            "",
        ],
    )


def split_markdown_document(document):
    """
    Split a Markdown document by heading structure first.

    File-level metadata is copied to every heading section.
    """

    header_splitter = create_markdown_header_splitter()

    sections = header_splitter.split_text(
        document.page_content
    )

    for section in sections:
        section.metadata = {
            **document.metadata,
            **section.metadata,
        }

    return sections


def find_tax_type(text):
    """Return an explicit tax type found in heading text."""

    normalized_text = text.lower()

    for tax_type, patterns in TAX_TYPE_PATTERNS.items():
        if any(
            re.search(pattern, normalized_text)
            for pattern in patterns
        ):
            return tax_type

    return None


def detect_chunk_tax_type(metadata):
    """
    Detect a chunk's tax type from its heading hierarchy.

    The nearest heading has priority. The document title and
    filename are fallbacks. Body text is intentionally excluded
    because it may merely refer to another tax type.
    """

    heading_candidates = [
        metadata.get("heading_4", ""),
        metadata.get("heading_3", ""),
        metadata.get("heading_2", ""),
        metadata.get("title", ""),
        metadata.get("source", ""),
    ]

    for candidate in heading_candidates:
        tax_type = find_tax_type(candidate)

        if tax_type:
            return tax_type

    return "General"


def add_heading_context(document):
    """
    Add the document title and heading path to chunk text.

    Chroma embeds page_content, not ordinary metadata values.
    Therefore the heading context is added directly to the text.
    """

    metadata = document.metadata

    tax_type = detect_chunk_tax_type(metadata)
    metadata["tax_type"] = tax_type

    title = metadata.get("title")

    heading_path = [
        metadata.get("heading_2"),
        metadata.get("heading_3"),
        metadata.get("heading_4"),
    ]
    heading_path = [
        heading
        for heading in heading_path
        if heading
    ]

    context_lines = []

    if metadata.get("language") == "zh":
        context_lines.append(
            f"税种：{tax_type}"
        )

        if title:
            context_lines.append(
                f"文档标题：{title}"
            )

        if heading_path:
            context_lines.append(
                "章节：" + " > ".join(heading_path)
            )
    else:
        context_lines.append(
            f"Tax type: {tax_type}"
        )

        if title:
            context_lines.append(
                f"Document title: {title}"
            )

        if heading_path:
            context_lines.append(
                "Section: " + " > ".join(heading_path)
            )

    if context_lines:
        document.page_content = (
            "\n".join(context_lines)
            + "\n\n"
            + document.page_content.strip()
        )
    else:
        document.page_content = (
            document.page_content.strip()
        )

    return document


def split_documents(documents):
    """
    Split all loaded documents into final chunks.

    Markdown files are split by headings before the normal
    size-based split. Other file types use only the normal split.
    """

    recursive_splitter = create_recursive_splitter()
    sections = []

    for document in documents:
        if document.metadata.get("file_type") == ".md":
            sections.extend(
                split_markdown_document(document)
            )
        else:
            sections.append(document)

    chunks = recursive_splitter.split_documents(sections)

    final_chunks = []
    chunk_counters = {}

    for chunk in chunks:
        if not chunk.page_content.strip():
            continue

        chunk = add_heading_context(chunk)

        # Store a stable order inside each source file. This is
        # used when an overview question needs all relevant
        # sections from the same document.
        path = chunk.metadata.get("path", "")
        chunk_index = chunk_counters.get(path, 0)

        chunk.metadata["chunk_index"] = chunk_index
        chunk_counters[path] = chunk_index + 1

        final_chunks.append(chunk)

    return final_chunks


# ==================================================
# Update one language collection
# ==================================================

def update_language_collection(
    language,
    language_docs_dir,
    collection_name,
    embeddings,
):
    """Update one Chroma collection incrementally."""

    print("\n" + "=" * 60)
    print(f"Language: {language}")
    print(f"Document directory: {language_docs_dir}")
    print(f"Collection: {collection_name}")
    print("=" * 60)

    vectorstore = Chroma(
        persist_directory=str(DB_DIR),
        embedding_function=embeddings,
        collection_name=collection_name,
    )

    # --------------------------------------------------
    # 1. Read existing file information from Chroma
    # --------------------------------------------------

    existing_data = vectorstore.get(
        include=["metadatas"]
    )

    existing_files = {}

    for metadata in existing_data["metadatas"]:
        if not metadata:
            continue

        path = metadata.get("path")
        file_hash = metadata.get("file_hash")

        if path:
            existing_files[path] = file_hash

    # --------------------------------------------------
    # 2. Read current files from the language directory
    # --------------------------------------------------

    current_files = get_supported_files(
        language_docs_dir
    )

    current_paths = {
        str(file_path.relative_to(language_docs_dir))
        for file_path in current_files
    }

    # --------------------------------------------------
    # 3. Remove files deleted from the directory
    # --------------------------------------------------

    deleted_files = (
        set(existing_files.keys()) - current_paths
    )

    for deleted_path in deleted_files:
        print(
            "Deleting removed file from database: "
            f"{deleted_path}"
        )

        vectorstore.delete(
            where={"path": deleted_path}
        )

    # --------------------------------------------------
    # 4. Check new and modified files
    # --------------------------------------------------

    documents_to_add = []

    added_count = 0
    updated_count = 0
    skipped_count = 0
    deleted_count = len(deleted_files)

    for file_path in current_files:
        relative_path = str(
            file_path.relative_to(language_docs_dir)
        )

        current_hash = get_file_hash(file_path)

        if relative_path not in existing_files:
            print(f"New file: {relative_path}")

            documents_to_add.extend(
                load_file(
                    file_path=file_path,
                    language=language,
                    language_docs_dir=language_docs_dir,
                )
            )

            added_count += 1

        elif existing_files[relative_path] != current_hash:
            print(f"Modified file: {relative_path}")

            vectorstore.delete(
                where={"path": relative_path}
            )

            documents_to_add.extend(
                load_file(
                    file_path=file_path,
                    language=language,
                    language_docs_dir=language_docs_dir,
                )
            )

            updated_count += 1

        else:
            print(f"Unchanged, skip: {relative_path}")
            skipped_count += 1

    # --------------------------------------------------
    # 5. Split and add new or modified documents
    # --------------------------------------------------

    if documents_to_add:
        chunks = split_documents(documents_to_add)

        print(
            f"Adding {len(chunks)} "
            "new/updated chunks..."
        )

        vectorstore.add_documents(chunks)
    else:
        print(
            "No new or modified documents to add."
        )

    # --------------------------------------------------
    # 6. Language update summary
    # --------------------------------------------------

    print(f"\nUpdate summary for {language}:")
    print(f"  Added:   {added_count} file(s)")
    print(f"  Updated: {updated_count} file(s)")
    print(f"  Deleted: {deleted_count} file(s)")
    print(f"  Skipped: {skipped_count} file(s)")


# ==================================================
# Main program
# ==================================================

def configure_paths(docs_dir, db_dir):
    """Apply command-line locations without changing ingestion behavior."""

    global DB_DIR
    global DOCS_DIR
    global LANGUAGE_CONFIG

    DOCS_DIR = Path(docs_dir)
    DB_DIR = Path(db_dir)
    LANGUAGE_CONFIG = {
        "zh": {
            "docs_dir": DOCS_DIR / "CN",
            "collection_name": "knowledge_base_cn",
        },
        "en": {
            "docs_dir": DOCS_DIR / "EN",
            "collection_name": "knowledge_base_en",
        },
    }


def main(docs_dir="docs", db_dir="db", embedding_model=EMBEDDING_MODEL):
    configure_paths(docs_dir=docs_dir, db_dir=db_dir)
    if not DOCS_DIR.is_dir():
        raise SystemExit(f"Document directory not found: {DOCS_DIR}")

    print("Checking knowledge bases...")

    embeddings = OllamaEmbeddings(
        model=embedding_model
    )

    for language, config in LANGUAGE_CONFIG.items():
        if not config["docs_dir"].is_dir():
            print(f"Skip missing language directory: {config['docs_dir']}")
            continue
        update_language_collection(
            language=language,
            language_docs_dir=config["docs_dir"],
            collection_name=config["collection_name"],
            embeddings=embeddings,
        )

    print("\nKnowledge base update completed.")


def parse_args():
    parser = argparse.ArgumentParser(description="Build or update the demo Chroma database.")
    parser.add_argument("--docs", default="docs", help="Document root (default: docs)")
    parser.add_argument("--db", default="db", help="Chroma directory (default: db)")
    parser.add_argument(
        "--embedding-model",
        default=EMBEDDING_MODEL,
        help="Ollama embedding model (default: nomic-embed-text)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(
        docs_dir=args.docs,
        db_dir=args.db,
        embedding_model=args.embedding_model,
    )
